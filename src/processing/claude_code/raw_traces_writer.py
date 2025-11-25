# Copyright © 2025 Sierra Labs LLC
# SPDX-License-Identifier: AGPL-3.0-only
# License-Filename: LICENSE

"""
Claude Code Raw Traces Writer.

Handles batch writes to claude_raw_traces table with field extraction,
zlib compression, and performance optimization.
"""

import json
import logging
from typing import Dict, List, Any
from datetime import datetime

from ..database.sqlite_client import SQLiteClient
from ..database.writer import SQLiteBatchWriter

logger = logging.getLogger(__name__)

# Prepared INSERT/UPSERT statement for claude_raw_traces
# Uses ON CONFLICT to merge duplicate events (based on external_id, uuid):
# - Preserves original sequence (AUTOINCREMENT) and ingested_at on updates
# - Updates all other fields with new values
INSERT_QUERY = """
INSERT INTO claude_raw_traces (
    event_id, external_id, event_type, platform, timestamp,
    uuid, parent_uuid, request_id, agent_id,
    workspace_hash, project_name, is_sidechain, user_type, cwd, version, git_branch,
    message_role, message_model, message_id, message_type, stop_reason, stop_sequence,
    input_tokens, cache_creation_input_tokens, cache_read_input_tokens, output_tokens,
    service_tier, cache_5m_tokens, cache_1h_tokens,
    operation, subtype, level, is_meta,
    summary, leaf_uuid,
    duration_ms, tokens_used, tool_calls_count,
    event_data
) VALUES (
    ?, ?, ?, ?, ?,
    ?, ?, ?, ?,
    ?, ?, ?, ?, ?, ?, ?,
    ?, ?, ?, ?, ?, ?,
    ?, ?, ?, ?,
    ?, ?, ?,
    ?, ?, ?, ?,
    ?, ?,
    ?, ?, ?,
    ?
)
ON CONFLICT(external_id, uuid) DO UPDATE SET
    event_id = excluded.event_id,
    event_type = excluded.event_type,
    platform = excluded.platform,
    timestamp = excluded.timestamp,
    parent_uuid = excluded.parent_uuid,
    request_id = excluded.request_id,
    agent_id = excluded.agent_id,
    workspace_hash = excluded.workspace_hash,
    project_name = excluded.project_name,
    is_sidechain = excluded.is_sidechain,
    user_type = excluded.user_type,
    cwd = excluded.cwd,
    version = excluded.version,
    git_branch = excluded.git_branch,
    message_role = excluded.message_role,
    message_model = excluded.message_model,
    message_id = excluded.message_id,
    message_type = excluded.message_type,
    stop_reason = excluded.stop_reason,
    stop_sequence = excluded.stop_sequence,
    input_tokens = excluded.input_tokens,
    cache_creation_input_tokens = excluded.cache_creation_input_tokens,
    cache_read_input_tokens = excluded.cache_read_input_tokens,
    output_tokens = excluded.output_tokens,
    service_tier = excluded.service_tier,
    cache_5m_tokens = excluded.cache_5m_tokens,
    cache_1h_tokens = excluded.cache_1h_tokens,
    operation = excluded.operation,
    subtype = excluded.subtype,
    level = excluded.level,
    is_meta = excluded.is_meta,
    summary = excluded.summary,
    leaf_uuid = excluded.leaf_uuid,
    duration_ms = excluded.duration_ms,
    tokens_used = excluded.tokens_used,
    tool_calls_count = excluded.tool_calls_count,
    event_data = excluded.event_data
"""


