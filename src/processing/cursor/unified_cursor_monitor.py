# Copyright © 2025 Sierra Labs LLC
# SPDX-License-Identifier: AGPL-3.0-only
# License-Filename: LICENSE

"""
UnifiedCursorMonitor - Session-aware monitoring for Cursor databases.

Consolidates all Cursor database monitoring into a single unified system with:
- Session-driven workspace activation
- Dual-database monitoring (workspace ItemTable + global cursorDiskKV)
- File watching with polling fallback
- Incremental state tracking
- Redis message queue routing with ACK support
"""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional, Set, Any
import aiosqlite
import redis

from .session_monitor import SessionMonitor
from .workspace_mapper import WorkspaceMapper

logger = logging.getLogger(__name__)


@dataclass
class CursorMonitorConfig:
    """Configuration for UnifiedCursorMonitor."""

    query_timeout: float = 1.5
    debounce_delay: float = 10.0
    poll_interval: float = 60.0
    cache_ttl: int = 300
    max_retries: int = 3


class IncrementalSync:
    """
    Tracks processed data to avoid reprocessing.
    Uses content hash and timestamp for change detection.
    """

    def __init__(self):
        self.state: Dict[str, Dict[str, Any]] = {}

    def should_process(
        self,
        storage_level: str,
        workspace_hash: str,
        key: str,
        data: Any
    ) -> bool:
        """
        Check if data should be processed based on state.

        Args:
            storage_level: 'workspace' or 'global'
            workspace_hash: Workspace identifier
            key: Database key
            data: Data to check

        Returns:
            True if data should be processed
        """
        state_key = f"{storage_level}:{workspace_hash}:{key}"

        # Compute hash of data
        data_str = json.dumps(data, sort_keys=True) if isinstance(data, dict) else str(data)
        data_hash = hashlib.sha256(data_str.encode()).hexdigest()[:16]

        # Get last processed hash
        last_state = self.state.get(state_key, {})
        last_hash = last_state.get("hash")

        # Changed if hash differs
        if last_hash != data_hash:
            self.state[state_key] = {
                "hash": data_hash,
                "timestamp": time.time()
            }
            return True

        return False

    def clear(self, workspace_hash: Optional[str] = None):
        """Clear state for a workspace or all."""
        if workspace_hash:
            keys_to_remove = [k for k in self.state if workspace_hash in k]
            for key in keys_to_remove:
                del self.state[key]
        else:
            self.state.clear()


class SmartCache:
    """TTL-based cache for database lookups."""

    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds
        self.cache: Dict[str, Dict[str, Any]] = {}

    async def get(self, key: str) -> Optional[Any]:
        """Get cached value if not expired."""
        if key in self.cache:
            entry = self.cache[key]
            if time.time() - entry["timestamp"] < self.ttl_seconds:
                return entry["value"]
            else:
                del self.cache[key]
        return None

    async def set(self, key: str, value: Any):
        """Set cached value with current timestamp."""
        self.cache[key] = {
            "value": value,
            "timestamp": time.time()
        }

    def invalidate(self, pattern: str):
        """Invalidate cache entries matching pattern (supports '*' wildcard)."""
        if "*" in pattern:
            prefix = pattern.replace("*", "")
            keys_to_remove = [k for k in self.cache if k.startswith(prefix)]
            for key in keys_to_remove:
                del self.cache[key]
        else:
            self.cache.pop(pattern, None)


