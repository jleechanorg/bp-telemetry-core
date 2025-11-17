"""Trace service powering MCP tooling for Claude Code telemetry."""

from __future__ import annotations

import json
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from processing.database.sqlite_client import SQLiteClient

DEFAULT_DB_PATH = Path.home() / ".blueplane" / "telemetry.db"


@dataclass
class TraceTimelineItem:
    """Single timeline entry for Claude traces."""

    sequence: int
    timestamp: str
    event_type: str
    uuid: Optional[str]
    parent_uuid: Optional[str]
    request_id: Optional[str]
    project_name: Optional[str]
    workspace_hash: Optional[str]
    duration_ms: Optional[int]
    tokens_used: Optional[int]
    tool_calls_count: Optional[int]
    raw_event: Dict[str, Any]


@dataclass
class TraceTimelinePage:
    """Paginated response for timeline queries."""

    items: List[TraceTimelineItem]
    has_more: bool
    next_cursor: Optional[int]


@dataclass
class TraceComparison:
    """Comparison payload for a generation UUID."""

    target_event: TraceTimelineItem
    surrounding_events: List[TraceTimelineItem]
    summary: Dict[str, Any]


@dataclass
class TraceGap:
    """Metadata describing a suspected trace gap."""

    start_sequence: int
    end_sequence: int
    gap_seconds: float
    start_timestamp: str
    end_timestamp: str
    session_id: str
    project_name: Optional[str]


@dataclass
class TraceInspectionResult:
    """Result payload for targeted payload inspection."""

    sequence: int
    uuid: Optional[str]
    requested_fields: Dict[str, Any]
    raw_event: Dict[str, Any]


