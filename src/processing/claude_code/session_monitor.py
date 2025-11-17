# Copyright © 2025 Sierra Labs LLC
# SPDX-License-Identifier: AGPL-3.0-only
# License-Filename: LICENSE

"""
Session Monitor for Claude Code sessions.

Listens to Redis session_start/end events from Claude Code hooks.
"""

import asyncio
import json
import logging
from typing import Dict, Optional
import redis

logger = logging.getLogger(__name__)


class ClaudeCodeSessionMonitor:
    """
    Monitor Claude Code sessions via Redis events.

    Design:
    - Redis stream events from OnSessionStart/OnSessionEnd hooks
    - Tracks active sessions with metadata (session_id, workspace_path)
    - Used by JSONL monitor to know which sessions to track
    """

    def __init__(self, redis_client: redis.Redis):
        self.redis_client = redis_client

        # Active sessions: session_id -> session_info
        self.active_sessions: Dict[str, dict] = {}

        # Track last processed Redis message ID (for resuming)
        self.last_redis_id = "0-0"

        self.running = False

    async def start(self):
        """Start monitoring sessions."""
        self.running = True

        # Process historical events first (catch up on existing sessions)
        await self._catch_up_historical_events()

        # Start Redis event listener
        asyncio.create_task(self._listen_redis_events())

        logger.info("Claude Code session monitor started (Redis events only)")

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

                logger.info(f"Processed {len(msgs)} historical Claude Code events")
        except Exception as e:
            logger.warning(f"Error catching up historical events: {e}")

    async def stop(self):
        """Stop monitoring."""
        self.running = False
        logger.info("Claude Code session monitor stopped")

    async def _listen_redis_events(self):
        """
        Listen to session_start/end events from Redis stream.

        Reads from telemetry:events stream, filters for Claude Code session events.
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

                except redis.exceptions.RedisError as e:
                    logger.error(f"Redis error in session monitor: {e}")
                    await asyncio.sleep(5)

        except Exception as e:
            logger.error(f"Fatal error in session monitor: {e}")

    async def _process_redis_message(self, msg_id, fields: dict):
        """
        Process a Redis stream message.

        Filters for session_start/session_end events from Claude Code.
        """
        # Decode fields
        event_type = self._decode_field(fields, 'event_type')
        platform = self._decode_field(fields, 'platform')

        # Only process Claude Code session events
        if platform != 'claude_code':
            return

        if event_type not in ('session_start', 'session_end'):
            return

        # Parse payload
        payload_str = self._decode_field(fields, 'payload')
        payload = json.loads(payload_str) if payload_str else {}

        metadata_str = self._decode_field(fields, 'metadata')
        metadata = json.loads(metadata_str) if metadata_str else {}

        session_id = payload.get('session_id') or self._decode_field(fields, 'session_id')
        workspace_hash = metadata.get('workspace_hash')
        workspace_path = payload.get('workspace_path', '')

        if event_type == 'session_start':
            self.active_sessions[session_id] = {
                "session_id": session_id,
                "workspace_hash": workspace_hash,
                "workspace_path": workspace_path,
                "platform": "claude_code",
                "started_at": asyncio.get_event_loop().time(),
                "source": "hooks",
            }
            logger.info(f"Claude Code session started: {session_id} (workspace: {workspace_path})")

        elif event_type == 'session_end':
            if session_id in self.active_sessions:
                del self.active_sessions[session_id]
                logger.info(f"Claude Code session ended: {session_id}")
            else:
                logger.debug(f"Session end for unknown session: {session_id}")

    def _decode_field(self, fields: dict, key: str) -> Optional[str]:
        """
        Decode a field from Redis stream message.

        Args:
            fields: Redis stream fields dictionary
            key: Field key to decode

        Returns:
            Decoded string value or None
        """
        value = fields.get(key) or fields.get(key.encode())
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode('utf-8')
        return str(value)

    def get_active_sessions(self) -> Dict[str, dict]:
        """
        Get all active Claude Code sessions.

        Returns:
            Dictionary of session_id -> session_info
        """
        return self.active_sessions.copy()

    def get_session_info(self, session_id: str) -> Optional[dict]:
        """
        Get info for a specific session.

        Args:
            session_id: Session ID to look up

        Returns:
            Session info dict or None
        """
        return self.active_sessions.get(session_id)