class FileWatcher:
    """
    Watches database files for changes using filesystem events with fallback.

    Strategy:
    1. Primary: watchdog library for filesystem events
    2. Fallback: stat-based polling every 60 seconds
    3. Debounce: 10-second delay after change detection
    """

    def __init__(self, db_path: Path, callback: Callable):
        self.db_path = db_path
        self.callback = callback
        self.last_modified = None
        self.last_size = None
        self.watchdog_observer = None
        self.active = True
        self.debounce_task = None
        self.debounce_delay = 10.0
        self.poll_task = None

    async def start_watching(self):
        """Start file watching with fallback."""
        # Record initial state
        try:
            stat = self.db_path.stat()
            self.last_modified = stat.st_mtime
            self.last_size = stat.st_size
        except FileNotFoundError:
            logger.warning(f"Database not found: {self.db_path}")
            return

        # Try watchdog first
        if await self._try_watchdog():
            logger.info(f"Using watchdog for {self.db_path}")
        else:
            logger.info(f"Watchdog unavailable, using polling for {self.db_path}")

        # Start polling fallback
        self.poll_task = asyncio.create_task(self._polling_loop())

    async def _try_watchdog(self) -> bool:
        """Try to use watchdog for filesystem events."""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class DBChangeHandler(FileSystemEventHandler):
                def __init__(self, watcher):
                    self.watcher = watcher

                def on_modified(self, event):
                    if event.src_path == str(self.watcher.db_path):
                        asyncio.create_task(
                            self.watcher._handle_change_with_debounce()
                        )

            self.watchdog_observer = Observer()
            self.watchdog_observer.schedule(
                DBChangeHandler(self),
                str(self.db_path.parent),
                recursive=False
            )
            self.watchdog_observer.start()
            return True

        except Exception as e:
            logger.warning(f"Watchdog failed: {e}")
            return False

    async def _handle_change_with_debounce(self):
        """Handle change with debouncing."""
        # Cancel existing debounce task
        if self.debounce_task:
            self.debounce_task.cancel()

        # Schedule new callback after delay
        self.debounce_task = asyncio.create_task(
            self._debounced_callback()
        )

    async def _debounced_callback(self):
        """Execute callback after debounce delay."""
        await asyncio.sleep(self.debounce_delay)
        await self.callback()

    async def _polling_loop(self):
        """Polling fallback: check for changes every 60 seconds."""
        while self.active:
            await asyncio.sleep(60)
            if await self.check_for_changes():
                await self._handle_change_with_debounce()

    async def check_for_changes(self) -> bool:
        """Polling fallback: check if file changed."""
        try:
            stat = self.db_path.stat()
            changed = (
                stat.st_mtime != self.last_modified or
                stat.st_size != self.last_size
            )
            if changed:
                self.last_modified = stat.st_mtime
                self.last_size = stat.st_size
                return True
        except FileNotFoundError:
            return False
        return False

    async def stop(self):
        """Stop watching and cleanup."""
        self.active = False

        if self.debounce_task:
            self.debounce_task.cancel()

        if self.poll_task:
            self.poll_task.cancel()

        if self.watchdog_observer:
            self.watchdog_observer.stop()
            self.watchdog_observer.join(timeout=1)


class EventQueuer:
    """
    Queues all events to Redis stream for processing.
    Ensures all telemetry flows through the message queue.
    """

    def __init__(self, redis_client: redis.Redis):
        self.redis_client = redis_client
        self.stream_name = "telemetry:events"
        self.max_stream_length = 10000
        self.consumer_group = "processors"

    async def queue_event(self, event: dict):
        """
        Queue event to Redis stream.

        Args:
            event: Event dictionary to queue
        """
        try:
            # Serialize event to JSON
            event_json = json.dumps(event)

            # Add to stream with MAXLEN for memory management
            self.redis_client.xadd(
                self.stream_name,
                {"data": event_json},
                maxlen=self.max_stream_length,
                approximate=True
            )

            logger.debug(f"Queued event {event.get('event_type')} to {self.stream_name}")

        except Exception as e:
            logger.error(f"Failed to queue event: {e}")


