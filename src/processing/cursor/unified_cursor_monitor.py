# Copyright © 2025 Sierra Labs LLC
# SPDX-License-Identifier: AGPL-3.0-only
# License-Filename: LICENSE

"""
UnifiedCursorMonitor: Comprehensive session-aware Cursor telemetry monitoring.

Consolidates all Cursor monitoring into a single unified system with:
- Session-driven workspace activation
- Dual-database monitoring (workspace ItemTable + global cursorDiskKV)
- File watching with polling fallback
- Incremental sync and smart caching
- Complete composer data capture
- Direct writes to cursor_raw_traces table
"""

import asyncio
import aiosqlite
import json
import logging
import redis
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

from .session_monitor import SessionMonitor
from .cursor_utils import FileWatcher, IncrementalSync, SmartCache
from .cursor_extractors import (
    ComposerDataExtractor,
    BackgroundComposerExtractor,
    AgentModeExtractor,
    GenerationExtractor,
    PromptExtractor,
)
from .cursor_raw_traces_writer import CursorRawTracesWriter
from ..database.sqlite_client import SQLiteClient

logger = logging.getLogger(__name__)


@dataclass
class CursorMonitorConfig:
    """Configuration for UnifiedCursorMonitor."""
    poll_interval: float = 60.0  # Fallback polling interval (1 minute)
    debounce_delay: float = 10.0  # Debounce after file change
    query_timeout: float = 1.5  # Database query timeout
    cache_ttl: int = 300  # Cache TTL (5 minutes)
    batch_size: int = 100  # Events per batch
    use_watchdog: bool = True  # Try filesystem events


class WorkspaceMonitor:
    """
    Monitors a single workspace's database.
    Created when session starts, destroyed when session ends.
    """

    def __init__(
        self,
        workspace_hash: str,
        db_path: Path,
        redis_client: redis.Redis,
        config: CursorMonitorConfig,
        itemtable_keys: List[str],
        writer: CursorRawTracesWriter,
        extractors: dict,
    ):
        self.workspace_hash = workspace_hash
        self.db_path = db_path
        self.redis_client = redis_client
        self.config = config
        self.itemtable_keys = itemtable_keys
        self.writer = writer
        self.extractors = extractors

        self.connection: Optional[aiosqlite.Connection] = None
        self.incremental_sync = IncrementalSync()

    async def start(self):
        """Connect to database."""
        try:
            self.connection = await aiosqlite.connect(
                str(self.db_path),
                timeout=self.config.query_timeout
            )
            self.connection.row_factory = aiosqlite.Row

            # Configure for read-only
            await self.connection.execute("PRAGMA query_only=1")
            logger.info(f"Connected to workspace database: {self.workspace_hash}")

        except Exception as e:
            logger.error(f"Failed to connect to workspace database {self.workspace_hash}: {e}")

    async def sync_all_data(self):
        """Initial sync of all monitored keys."""
        if not self.connection:
            return

        try:
            for key in self.itemtable_keys:
                await self._sync_itemtable_key(key)

        except Exception as e:
            logger.error(f"Error during initial sync for {self.workspace_hash}: {e}")

    async def _sync_itemtable_key(self, key: str):
        """Sync a specific ItemTable key."""
        if not self.connection:
            return

        try:
            cursor = await self.connection.execute(
                "SELECT value FROM ItemTable WHERE key = ?",
                (key,)
            )
            row = await cursor.fetchone()

            if not row or not row[0]:
                return

            # Parse value
            value_str = row[0]
            if isinstance(value_str, bytes):
                value_str = value_str.decode('utf-8')

            data = json.loads(value_str)

            # Check if we should process this data
            if not self.incremental_sync.should_process(
                "workspace",
                self.workspace_hash,
                key,
                data
            ):
                return

            # Extract and queue events based on key type
            await self._process_itemtable_data(key, data)

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error for key {key}: {e}")
        except Exception as e:
            logger.error(f"Error syncing key {key}: {e}")

    async def _process_itemtable_data(self, key: str, data):
        """Process ItemTable data based on key type."""
        external_session_id = None  # Will be set from context

        if key == "aiService.generations" and isinstance(data, list):
            # Get only new generations
            new_items = self.incremental_sync.get_new_items(
                "workspace",
                self.workspace_hash,
                key,
                data
            )
            for gen in new_items:
                event = self.extractors['generation'].extract_generation(
                    gen,
                    self.workspace_hash,
                    external_session_id
                )
                await self.writer.write_event(event)

        elif key == "aiService.prompts" and isinstance(data, list):
            # Get only new prompts
            new_items = self.incremental_sync.get_new_items(
                "workspace",
                self.workspace_hash,
                key,
                data
            )
            for prompt in new_items:
                event = self.extractors['prompt'].extract_prompt(
                    prompt,
                    self.workspace_hash,
                    external_session_id
                )
                await self.writer.write_event(event)

        elif key == "workbench.backgroundComposer.workspacePersistentData":
            event = self.extractors['background_composer'].extract_background_composer(
                data,
                self.workspace_hash,
                external_session_id
            )
            await self.writer.write_event(event)

        elif key == "workbench.agentMode.exitInfo":
            event = self.extractors['agent_mode'].extract_agent_mode(
                data,
                self.workspace_hash,
                external_session_id
            )
            await self.writer.write_event(event)

    async def close(self):
        """Close database connection."""
        if self.connection:
            try:
                await self.connection.close()
            except:
                pass
            self.connection = None


