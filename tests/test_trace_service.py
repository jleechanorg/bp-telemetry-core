from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

sys.path.insert(0, str(SRC_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from processing.database.sqlite_client import SQLiteClient
from processing.database.schema import create_schema
from processing.database.writer import SQLiteBatchWriter
from mcp.trace_service import ClaudeTraceService


def _build_event(
    session_id: str,
    uuid: str,
    timestamp: datetime,
    project_name: str = "Demo Project",
    workspace_hash: str = "hash123",
) -> dict:
    entry_timestamp = timestamp.isoformat()
    entry_data = {
        "uuid": uuid,
        "sessionId": session_id,
        "type": "message",
        "timestamp": entry_timestamp,
        "message": {
            "role": "assistant",
            "model": "claude-3",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 20,
            },
            "content": [
                {
                    "type": "text",
                    "text": "hello world",
                }
            ],
        },
    }
    return {
        "event_id": f"event-{uuid}",
        "session_id": session_id,
        "event_type": entry_data["type"],
        "platform": "claude_code",
        "timestamp": entry_timestamp,
        "metadata": {
            "workspace_hash": workspace_hash,
            "project_name": project_name,
        },
        "payload": {
            "entry_data": entry_data,
        },
    }


def _create_service_with_events(event_count: int = 4):
    tmpdir = TemporaryDirectory()
    db_path = Path(tmpdir.name) / "telemetry.db"
    client = SQLiteClient(str(db_path))
    client.initialize_database()
    create_schema(client)
    writer = SQLiteBatchWriter(client)

    base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
    events = []
    for idx in range(event_count):
        timestamp = base_time + timedelta(minutes=idx * 5)
        events.append(_build_event("sess-123", f"uuid-{idx}", timestamp))

    writer.write_claude_batch_sync(events)
    service = ClaudeTraceService(sqlite_client=client)
    return service, tmpdir


def test_get_timeline_paginates():
    service, tmpdir = _create_service_with_events()
    try:
        page = service.get_timeline("sess-123", limit=2)
        assert len(page.items) == 2
        assert page.has_more
        assert page.next_cursor is not None

        next_page = service.get_timeline("sess-123", cursor=page.next_cursor, limit=5)
        assert len(next_page.items) == 2
        assert not next_page.has_more
    finally:
        tmpdir.cleanup()


def test_compare_generation_returns_neighbors():
    service, tmpdir = _create_service_with_events()
    try:
        comparison = service.compare_generation("uuid-1", tolerance_seconds=600)
        assert comparison.target_event.uuid == "uuid-1"
        assert comparison.summary["neighbor_count"] >= 1
    finally:
        tmpdir.cleanup()


def test_find_gaps_detects_large_delta():
    service, tmpdir = _create_service_with_events(event_count=3)
    try:
        # Insert an additional event with a large time delta to trigger gap detection
        writer = SQLiteBatchWriter(service.client)
        late_event = _build_event(
            "sess-123",
            "uuid-gap",
            datetime(2025, 1, 1, 3, 0, tzinfo=timezone.utc),
        )
        writer.write_claude_batch_sync([late_event])

        gaps = service.find_gaps(session_id="sess-123", minimum_gap_seconds=1800)
        assert gaps, "Expected at least one detected gap"
        assert gaps[0].gap_seconds >= 1800
    finally:
        tmpdir.cleanup()


def test_inspect_payload_selector():
    service, tmpdir = _create_service_with_events()
    try:
        timeline = service.get_timeline("sess-123", limit=1)
        first = timeline.items[0]
        result = service.inspect_payload(sequence=first.sequence, selectors=["payload.entry_data.message.role"])
        assert result.requested_fields["payload.entry_data.message.role"] == "assistant"
    finally:
        tmpdir.cleanup()