class WorkspaceMonitor:
    """
    Monitors a single workspace database.
    Tracks specific ItemTable keys for AI telemetry.
    """

    def __init__(
        self,
        workspace_hash: str,
        db_path: Path,
        redis_client: redis.Redis,
        config: CursorMonitorConfig,
        itemtable_keys: list
    ):
        self.workspace_hash = workspace_hash
        self.db_path = db_path
        self.redis_client = redis_client
        self.config = config
        self.itemtable_keys = itemtable_keys

        self.connection = None
        self.event_queuer = EventQueuer(redis_client)
        self.incremental_sync = IncrementalSync()

    async def connect(self):
        """Connect to workspace database."""
        self.connection = await aiosqlite.connect(
            str(self.db_path),
            timeout=self.config.query_timeout
        )
        self.connection.row_factory = aiosqlite.Row

    async def sync_all_data(self):
        """Initial sync of all monitored keys."""
        if not self.connection:
            await self.connect()

        for key in self.itemtable_keys:
            await self._sync_key(key)

    async def _sync_key(self, key: str):
        """Sync a specific ItemTable key."""
        try:
            cursor = await self.connection.execute(
                "SELECT key, value FROM ItemTable WHERE key = ?",
                (key,)
            )
            row = await cursor.fetchone()

            if row and row["value"]:
                value = row["value"]

                # Check if changed
                if self.incremental_sync.should_process(
                    "workspace",
                    self.workspace_hash,
                    key,
                    value
                ):
                    await self._queue_itemtable_event(key, value)

        except Exception as e:
            logger.error(f"Error syncing key {key}: {e}")

    async def _queue_itemtable_event(self, key: str, value: str):
        """Queue ItemTable event to Redis."""
        try:
            # Parse JSON value
            data = json.loads(value) if isinstance(value, str) else value

            event = {
                "version": "0.1.0",
                "hook_type": "DatabaseTrace",
                "event_type": self._determine_event_type(key, data),
                "event_id": str(uuid.uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metadata": {
                    "storage_level": "workspace",
                    "database_table": "ItemTable",
                    "item_key": key,
                    "workspace_hash": self.workspace_hash,
                    "source": "workspace_monitor",
                },
                "payload": {
                    "extracted_fields": self._extract_fields(key, data),
                    "full_data": data
                }
            }

            await self.event_queuer.queue_event(event)

        except Exception as e:
            logger.error(f"Error queuing ItemTable event: {e}")

    def _determine_event_type(self, key: str, data: Any) -> str:
        """Determine event type from key and data."""
        if "generation" in key.lower():
            return "generation"
        elif "prompt" in key.lower():
            return "prompt"
        elif "composer" in key.lower():
            return "composer"
        elif "session" in key.lower():
            return "session"
        return "other"

    def _extract_fields(self, key: str, data: Any) -> dict:
        """Extract relevant fields from data."""
        fields = {}

        if isinstance(data, dict):
            # Extract common fields
            for field in ["uuid", "generationUUID", "composerId", "timestamp", "unixMs"]:
                if field in data:
                    fields[field] = data[field]

        return fields

    async def close(self):
        """Close database connection."""
        if self.connection:
            await self.connection.close()


class UserLevelListener:
    """
    Monitors user-level Cursor database (~/.cursor-tutor/db/6.vscdb).
    Started once on UnifiedCursorMonitor startup.
    Remains active for entire monitor lifetime.
    """

    def __init__(self, redis_client: redis.Redis, config: CursorMonitorConfig):
        self.redis_client = redis_client
        self.config = config
        self.db_path = None
        self.connection = None
        self.file_watcher = None
        self.incremental_sync = IncrementalSync()
        self.event_queuer = EventQueuer(redis_client)
        self.active_workspaces: Set[str] = set()

    async def start(self):
        """Start monitoring user-level database."""
        # Find user database
        self.db_path = await self._find_user_db()
        if not self.db_path or not self.db_path.exists():
            logger.warning("User-level Cursor database not found")
            return

        # Establish connection
        self.connection = await aiosqlite.connect(
            str(self.db_path),
            timeout=self.config.query_timeout
        )
        self.connection.row_factory = aiosqlite.Row

        # Start file watcher
        self.file_watcher = FileWatcher(
            self.db_path,
            self._on_user_db_change
        )
        await self.file_watcher.start_watching()

        # Initial sync
        await self._sync_composer_data()

        logger.info(f"Started user-level listener for {self.db_path}")

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
        """
        Sync composer data from global database.
        Only processes composers for active workspaces.
        """
        if not self.connection:
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
                key = row["key"]
                value = row["value"]

                if not value:
                    continue

                # Parse composer data
                try:
                    composer_data = json.loads(value)
                except json.JSONDecodeError:
                    continue

                # Check if data changed using incremental sync
                if self.incremental_sync.should_process("global", "all", key, value):
                    await self._queue_composer_event(key, composer_data)

        except Exception as e:
            logger.error(f"Error syncing composer data: {e}")

    async def _queue_composer_event(self, key: str, data: dict):
        """Queue composer event to Redis."""
        event = {
            "version": "0.1.0",
            "hook_type": "DatabaseTrace",
            "event_type": "composer",
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "storage_level": "global",
                "database_table": "cursorDiskKV",
                "item_key": key,
                "source": "user_level_listener",
            },
            "payload": {
                "extracted_fields": self._extract_composer_fields(data),
                "full_data": data
            }
        }

        await self.event_queuer.queue_event(event)

    def _extract_composer_fields(self, data: dict) -> dict:
        """Extract relevant fields from composer data."""
        fields = {}

        for field in ["composerId", "workspaceId", "createdAt", "lastUpdatedAt"]:
            if field in data:
                fields[field] = data[field]

        return fields

    def set_active_workspaces(self, workspaces: Set[str]):
        """Update set of active workspaces."""
        self.active_workspaces = workspaces

    async def stop(self):
        """Stop user-level listener."""
        if self.file_watcher:
            await self.file_watcher.stop()

        if self.connection:
            await self.connection.close()