class ClaudeTraceService:
    """High-level query helpers for Claude Code raw traces."""

    def __init__(
        self,
        sqlite_client: Optional[SQLiteClient] = None,
        db_path: Optional[Path] = None,
    ) -> None:
        self.client = sqlite_client or SQLiteClient(str(db_path or DEFAULT_DB_PATH))

    # ------------------------------------------------------------------
    # Timeline APIs (Phase 1)
    # ------------------------------------------------------------------
    def get_timeline(
        self,
        session_id: str,
        *,
        limit: int = 200,
        cursor: Optional[int] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        project_name: Optional[str] = None,
        event_types: Optional[Sequence[str]] = None,
    ) -> TraceTimelinePage:
        """Return ordered trace entries for a session."""

        if limit <= 0:
            raise ValueError("limit must be positive")

        clauses = ["session_id = ?"]
        params: List[Any] = [session_id]

        if project_name:
            clauses.append("project_name = ?")
            params.append(project_name)

        if cursor is not None:
            clauses.append("sequence > ?")
            params.append(cursor)

        if start:
            clauses.append("timestamp >= ?")
            params.append(start)

        if end:
            clauses.append("timestamp <= ?")
            params.append(end)

        if event_types:
            placeholders = ", ".join("?" for _ in event_types)
            clauses.append(f"event_type IN ({placeholders})")
            params.extend(event_types)

        where_sql = " AND ".join(clauses)
        query = f"""
            SELECT
                sequence, session_id, timestamp, event_type,
                uuid, parent_uuid, request_id,
                project_name, workspace_hash,
                duration_ms, tokens_used, tool_calls_count,
                event_data
            FROM claude_raw_traces
            WHERE {where_sql}
            ORDER BY timestamp ASC, sequence ASC
            LIMIT ?
        """
        params.append(min(limit, 1000) + 1)  # Fetch one extra record to signal pagination

        rows = self._fetch_rows(query, params)
        items = [self._build_timeline_item(row) for row in rows[:limit]]
        has_more = len(rows) > limit
        next_cursor = items[-1].sequence if has_more and items else None

        return TraceTimelinePage(items=items, has_more=has_more, next_cursor=next_cursor)

    def compare_generation(
        self,
        generation_id: str,
        *,
        tolerance_seconds: float = 10.0,
    ) -> TraceComparison:
        """Compare a generation UUID with surrounding events."""

        target_row = self._get_event_by_uuid(generation_id)
        if not target_row:
            raise ValueError(f"Generation {generation_id} not found.")

        target_item = self._build_timeline_item(target_row)
        target_ts = self._parse_timestamp(target_item.timestamp)

        window_start = (target_ts - timedelta(seconds=tolerance_seconds)).isoformat()
        window_end = (target_ts + timedelta(seconds=tolerance_seconds)).isoformat()

        neighbor_page = self.get_timeline(
            target_row["session_id"],
            start=window_start,
            end=window_end,
            limit=200,
            event_types=None,
        )
        neighbors = [item for item in neighbor_page.items if item.sequence != target_item.sequence]

        summary = {
            "uuid": generation_id,
            "session_id": target_row["session_id"],
            "project_name": target_item.project_name,
            "tokens_used": target_item.tokens_used,
            "duration_ms": target_item.duration_ms,
            "neighbor_count": len(neighbors),
        }

        return TraceComparison(
            target_event=target_item,
            surrounding_events=neighbors,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Advanced analytics (Phase 2)
    # ------------------------------------------------------------------
    def find_gaps(
        self,
        *,
        session_id: Optional[str] = None,
        project_name: Optional[str] = None,
        minimum_gap_seconds: float = 60.0,
        max_events: int = 2000,
        since: Optional[str] = None,
    ) -> List[TraceGap]:
        """Detect gaps between consecutive traces that exceed the threshold."""

        if not session_id and not project_name:
            raise ValueError("session_id or project_name is required to scope gap detection.")

        clauses = []
        params: List[Any] = []

        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)

        if project_name:
            clauses.append("project_name = ?")
            params.append(project_name)

        if since:
            clauses.append("timestamp >= ?")
            params.append(since)

        where_sql = " AND ".join(clauses) if clauses else "1=1"
        query = f"""
            SELECT sequence, session_id, timestamp, project_name
            FROM claude_raw_traces
            WHERE {where_sql}
            ORDER BY timestamp ASC, sequence ASC
            LIMIT ?
        """
        params.append(min(max_events, 5000))

        rows = self._fetch_rows(query, params)
        gaps: List[TraceGap] = []

        previous = None
        for row in rows:
            if previous is not None:
                delta = self._compute_gap_seconds(previous["timestamp"], row["timestamp"])
                if delta >= minimum_gap_seconds:
                    gaps.append(
                        TraceGap(
                            start_sequence=previous["sequence"],
                            end_sequence=row["sequence"],
                            gap_seconds=delta,
                            start_timestamp=previous["timestamp"],
                            end_timestamp=row["timestamp"],
                            session_id=row["session_id"],
                            project_name=row["project_name"],
                        )
                    )
            previous = row

        return gaps

    def inspect_payload(
        self,
        *,
        sequence: Optional[int] = None,
        uuid: Optional[str] = None,
        selectors: Optional[Sequence[str]] = None,
    ) -> TraceInspectionResult:
        """Inspect targeted payload fields with optional selectors."""

        if sequence is None and uuid is None:
            raise ValueError("sequence or uuid is required for inspection.")

        row = None
        if sequence is not None:
            row = self._get_event_by_sequence(sequence)
        if row is None and uuid is not None:
            row = self._get_event_by_uuid(uuid)

        if row is None:
            target = uuid if uuid is not None else sequence
            raise ValueError(f"Trace event {target} not found.")

        raw_event = self._decode_event_blob(row["event_data"])
        fields: Dict[str, Any] = {}

        if selectors:
            for selector in selectors:
                fields[selector] = self._extract_selector(raw_event, selector)
        else:
            fields["*"] = raw_event

        return TraceInspectionResult(
            sequence=row["sequence"],
            uuid=row["uuid"],
            requested_fields=fields,
            raw_event=raw_event,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _fetch_rows(self, query: str, params: Sequence[Any]) -> List[Any]:
        with self.client.get_connection() as conn:
            cursor = conn.execute(query, tuple(params))
            rows = cursor.fetchall()
        return rows

    def _decode_event_blob(self, blob: Any) -> Dict[str, Any]:
        data = zlib.decompress(bytes(blob))
        return json.loads(data.decode("utf-8"))

    def _build_timeline_item(self, row: Any) -> TraceTimelineItem:
        raw_event = self._decode_event_blob(row["event_data"])
        return TraceTimelineItem(
            sequence=row["sequence"],
            timestamp=row["timestamp"],
            event_type=row["event_type"],
            uuid=row["uuid"],
            parent_uuid=row["parent_uuid"],
            request_id=row["request_id"],
            project_name=row["project_name"],
            workspace_hash=row["workspace_hash"],
            duration_ms=row["duration_ms"],
            tokens_used=row["tokens_used"],
            tool_calls_count=row["tool_calls_count"],
            raw_event=raw_event,
        )

    def _get_event_by_uuid(self, uuid: str) -> Optional[Any]:
        query = """
            SELECT *
            FROM claude_raw_traces
            WHERE uuid = ?
            ORDER BY timestamp ASC
            LIMIT 1
        """
        rows = self._fetch_rows(query, [uuid])
        return rows[0] if rows else None

    def _get_event_by_sequence(self, sequence: int) -> Optional[Any]:
        query = """
            SELECT *
            FROM claude_raw_traces
            WHERE sequence = ?
            LIMIT 1
        """
        rows = self._fetch_rows(query, [sequence])
        return rows[0] if rows else None

    def _parse_timestamp(self, timestamp: str) -> datetime:
        try:
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")

    def _compute_gap_seconds(self, start_ts: str, end_ts: str) -> float:
        start = self._parse_timestamp(start_ts)
        end = self._parse_timestamp(end_ts)
        delta = end - start
        return delta.total_seconds()

    def _extract_selector(self, data: Any, selector: str) -> Any:
        """Extract value using dotted selector notation."""
        parts = [part for part in selector.split(".") if part]
        current: Any = data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    idx = int(part)
                except ValueError:
                    raise ValueError(f"List selector '{part}' is not an integer index")
                if idx >= len(current):
                    current = None
                else:
                    current = current[idx]
            else:
                return None
            if current is None:
                break
        return current


__all__ = [
    "ClaudeTraceService",
    "TraceTimelinePage",
    "TraceTimelineItem",
    "TraceComparison",
    "TraceGap",
    "TraceInspectionResult",
]


