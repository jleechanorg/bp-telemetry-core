# Copyright © 2025 Sierra Labs LLC
# SPDX-License-Identifier: AGPL-3.0-only
# License-Filename: LICENSE

"""
CursorRawTracesWriter - Fast path writer for cursor_raw_traces table.

Handles batch writes to the cursor_raw_traces table with:
- Field extraction from Cursor events
- zlib compression of full payload
- Batched inserts for performance
- Error handling with logging
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..database.sqlite_client import SQLiteClient
from ..database.writer import SQLiteBatchWriter

logger = logging.getLogger(__name__)


class CursorRawTracesWriter:
    """
    Fast path writer for cursor_raw_traces table.
    Extracts fields and writes compressed events in batches.
    """

    def __init__(self, sqlite_client: SQLiteClient):
        self.sqlite_client = sqlite_client
        self.batch_writer = SQLiteBatchWriter(sqlite_client)

    async def write_events(self, events: List[dict]) -> int:
        """
        Write events to cursor_raw_traces table.

        Args:
            events: List of event dictionaries

        Returns:
            Number of events written
        """
        if not events:
            return 0

        rows = []
        for event in events:
            try:
                row = self._extract_row(event)
                if row:
                    rows.append(row)
            except Exception as e:
                logger.error(f"Error extracting row from event: {e}")
                continue

        if not rows:
            return 0

        # Batch insert
        written = self._batch_insert(rows)
        logger.info(f"Wrote {written} events to cursor_raw_traces")
        return written

    def _extract_row(self, event: dict) -> Optional[tuple]:
        """
        Extract row data from event.

        Args:
            event: Event dictionary

        Returns:
            Tuple of values for INSERT statement
        """
        metadata = event.get("metadata", {})
        payload = event.get("payload", {})
        full_data = payload.get("full_data", {})
        extracted = payload.get("extracted_fields", {})

        # Generate event_id if not present
        event_id = event.get("event_id") or str(uuid.uuid4())

        # Parse timestamp
        timestamp_str = event.get("timestamp")
        if timestamp_str:
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except:
                timestamp = datetime.now(timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)

        # Extract fields
        external_session_id = self._extract_session_id(event, metadata, full_data)
        event_type = event.get("event_type", "unknown")

        # Source location
        storage_level = metadata.get("storage_level", "workspace")
        workspace_hash = metadata.get("workspace_hash", "")
        database_table = metadata.get("database_table", "ItemTable")
        item_key = metadata.get("item_key", "")

        # AI Service fields
        generation_uuid = self._safe_get(full_data, "generationUUID")
        generation_type = self._safe_get(full_data, "type")
        command_type = self._safe_get(full_data, "commandType")

        # Composer/Bubble fields
        composer_id = self._safe_get(full_data, "composerId") or self._safe_get(full_data, "id")
        bubble_id = self._safe_get(full_data, "bubbleId")
        server_bubble_id = self._safe_get(full_data, "serverBubbleId")
        message_type = self._safe_get(full_data, "messageType")
        is_agentic = self._safe_get_bool(full_data, "isAgentic")

        # Content fields
        text_description = self._safe_get(full_data, "textDescription")
        raw_text = self._safe_get(full_data, "text") or self._safe_get(full_data, "rawText")
        rich_text = self._safe_get_json(full_data, "richText")

        # Timing fields (milliseconds)
        unix_ms = self._safe_get_int(full_data, "unixMs")
        created_at = self._safe_get_int(full_data, "createdAt")
        last_updated_at = self._safe_get_int(full_data, "lastUpdatedAt")
        completed_at = self._safe_get_int(full_data, "completedAt")

        timing_info = full_data.get("timingInfo", {})
        client_start_time = self._safe_get_int(timing_info, "clientStartTime")
        client_end_time = self._safe_get_int(timing_info, "clientEndTime")

        # Metrics fields
        lines_added = self._safe_get_int(full_data, "linesAdded")
        lines_removed = self._safe_get_int(full_data, "linesRemoved")
        token_count = self._safe_get_int(full_data, "tokenCountUpUntilHere")

        # Capability/Tool fields
        capabilities_ran = self._safe_get_json(full_data, "capabilitiesRan")
        capability_statuses = self._safe_get_json(full_data, "capabilityStatuses")

        # Context fields
        project_name = self._extract_project_name(metadata, full_data)
        relevant_files = self._safe_get_json(full_data, "relevantFiles")
        selections = self._safe_get_json(full_data, "selections")

        # Status fields
        is_archived = self._safe_get_bool(full_data, "isArchived")
        has_unread_messages = self._safe_get_bool(full_data, "hasUnreadMessages")

        # Compress full event data
        event_data_compressed = self.batch_writer.compress_event(full_data)

        return (
            event_id,
            external_session_id,
            event_type,
            timestamp.isoformat(),
            storage_level,
            workspace_hash,
            database_table,
            item_key,
            generation_uuid,
            generation_type,
            command_type,
            composer_id,
            bubble_id,
            server_bubble_id,
            message_type,
            is_agentic,
            text_description,
            raw_text,
            rich_text,
            unix_ms,
            created_at,
            last_updated_at,
            completed_at,
            client_start_time,
            client_end_time,
            lines_added,
            lines_removed,
            token_count,
            capabilities_ran,
            capability_statuses,
            project_name,
            relevant_files,
            selections,
            is_archived,
            has_unread_messages,
            event_data_compressed,
        )

    def _batch_insert(self, rows: List[tuple]) -> int:
        """
        Batch insert/upsert rows into cursor_raw_traces.

        Uses INSERT ... ON CONFLICT to merge duplicate events:
        - Preserves original sequence (AUTOINCREMENT) and ingested_at on updates
        - Updates all other fields with new values

        Args:
            rows: List of row tuples

        Returns:
            Number of rows processed (inserted or updated)
        """
        sql = """
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
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(event_id) DO UPDATE SET
            external_session_id = excluded.external_session_id,
            event_type = excluded.event_type,
            timestamp = excluded.timestamp,
            storage_level = excluded.storage_level,
            workspace_hash = excluded.workspace_hash,
            database_table = excluded.database_table,
            item_key = excluded.item_key,
            generation_uuid = excluded.generation_uuid,
            generation_type = excluded.generation_type,
            command_type = excluded.command_type,
            composer_id = excluded.composer_id,
            bubble_id = excluded.bubble_id,
            server_bubble_id = excluded.server_bubble_id,
            message_type = excluded.message_type,
            is_agentic = excluded.is_agentic,
            text_description = excluded.text_description,
            raw_text = excluded.raw_text,
            rich_text = excluded.rich_text,
            unix_ms = excluded.unix_ms,
            created_at = excluded.created_at,
            last_updated_at = excluded.last_updated_at,
            completed_at = excluded.completed_at,
            client_start_time = excluded.client_start_time,
            client_end_time = excluded.client_end_time,
            lines_added = excluded.lines_added,
            lines_removed = excluded.lines_removed,
            token_count_up_until_here = excluded.token_count_up_until_here,
            capabilities_ran = excluded.capabilities_ran,
            capability_statuses = excluded.capability_statuses,
            project_name = excluded.project_name,
            relevant_files = excluded.relevant_files,
            selections = excluded.selections,
            is_archived = excluded.is_archived,
            has_unread_messages = excluded.has_unread_messages,
            event_data = excluded.event_data
        """

        try:
            with self.sqlite_client.get_connection() as conn:
                conn.executemany(sql, rows)
                conn.commit()
                return len(rows)
        except Exception as e:
            logger.error(f"Error batch inserting/updating cursor_raw_traces: {e}")
            return 0

    def _extract_session_id(self, event: dict, metadata: dict, data: dict) -> Optional[str]:
        """Extract session ID from various possible locations."""
        # Try metadata first
        session_id = metadata.get("external_session_id") or metadata.get("session_id")
        if session_id:
            return session_id

        # Try data
        session_id = data.get("sessionId") or data.get("session_id")
        if session_id:
            return session_id

        return None

    def _extract_project_name(self, metadata: dict, data: dict) -> Optional[str]:
        """Extract project name from various possible locations."""
        # Try metadata
        project_name = metadata.get("project_name") or metadata.get("workspace_name")
        if project_name:
            return project_name

        # Try data
        project_name = data.get("projectName") or data.get("workspaceName")
        if project_name:
            return project_name

        return None

    def _safe_get(self, d: dict, key: str) -> Optional[str]:
        """Safely get string value from dict."""
        value = d.get(key)
        if value is None:
            return None
        return str(value) if not isinstance(value, str) else value

    def _safe_get_int(self, d: dict, key: str) -> Optional[int]:
        """Safely get int value from dict."""
        value = d.get(key)
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    def _safe_get_bool(self, d: dict, key: str) -> Optional[bool]:
        """Safely get bool value from dict."""
        value = d.get(key)
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        return bool(value)

    def _safe_get_json(self, d: dict, key: str) -> Optional[str]:
        """Safely get JSON string from dict."""
        value = d.get(key)
        if value is None:
            return None
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value)
        except (TypeError, ValueError):
            return None
