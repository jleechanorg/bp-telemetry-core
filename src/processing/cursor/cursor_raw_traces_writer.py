# Copyright © 2025 Sierra Labs LLC
# SPDX-License-Identifier: AGPL-3.0-only
# License-Filename: LICENSE

"""
Writer for cursor_raw_traces table.

Handles batch writes with zlib compression for optimal performance.
"""

import json
import logging
import zlib
from typing import Dict, List

from ..database.sqlite_client import SQLiteClient

logger = logging.getLogger(__name__)


class CursorRawTracesWriter:
    """
    Writes Cursor telemetry events to cursor_raw_traces table.

    Features:
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