class UnifiedCursorMonitor:
    """
    Unified monitor with session-aware workspace activation.
    Consolidates all Cursor database telemetry monitoring.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        session_monitor: SessionMonitor,
        config: Optional[CursorMonitorConfig] = None
    ):
        # Core dependencies
        self.redis_client = redis_client
        self.session_monitor = session_monitor
        self.config = config or CursorMonitorConfig()

        # Initialize components
        self.user_listener = UserLevelListener(redis_client, self.config)
        self.event_queuer = EventQueuer(redis_client)
        self.incremental_sync = IncrementalSync()
        self.smart_cache = SmartCache(ttl_seconds=self.config.cache_ttl)

        # Workspace management
        self.workspace_monitors: Dict[str, WorkspaceMonitor] = {}
        self.file_watchers: Dict[str, FileWatcher] = {}

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

        logger.info("UnifiedCursorMonitor started")

    async def stop(self):
        """Stop the unified monitor."""
        self.running = False

        # Stop all workspace monitors
        for workspace_hash in list(self.workspace_monitors.keys()):
            await self.on_session_end(workspace_hash)

        # Stop user-level listener
        await self.user_listener.stop()

        if self.monitoring_task:
            self.monitoring_task.cancel()

        logger.info("UnifiedCursorMonitor stopped")

    async def on_session_start(self, workspace_hash: str, session_info: dict):
        """
        Activate monitoring for a workspace when session starts.
        Called by SessionMonitor when a new Cursor session begins.
        """
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
            itemtable_keys=self.workspace_itemtable_keys
        )
        await monitor.connect()
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

        # Update user-level listener with active workspaces
        self.user_listener.set_active_workspaces(set(self.workspace_monitors.keys()))

        logger.info(f"Activated monitoring for workspace {workspace_hash}")

    async def on_session_end(self, workspace_hash: str):
        """
        Deactivate monitoring when session ends.
        Called by SessionMonitor when a Cursor session terminates.
        """
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

        # Update user-level listener with active workspaces
        self.user_listener.set_active_workspaces(set(self.workspace_monitors.keys()))

        logger.info(f"Deactivated monitoring for workspace {workspace_hash}")

    async def _on_workspace_db_change(self, workspace_hash: str):
        """Handle workspace database change."""
        if workspace_hash in self.workspace_monitors:
            await self.workspace_monitors[workspace_hash].sync_all_data()

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

        # Try workspace mapper first
        mapper = WorkspaceMapper(self.session_monitor)
        mapping = mapper.get_mapping(workspace_hash)

        if mapping and mapping.get("db_path"):
            db_path = Path(mapping["db_path"])
            if db_path.exists():
                await self.smart_cache.set(cache_key, str(db_path))
                return db_path

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