class UserLevelListener:
    """
    Monitors user-level Cursor database (~/.cursor-tutor/db/6.vscdb).
    Started once on UnifiedCursorMonitor startup.
    Remains active for entire monitor lifetime.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        config: CursorMonitorConfig,
        writer: CursorRawTracesWriter,
        extractors: dict,
    ):
        self.redis_client = redis_client
        self.config = config
        self.writer = writer
        self.extractors = extractors

        self.db_path: Optional[Path] = None
        self.connection: Optional[aiosqlite.Connection] = None
        self.file_watcher: Optional[FileWatcher] = None
        self.incremental_sync = IncrementalSync()
        self.active_workspaces: Set[str] = set()

    async def start(self):
        """Start monitoring user-level database."""
        # Find user database
        self.db_path = await self._find_user_db()
        if not self.db_path or not self.db_path.exists():
            logger.warning("User-level Cursor database not found")
            return

        # Establish connection
        try:
            self.connection = await aiosqlite.connect(
                str(self.db_path),
                timeout=self.config.query_timeout
            )
            self.connection.row_factory = aiosqlite.Row
            await self.connection.execute("PRAGMA query_only=1")

            logger.info(f"Started user-level listener for {self.db_path}")

            # Start file watcher
            self.file_watcher = FileWatcher(
                self.db_path,
                self._on_user_db_change
            )
            await self.file_watcher.start_watching()

            # Initial sync
            await self._sync_composer_data()

        except Exception as e:
            logger.error(f"Failed to start user-level listener: {e}")

    async def _find_user_db(self) -> Optional[Path]:
        """Find user-level Cursor database."""
        # Primary location
        cursor_dir = Path.home() / ".cursor-tutor"

        # Fallback locations
        if not cursor_dir.exists():
            cursor_dir = Path.home() / ".cursor"

        if not cursor_dir.exists():
            return None

        # Check for database file
        db_dir = cursor_dir / "db"
        if not db_dir.exists():
            return None

        # Try specific version
        db_path = db_dir / "6.vscdb"
        if db_path.exists():
            return db_path

        # Try numbered versions
        for i in range(10):
            candidate = db_dir / f"{i}.vscdb"
            if candidate.exists():
                return candidate

        return None

    async def _on_user_db_change(self):
        """Handle user database changes."""
        try:
            await self._sync_composer_data()
        except Exception as e:
            logger.error(f"Error syncing user database: {e}")

    async def _sync_composer_data(self):
        """Sync composer data from global database."""
        if not self.connection:
            return

        if not self.active_workspaces:
            return

        try:
            # Query composer data
            cursor = await self.connection.execute("""
                SELECT key, value
                FROM cursorDiskKV
                WHERE key LIKE 'composerData:%'
            """)

            rows = await cursor.fetchall()

            for row in rows:
                key = row['key']
                value = row['value']

                if not value:
                    continue

                try:
                    composer_data = json.loads(value)
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse composer data for key {key}")
                    continue

                # Check if this composer belongs to an active workspace
                # (This requires workspace hash in composer data, which may not always be available)

                # Check if data changed using incremental sync
                if self.incremental_sync.should_process('global', 'all', key, value):
                    await self._queue_composer_events(key, composer_data)

        except Exception as e:
            logger.error(f"Error syncing composer data: {e}")

    async def _queue_composer_events(self, key: str, composer_data: dict):
        """Queue composer events."""
        # Extract composer ID from key
        composer_id = key.split(":")[-1] if ":" in key else None

        # For now, we'll use a generic workspace hash since we may not have it in the data
        workspace_hash = "unknown"
        external_session_id = None

        try:
            events = self.extractors['composer'].extract_composer_events(
                composer_data,
                workspace_hash,
                external_session_id
            )

            for event in events:
                await self.writer.write_event(event)

        except Exception as e:
            logger.error(f"Error queuing composer events for {key}: {e}")

    def set_active_workspaces(self, workspaces: Set[str]):
        """Update set of active workspaces."""
        self.active_workspaces = workspaces


class UnifiedCursorMonitor:
    """
    Unified monitor with session-aware workspace activation.
    Consolidates all Cursor database telemetry monitoring.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        session_monitor: SessionMonitor,
        sqlite_client: SQLiteClient,
        config: Optional[CursorMonitorConfig] = None
    ):
        self.redis_client = redis_client
        self.session_monitor = session_monitor
        self.sqlite_client = sqlite_client
        self.config = config or CursorMonitorConfig()

        # Initialize components
        self.writer = CursorRawTracesWriter(sqlite_client, self.config.batch_size)

        # Initialize extractors
        self.extractors = {
            'composer': ComposerDataExtractor(),
            'background_composer': BackgroundComposerExtractor(),
            'agent_mode': AgentModeExtractor(),
            'generation': GenerationExtractor(),
            'prompt': PromptExtractor(),
        }

        self.user_listener = UserLevelListener(
            redis_client,
            self.config,
            self.writer,
            self.extractors
        )

        self.smart_cache = SmartCache(ttl_seconds=self.config.cache_ttl)

        # Keys to monitor in workspace ItemTable
        self.workspace_itemtable_keys = [
            "aiService.generations",
            "aiService.prompts",
            "composer.composerData",
            "workbench.backgroundComposer.workspacePersistentData",
            "workbench.agentMode.exitInfo",
            "interactive.sessions",
            "history.entries",
            "cursorAuth/workspaceOpenedDate",
        ]

        # Workspace management
        self.workspace_monitors: Dict[str, WorkspaceMonitor] = {}
        self.file_watchers: Dict[str, FileWatcher] = {}

        # State
        self.running = False
        self.monitoring_task = None

    async def start(self):
        """Start the unified monitor."""
        self.running = True

        # Start user-level listener (runs for entire lifetime)
        await self.user_listener.start()

        # Register session callbacks
        self.session_monitor.on_session_start = self.on_session_start
        self.session_monitor.on_session_end = self.on_session_end

        # Process existing active sessions
        active = self.session_monitor.get_active_workspaces()
        for workspace_hash, session_info in active.items():
            await self.on_session_start(workspace_hash, session_info)

        # Update user listener with active workspaces
        self.user_listener.set_active_workspaces(set(active.keys()))

        # Start monitoring loop for fallback polling
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())

        logger.info("UnifiedCursorMonitor started")

    async def stop(self):
        """Stop the monitor."""
        self.running = False

        if self.monitoring_task:
            self.monitoring_task.cancel()

        # Stop all workspace monitors
        for workspace_hash in list(self.workspace_monitors.keys()):
            await self.on_session_end(workspace_hash)

        # Flush any pending writes
        await self.writer.flush()

        logger.info("UnifiedCursorMonitor stopped")

    async def on_session_start(self, workspace_hash: str, session_info: dict):
        """Activate monitoring for a workspace when session starts."""
        logger.info(f"Activating monitoring for workspace {workspace_hash}")

        # Skip if already monitoring
        if workspace_hash in self.workspace_monitors:
            logger.debug(f"Already monitoring workspace {workspace_hash}")
            return

        # Find workspace database
        workspace_path = session_info.get("workspace_path")
        db_path = await self._find_workspace_db(workspace_hash, workspace_path)

        if not db_path or not db_path.exists():
            logger.warning(f"Database not found for workspace {workspace_hash}")
            return

        # Create workspace monitor
        monitor = WorkspaceMonitor(
            workspace_hash=workspace_hash,
            db_path=db_path,
            redis_client=self.redis_client,
            config=self.config,
            itemtable_keys=self.workspace_itemtable_keys,
            writer=self.writer,
            extractors=self.extractors,
        )
        await monitor.start()
        self.workspace_monitors[workspace_hash] = monitor

        # Start file watcher
        watcher = FileWatcher(
            db_path,
            lambda: self._on_workspace_db_change(workspace_hash)
        )
        await watcher.start_watching()
        self.file_watchers[workspace_hash] = watcher

        # Initial sync of all data
        await monitor.sync_all_data()

        # Update user listener
        self.user_listener.set_active_workspaces(set(self.workspace_monitors.keys()))

        logger.info(f"Activated monitoring for workspace {workspace_hash}")

    async def on_session_end(self, workspace_hash: str):
        """Deactivate monitoring when session ends."""
        logger.info(f"Deactivating monitoring for workspace {workspace_hash}")

        # Stop file watcher
        if workspace_hash in self.file_watchers:
            await self.file_watchers[workspace_hash].stop()
            del self.file_watchers[workspace_hash]

        # Close workspace monitor
        if workspace_hash in self.workspace_monitors:
            await self.workspace_monitors[workspace_hash].close()
            del self.workspace_monitors[workspace_hash]

        # Clear from cache
        self.smart_cache.invalidate(f"{workspace_hash}:*")

        # Update user listener
        self.user_listener.set_active_workspaces(set(self.workspace_monitors.keys()))

        logger.info(f"Deactivated monitoring for workspace {workspace_hash}")

    async def _find_workspace_db(
        self,
        workspace_hash: str,
        workspace_path: Optional[str]
    ) -> Optional[Path]:
        """Find workspace database file."""
        # Use smart cache
        cache_key = f"db_path:{workspace_hash}"
        cached = await self.smart_cache.get(cache_key)
        if cached:
            return Path(cached)

        # Try workspace path if provided
        if workspace_path:
            workspace_dir = Path(workspace_path)

            # Check .vscode directory
            vscode_db = workspace_dir / ".vscode" / ".vscdb"
            if vscode_db.exists():
                await self.smart_cache.set(cache_key, str(vscode_db))
                return vscode_db

            # Check numbered versions
            for i in range(10):
                vscode_db = workspace_dir / ".vscode" / f"{i}.vscdb"
                if vscode_db.exists():
                    await self.smart_cache.set(cache_key, str(vscode_db))
                    return vscode_db

        return None

    async def _on_workspace_db_change(self, workspace_hash: str):
        """Handle workspace database change."""
        monitor = self.workspace_monitors.get(workspace_hash)
        if monitor:
            try:
                await monitor.sync_all_data()
            except Exception as e:
                logger.error(f"Error syncing workspace {workspace_hash}: {e}")

    async def _monitoring_loop(self):
        """Main monitoring loop for fallback polling."""
        while self.running:
            try:
                # Check all active workspaces
                for workspace_hash in list(self.workspace_monitors.keys()):
                    watcher = self.file_watchers.get(workspace_hash)
                    if watcher and await watcher.check_for_changes():
                        await self._on_workspace_db_change(workspace_hash)

                # Check user-level database
                if self.user_listener.file_watcher:
                    if await self.user_listener.file_watcher.check_for_changes():
                        await self.user_listener._on_user_db_change()

                # Cleanup expired cache entries
                await self.smart_cache.cleanup_expired()

                # Flush any pending writes
                await self.writer.flush()

            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")

            # Wait for next poll interval
            await asyncio.sleep(self.config.poll_interval)
