# Copyright © 2025 Sierra Labs LLC
# SPDX-License-Identifier: AGPL-3.0-only
# License-Filename: LICENSE

"""
Event queuer and writer for cursor_raw_traces.

EventQueuer: Queues events to Redis Streams with at-least-once delivery
CursorRawTracesWriter: Consumes from Redis and writes to cursor_raw_traces table
"""

import asyncio
import json
import logging
import time
import zlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import aiosqlite
import redis

from ..database.sqlite_client import SQLiteClient

logger = logging.getLogger(__name__)


class EventQueuer:
    """
    Queues all Cursor events to Redis stream for processing.
    Ensures all telemetry flows through the message queue with at-least-once delivery.
    """

    def __init__(self, redis_client: redis.Redis):
        self.redis_client = redis_client
        self.stream_name = "telemetry:events"
        self.max_stream_length = 10000
        self.consumer_group = "processors"

        # Ensure consumer group exists
        self._ensure_consumer_group()

    def _ensure_consumer_group(self):
        """Create consumer group if it doesn't exist."""
        try:
            self.redis_client.xgroup_create(
                self.stream_name,
                self.consumer_group,
                id='0',
                mkstream=True
            )
            logger.info(f"Created consumer group '{self.consumer_group}'")
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                pass  # Group already exists
            else:
                raise

    async def queue_event(self, event: dict) -> Optional[str]:
        """
        Queue single event to Redis stream.
        Returns the stream entry ID on success.
        """
        try:
            # Serialize nested structures
            serialized = self._serialize_event(event)

            # Add to stream with automatic ID
            entry_id = self.redis_client.xadd(
                self.stream_name,
                serialized,
                maxlen=self.max_stream_length,
                approximate=True
            )

            logger.debug(f"Queued event {event.get('event_id')} as stream entry {entry_id}")
            return entry_id

        except Exception as e:
            logger.error(f"Failed to queue event: {e}")
            await self._buffer_locally(event)
            return None

    async def queue_events_batch(self, events: List[dict]) -> List[str]:
        """
        Queue multiple events efficiently.
        Returns list of stream entry IDs.
        """
        if not events:
            return []

        pipeline = self.redis_client.pipeline()
        entry_ids = []

        for event in events:
            serialized = self._serialize_event(event)
            pipeline.xadd(
                self.stream_name,
                serialized,
                maxlen=self.max_stream_length,
                approximate=True
            )

        try:
            entry_ids = pipeline.execute()
            logger.debug(f"Queued batch of {len(events)} events")
            return entry_ids
        except Exception as e:
            logger.error(f"Failed to queue batch: {e}")
            # Fall back to individual queuing
            for event in events:
                entry_id = await self.queue_event(event)
                if entry_id:
                    entry_ids.append(entry_id)
            return entry_ids

    def _serialize_event(self, event: dict) -> dict:
        """Serialize event for Redis."""
        serialized = {}

        for key, value in event.items():
            if isinstance(value, (dict, list)):
                serialized[key] = json.dumps(value)
            elif isinstance(value, datetime):
                serialized[key] = value.isoformat()
            elif value is not None:
                serialized[key] = str(value)
            else:
                serialized[key] = ""

        return serialized

    async def _buffer_locally(self, event: dict):
        """Buffer events locally when Redis is unavailable."""
        buffer_path = Path.home() / ".blueplane" / "cursor_event_buffer.db"
        buffer_path.parent.mkdir(exist_ok=True)

        async with aiosqlite.connect(str(buffer_path)) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS buffered_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    event_data TEXT NOT NULL,
                    retry_count INTEGER DEFAULT 0
                )
            """)

            await conn.execute(
                "INSERT INTO buffered_events (event_data) VALUES (?)",
                (json.dumps(event),)
            )
            await conn.commit()

        logger.info("Buffered event locally due to Redis unavailability")


class CursorRawTracesWriter:
    """
    Writes Cursor telemetry events to cursor_raw_traces table.

    Features:
    - Consumes from Redis Streams with XACK
    - Batch writes for performance
    - zlib level 6 compression for event_data
    - Proper field extraction and mapping
    """

    def __init__(self, sqlite_client: SQLiteClient, batch_size: int = 100):
        self.sqlite_client = sqlite_client
        self.batch_size = batch_size
        self.pending_events = []

    async def write_event(self, event: dict):
        """
        Write a single event (buffered for batch processing).

        Args:
            event: Event dictionary with extracted fields and full_data
        """
        self.pending_events.append(event)

        if len(self.pending_events) >= self.batch_size:
            await self.flush()

    async def write_events_batch(self, events: List[dict]):
        """
        Write multiple events in a single batch.

        Args:
            events: List of event dictionaries
        """
        if not events:
            return

        try:
            # Prepare batch data
            batch_data = []
            for event in events:
                row = self._prepare_row(event)
                batch_data.append(row)

            # Execute batch insert
            with self.sqlite_client.get_connection() as conn:
                conn.executemany("""
                    INSERT INTO cursor_raw_traces (
                        event_id, external_session_id, event_type, timestamp,
                        storage_level, workspace_hash, database_table, item_key,
                        generation_uuid, generation_type, command_type,
                        composer_id, bubble_id, server_bubble_id, message_type, is_agentic,
                        text_description, raw_text, rich_text,
                        unix_ms, created_at, last_updated_at, completed_at,
                        client_start_time, client_end_time,
                        lines_added, lines_removed, token_count_up_until_here,
                        capabilities_ran, capability_statuses,
                        project_name, relevant_files, selections,
                        is_archived, has_unread_messages,
                        event_data
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?
                    )
                """, batch_data)
                conn.commit()

            logger.info(f"Wrote {len(batch_data)} events to cursor_raw_traces")

        except Exception as e:
            logger.error(f"Failed to write batch to cursor_raw_traces: {e}")
            raise

    async def flush(self):
        """Flush pending events to database."""
        if not self.pending_events:
            return

        events = self.pending_events
        self.pending_events = []

        await self.write_events_batch(events)

    def _prepare_row(self, event: dict) -> tuple:
        """
        Prepare database row from event dictionary.

        Args:
            event: Event dictionary

        Returns:
            Tuple of values for SQL insert
        """
        # Compress full event data
        full_data = event.get("full_data", event)
        event_data_json = json.dumps(full_data, default=str)
        event_data_compressed = zlib.compress(event_data_json.encode(), level=6)

        # Extract all fields
        return (
            event.get("event_id"),
            event.get("external_session_id"),
            event.get("event_type"),
            event.get("timestamp"),

            event.get("storage_level"),
            event.get("workspace_hash"),
            event.get("database_table"),
            event.get("item_key"),

            event.get("generation_uuid"),
            event.get("generation_type"),
            event.get("command_type"),

            event.get("composer_id"),
            event.get("bubble_id"),
            event.get("server_bubble_id"),
            event.get("message_type"),
            event.get("is_agentic"),

            event.get("text_description"),
            event.get("raw_text"),
            event.get("rich_text"),

            event.get("unix_ms"),
            event.get("created_at"),
            event.get("last_updated_at"),
            event.get("completed_at"),
            event.get("client_start_time"),
            event.get("client_end_time"),

            event.get("lines_added"),
            event.get("lines_removed"),
            event.get("token_count_up_until_here"),

            event.get("capabilities_ran"),
            event.get("capability_statuses"),

            event.get("project_name"),
            event.get("relevant_files"),
            event.get("selections"),

            event.get("is_archived"),
            event.get("has_unread_messages"),

            event_data_compressed,
        )