class ClaudeRawTracesWriter:
    """
    Batch writer for Claude Code raw traces.

    Writes events to claude_raw_traces table with:
    - Field extraction from JSONL schema
    - zlib compression for event_data BLOB
    - Batch inserts with executemany() for performance
    - Zero reads - pure write path

    Target: <10ms P95 latency for 100 events.
    """

    def __init__(self, client: SQLiteClient):
        """
        Initialize Claude raw traces writer.

        Args:
            client: SQLiteClient instance
        """
        self.client = client
        self.batch_writer = SQLiteBatchWriter(client)

    def _extract_indexed_fields(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract indexed fields from Claude Code JSONL event.

        Maps JSONL schema fields to database columns for claude_raw_traces table.

        Args:
            event: Full event dictionary

        Returns:
            Dictionary with extracted fields
        """
        payload = event.get('payload', {})
        entry_data = payload.get('entry_data', {})
        metadata = event.get('metadata', {})

        # Extract message data (for user/assistant events)
        message = entry_data.get('message', {})
        usage = message.get('usage', {}) if isinstance(message, dict) else {}
        cache_creation = usage.get('cache_creation', {}) if isinstance(usage, dict) else {}

        # Calculate total tokens
        input_tokens = usage.get('input_tokens', 0)
        output_tokens = usage.get('output_tokens', 0)
        tokens_used = input_tokens + output_tokens if (input_tokens or output_tokens) else None

        # Count tool calls
        tool_calls_count = 0
        if isinstance(message, dict):
            content = message.get('content', [])
            if isinstance(content, list):
                tool_calls_count = sum(1 for item in content if isinstance(item, dict) and item.get('type') == 'tool_use')

        # Extract external_id from event top-level (set by jsonl_monitor)
        external_id = event.get('session_id', '')

        # Warn if external_id is still empty (shouldn't happen for valid events)
        if not external_id:
            logger.warning(
                f"Claude Code event missing external_id: event_id={entry_data.get('uuid', 'unknown')}, "
                f"event_type={entry_data.get('type', 'unknown')}"
            )

        return {
            'event_id': entry_data.get('uuid', ''),
            'external_id': external_id,
            'event_type': entry_data.get('type', ''),
            'platform': 'claude_code',
            'timestamp': entry_data.get('timestamp', event.get('timestamp', '')),

            # Claude Code specific
            'uuid': entry_data.get('uuid'),
            'parent_uuid': entry_data.get('parentUuid'),
            'request_id': entry_data.get('requestId'),
            'agent_id': entry_data.get('agentId'),

            # Context
            'workspace_hash': metadata.get('workspace_hash'),
            'project_name': metadata.get('project_name') or entry_data.get('projectName'),
            'is_sidechain': entry_data.get('isSidechain', False),
            'user_type': entry_data.get('userType'),
            'cwd': entry_data.get('cwd'),
            'version': entry_data.get('version'),
            'git_branch': entry_data.get('gitBranch'),

            # Message fields
            'message_role': message.get('role') if isinstance(message, dict) else None,
            'message_model': message.get('model') if isinstance(message, dict) else None,
            'message_id': message.get('id') if isinstance(message, dict) else None,
            'message_type': message.get('type') if isinstance(message, dict) else None,
            'stop_reason': message.get('stop_reason') if isinstance(message, dict) else None,
            'stop_sequence': message.get('stop_sequence') if isinstance(message, dict) else None,

            # Token usage
            'input_tokens': usage.get('input_tokens'),
            'cache_creation_input_tokens': usage.get('cache_creation_input_tokens'),
            'cache_read_input_tokens': usage.get('cache_read_input_tokens'),
            'output_tokens': usage.get('output_tokens'),
            'service_tier': usage.get('service_tier'),
            'cache_5m_tokens': cache_creation.get('ephemeral_5m_input_tokens'),
            'cache_1h_tokens': cache_creation.get('ephemeral_1h_input_tokens'),

            # Queue operation
            'operation': entry_data.get('operation'),

            # System event
            'subtype': entry_data.get('subtype'),
            'level': entry_data.get('level'),
            'is_meta': entry_data.get('isMeta', False),

            # Summary
            'summary': entry_data.get('summary'),
            'leaf_uuid': entry_data.get('leafUuid'),

            # Metrics
            'duration_ms': payload.get('duration_ms'),
            'tokens_used': tokens_used,
            'tool_calls_count': tool_calls_count if tool_calls_count > 0 else None,
        }

    def write_batch_sync(self, events: List[Dict[str, Any]]) -> List[int]:
        """
        Synchronous batch write/upsert for Claude Code events.

        Writes to claude_raw_traces table with Claude-specific fields.
        Uses INSERT ... ON CONFLICT to merge duplicate events:
        - Preserves original sequence and ingested_at on updates
        - Updates all other fields with new values

        Args:
            events: List of Claude Code event dictionaries

        Returns:
            List of sequence numbers for written events (note: for updated
            events, this returns the original sequence, not a new one)
        """
        if not events:
            return []

        # Prepare batch data
        rows = []
        uuids = []  # Track UUIDs for sequence lookup after upsert
        for event in events:
            # Extract indexed fields
            fields = self._extract_indexed_fields(event)

            # Compress full event
            compressed_data = self.batch_writer.compress_event(event)

            # Track UUID for later sequence lookup
            uuids.append((fields['external_id'], fields['uuid']))

            # Build row tuple (39 fields)
            row = (
                fields['event_id'],
                fields['external_id'],
                fields['event_type'],
                fields['platform'],
                fields['timestamp'],
                fields['uuid'],
                fields['parent_uuid'],
                fields['request_id'],
                fields['agent_id'],
                fields['workspace_hash'],
                fields['project_name'],
                fields['is_sidechain'],
                fields['user_type'],
                fields['cwd'],
                fields['version'],
                fields['git_branch'],
                fields['message_role'],
                fields['message_model'],
                fields['message_id'],
                fields['message_type'],
                fields['stop_reason'],
                fields['stop_sequence'],
                fields['input_tokens'],
                fields['cache_creation_input_tokens'],
                fields['cache_read_input_tokens'],
                fields['output_tokens'],
                fields['service_tier'],
                fields['cache_5m_tokens'],
                fields['cache_1h_tokens'],
                fields['operation'],
                fields['subtype'],
                fields['level'],
                fields['is_meta'],
                fields['summary'],
                fields['leaf_uuid'],
                fields['duration_ms'],
                fields['tokens_used'],
                fields['tool_calls_count'],
                compressed_data,
            )
            rows.append(row)

        # Batch insert/upsert
        try:
            with self.client.get_connection() as conn:
                # Insert/update batch
                conn.executemany(INSERT_QUERY, rows)

                # Query actual sequences for all upserted events
                # This handles both new inserts and updates correctly
                sequences = []
                for external_id, uuid_val in uuids:
                    cursor = conn.execute(
                        "SELECT sequence FROM claude_raw_traces WHERE external_id = ? AND uuid = ?",
                        (external_id, uuid_val)
                    )
                    result = cursor.fetchone()
                    if result:
                        sequences.append(result[0])

                # Commit
                conn.commit()

            if sequences:
                logger.debug(f"Wrote Claude Code batch of {len(events)} events, sequences: {sequences[0]}-{sequences[-1]}")
            else:
                logger.debug(f"Wrote Claude Code batch of {len(events)} events")

            return sequences

        except Exception as e:
            logger.error(f"Failed to write Claude Code batch: {e}", exc_info=True)
            raise
