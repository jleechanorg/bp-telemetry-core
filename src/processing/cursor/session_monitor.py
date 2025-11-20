# Copyright © 2025 Sierra Labs LLC
# SPDX-License-Identifier: AGPL-3.0-only
# License-Filename: LICENSE

"""
Session Monitor for Cursor workspaces.

Listens to Redis session_start/end events from the extension.
Provides persistent session management with database-backed recovery.
"""

import asyncio
import json
import logging
import threading
from typing import Dict, Optional
import redis

from .session_persistence import (
    CursorSessionPersistence,
    SessionNotFoundError,
    DatabaseError
)
from ..database.sqlite_client import SQLiteClient

logger = logging.getLogger(__name__)


class SessionMonitor:
    """
    Monitor Cursor sessions via Redis events with database persistence.

    Design:
    - Redis stream events from extension (session_start/end)
    - Tracks active sessions with metadata (session_id, workspace_path)
    - Persists sessions to SQLite database for durability
    - Recovers incomplete sessions on startup
    """

    def __init__(self, redis_client: redis.Redis, sqlite_client: Optional[SQLiteClient] = None):
        """
        Initialize Cursor session monitor.

        Args:
            redis_client: Redis client for event streaming
            sqlite_client: Optional SQLite client for persistence (if None, persistence disabled)
        """
        self.redis_client = redis_client
        self.sqlite_client = sqlite_client

        # Active sessions: workspace_hash -> session_info (in-memory for fast lookups)
        self.active_sessions: Dict[str, dict] = {}
        self._lock = threading.Lock()

        # Track last processed Redis message ID (for resuming)
        self.last_redis_id = "0-0"

        # Session persistence (if sqlite_client provided)
        self.persistence: Optional[CursorSessionPersistence] = None
        if sqlite_client:
            self.persistence = CursorSessionPersistence(sqlite_client)

        self.running = False

    async def start(self):
        """
        Start monitoring sessions with recovery.
        
        Steps:
        1. Recover incomplete sessions from database (if persistence enabled)
        2. Catch up on historical Redis events
        3. Start listening to new Redis events
        """
        self.running = True

        # Step 1: Recover incomplete sessions from last run (if persistence enabled)
        if self.persistence:
            await self._recover_active_sessions()

        # Step 2: Process historical events first (catch up on existing sessions)
        await self._catch_up_historical_events()

        persistence_status = "with database persistence" if self.persistence else "(in-memory only)"
        logger.info(f"Cursor session monitor started {persistence_status}")

        # Step 3: Run Redis event listener directly (blocks until stopped)
        await self._listen_redis_events()

    async def _recover_active_sessions(self):
        """Recover active sessions from database."""
        if not self.persistence:
            return
        
        try:
            recovered = await self.persistence.recover_active_sessions()
            with self._lock:
                for external_session_id, session_info in recovered.items():
                    workspace_hash = session_info.get('workspace_hash')
                    if workspace_hash:
                        self.active_sessions[workspace_hash] = session_info
            logger.info(f"Recovered {len(recovered)} active Cursor sessions from database")
        except Exception as e:
            logger.error(f"Failed to recover active sessions: {e}", exc_info=True)

    async def _catch_up_historical_events(self):
        """Process all historical session_start events from Redis."""
        try:
            # Read all historical events
            messages = self.redis_client.xread(
                {"telemetry:events": "0-0"},
                count=1000,
                block=0  # Non-blocking
            )

            if messages:
                for stream, msgs in messages:
                    for msg_id, fields in msgs:
                        await self._process_redis_message(msg_id, fields)
                        self.last_redis_id = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)

                logger.info(f"Processed {len(msgs)} historical events")
        except Exception as e:
            logger.warning(f"Error catching up historical events: {e}")

    async def stop(self):
        """Stop monitoring."""
        self.running = False
        logger.info("Session monitor stopped")

    async def _listen_redis_events(self):
        """
        Listen to session_start/end events from Redis stream.

        Reads from telemetry:events stream, filters for session events.
        """
        try:
            while self.running:
                try:
                    # Read from stream (non-blocking, 1 second timeout)
                    messages = self.redis_client.xread(
                        {"telemetry:events": self.last_redis_id},
                        count=100,
                        block=1000  # 1 second block
                    )

                    if not messages:
                        await asyncio.sleep(0.1)
                        continue

                    # Process messages
                    for stream, msgs in messages:
                        for msg_id, fields in msgs:
                            await self._process_redis_message(msg_id, fields)
                            self.last_redis_id = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)

                except redis.ConnectionError:
                    logger.warning("Redis connection lost, retrying...")
                    await asyncio.sleep(5)
                except Exception as e:
                    logger.error(f"Error reading Redis events: {e}")
                    await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Redis event listener failed: {e}")

    async def _process_redis_message(self, msg_id, fields: dict):
        """Process a Redis message and update session state."""
        try:
            # Decode fields
            event_type = self._decode_field(fields, 'event_type')
            platform = self._decode_field(fields, 'platform')
            hook_type = self._decode_field(fields, 'hook_type')

            # Only process Cursor session events
            if platform != 'cursor':
                return

            # Only process session events
            if event_type not in ('session_start', 'session_end'):
                return

            # Parse payload
            payload_str = self._decode_field(fields, 'payload')
            if payload_str:
                payload = json.loads(payload_str)
            else:
                payload = {}

            # Parse metadata
            metadata_str = self._decode_field(fields, 'metadata')
            if metadata_str:
                metadata = json.loads(metadata_str)
            else:
                metadata = {}

            workspace_hash = metadata.get('workspace_hash') or payload.get('workspace_hash')
            session_id = payload.get('session_id') or metadata.get('session_id')
            workspace_path = payload.get('workspace_path', '')

            if not workspace_hash or not session_id:
                logger.debug(f"Incomplete session event: {msg_id}")
                return

            if event_type == 'session_start':
                # Extract workspace_name from metadata if available
                workspace_name = metadata.get('workspace_name') or payload.get('workspace_name') or ''
                
                # Persist to database (durable)
                internal_session_id = None
                if self.persistence:
                    try:
                        internal_session_id = await self.persistence.save_session_start(
                            external_session_id=session_id,
                            workspace_hash=workspace_hash,
                            workspace_path=workspace_path,
                            workspace_name=workspace_name,
                            metadata=metadata
                        )
                    except SessionNotFoundError:
                        # This shouldn't happen for session_start, but log it
                        logger.error(f"Session not found during start (unexpected): {session_id}")
                        # Continue with in-memory tracking
                    except DatabaseError as e:
                        logger.error(f"Database error persisting session start: {e}")
                        # Continue with in-memory tracking - system degrades gracefully
                    except Exception as e:
                        logger.error(f"Unexpected error persisting session start: {e}", exc_info=True)
                        # Continue with in-memory tracking
                
                # Add to in-memory dict (fast path)
                session_info = {
                    "session_id": session_id,  # External session ID (backwards compatibility)
                    "internal_session_id": internal_session_id,
                    "external_session_id": session_id,
                    "workspace_hash": workspace_hash,
                    "workspace_path": workspace_path,
                    "workspace_name": workspace_name,
                    "started_at": asyncio.get_event_loop().time(),
                    "source": "redis",
                }
                
                with self._lock:
                    self.active_sessions[workspace_hash] = session_info
                
                logger.info(f"Cursor session started: {workspace_hash} -> {session_id}")

            elif event_type == 'session_end':
                # Update database first (ensure durability)
                if self.persistence:
                    try:
                        await self.persistence.save_session_end(session_id, end_reason='normal')
                    except SessionNotFoundError as e:
                        logger.warning(f"Session not found during end: {e}")
                        # Continue with cleanup
                    except DatabaseError as e:
                        logger.error(f"Database error persisting session end: {e}")
                        # Continue with cleanup - system degrades gracefully
                    except Exception as e:
                        logger.error(f"Unexpected error persisting session end: {e}", exc_info=True)
                        # Continue with cleanup
                
                # Then remove from memory
                with self._lock:
                    removed = self.active_sessions.pop(workspace_hash, None)
                    if removed:
                        logger.info(f"Cursor session ended: {workspace_hash}")
                    else:
                        logger.debug(f"Session end for unknown workspace: {workspace_hash}")

        except Exception as e:
            logger.error(f"Error processing Redis message {msg_id}: {e}")

    def _decode_field(self, fields: dict, key: str) -> str:
        """Decode a field from Redis message."""
        # Handle both dict and list formats
        if isinstance(fields, dict):
            value = fields.get(key.encode() if isinstance(key, str) else key)
        else:
            # List format: [key1, val1, key2, val2, ...]
            try:
                idx = list(fields).index(key.encode() if isinstance(key, str) else key)
                value = fields[idx + 1] if idx + 1 < len(fields) else None
            except (ValueError, IndexError):
                value = None

        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode('utf-8')
        return str(value)

    def get_active_workspaces(self) -> Dict[str, dict]:
        """Get currently active workspaces."""
        with self._lock:
            return {
                workspace_hash: session.copy()
                for workspace_hash, session in self.active_sessions.items()
            }

    def get_workspace_path(self, workspace_hash: str) -> Optional[str]:
        """Get workspace path for hash."""
        with self._lock:
            session = self.active_sessions.get(workspace_hash)
            return session.get("workspace_path") if session else None

    def remove_session_by_workspace_hash(self, workspace_hash: str) -> bool:
        """
        Remove session from memory by workspace hash.
        
        Args:
            workspace_hash: Workspace hash identifier
            
        Returns:
            True if session was removed, False if not found
        """
        with self._lock:
            removed = self.active_sessions.pop(workspace_hash, None)
            return removed is not None

    def remove_session_by_external_id(self, external_session_id: str) -> bool:
        """
        Remove session from memory by external session ID.
        
        Args:
            external_session_id: External session ID from Cursor extension
            
        Returns:
            True if session was removed, False if not found
        """
        with self._lock:
            for workspace_hash, session_info in list(self.active_sessions.items()):
                if session_info.get('external_session_id') == external_session_id:
                    del self.active_sessions[workspace_hash]
                    return True
            return False



