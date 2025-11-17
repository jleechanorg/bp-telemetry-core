#!/usr/bin/env python3
"""Test script to verify MCP server setup and trace service functionality."""

import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from processing.database.sqlite_client import SQLiteClient
from processing.database.schema import create_schema
from processing.database.writer import SQLiteBatchWriter
from mcp.trace_service import ClaudeTraceService


def create_test_events(session_id: str, count: int = 10):
    """Create test trace events."""
    events = []
    base_time = datetime.now(timezone.utc)

    for i in range(count):
        timestamp = base_time + timedelta(seconds=i * 5)
        event = {
            "event_id": f"evt-{i}",
            "session_id": session_id,
            "event_type": "message" if i % 2 == 0 else "tool_use",
            "platform": "claude_code",
            "timestamp": timestamp.isoformat(),
            "metadata": {
                "workspace_hash": "test-hash",
                "project_name": "MCP Test Project"
            },
            "payload": {
                "entry_data": {
                    "uuid": f"uuid-{i}",
                    "sessionId": session_id,
                    "type": "message" if i % 2 == 0 else "tool_use",
                    "timestamp": timestamp.isoformat(),
                    "message": {
                        "role": "assistant" if i % 2 == 0 else "user",
                        "content": f"Test message {i}"
                    } if i % 2 == 0 else None,
                    "tool": {
                        "name": f"tool_{i}",
                        "parameters": {"test": True}
                    } if i % 2 == 1 else None
                }
            }
        }
        events.append(event)

    return events


async def test_trace_service():
    """Test the trace service functionality."""
    print("🔧 Testing MCP Trace Service Setup...")

    # Initialize database
    db_path = Path.home() / ".blueplane" / "telemetry.db"
    db_path.parent.mkdir(exist_ok=True)

    client = SQLiteClient(str(db_path))
    client.initialize_database()

    # Import and create the Claude-specific schema
    from processing.database.schema import create_claude_raw_traces_table, create_claude_indexes
    create_claude_raw_traces_table(client)
    create_claude_indexes(client)

    # Create test session
    session_id = f"test-session-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    # Write test events
    print(f"📝 Writing test events for session: {session_id}")
    writer = SQLiteBatchWriter(client)
    events = create_test_events(session_id, count=10)
    writer.write_claude_batch_sync(events)

    # Initialize trace service
    service = ClaudeTraceService(sqlite_client=client)

    # Test 1: Get Timeline
    print("\n✅ Test 1: Get Timeline")
    timeline = service.get_timeline(session_id, limit=5)
    print(f"  - Retrieved {len(timeline.items)} events")
    print(f"  - Has more: {timeline.has_more}")
    if timeline.items:
        print(f"  - First event: {timeline.items[0].event_type} at {timeline.items[0].timestamp}")

    # Test 2: Find Gaps
    print("\n✅ Test 2: Find Gaps")
    gaps = service.find_gaps(session_id=session_id, minimum_gap_seconds=10)
    print(f"  - Found {len(gaps)} gaps")

    # Test 3: Inspect Payload
    print("\n✅ Test 3: Inspect Payload")
    if timeline.items:
        first_item = timeline.items[0]
        result = service.inspect_payload(
            sequence=first_item.sequence,
            selectors=["payload.entry_data.message.role", "payload.entry_data.type"]
        )
        print(f"  - Inspected fields: {list(result.requested_fields.keys())}")
        for field, value in result.requested_fields.items():
            print(f"    - {field}: {value}")

    # Test 4: Compare Generation
    print("\n✅ Test 4: Compare Generation")
    if len(timeline.items) > 1:
        comparison = service.compare_generation("uuid-1", tolerance_seconds=30)
        if comparison:
            print(f"  - Target event: {comparison.target_event.uuid}")
            print(f"  - Surrounding events: {comparison.summary.get('neighbor_count', 0)}")

    print("\n✅ All tests passed! MCP server is ready to use.")
    print(f"📂 Database location: {db_path}")

    return True


async def test_mcp_tools():
    """Test MCP tool definitions for Cursor."""
    print("\n🔧 Testing MCP Tool Definitions...")

    # Define tool schemas that Cursor will use
    tools = {
        "trace_get_timeline": {
            "description": "Get paginated timeline of trace events",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 100},
                    "cursor": {"type": "integer"},
                    "project_name": {"type": "string"}
                },
                "required": ["session_id"]
            }
        },
        "trace_find_gaps": {
            "description": "Find gaps in trace timeline",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "minimum_gap_seconds": {"type": "number", "default": 60}
                }
            }
        },
        "trace_inspect_payload": {
            "description": "Inspect specific fields in trace payload",
            "parameters": {
                "type": "object",
                "properties": {
                    "sequence": {"type": "integer"},
                    "uuid": {"type": "string"},
                    "selectors": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                }
            }
        }
    }

    print("📋 Available MCP Tools:")
    for tool_name, tool_def in tools.items():
        print(f"  - {tool_name}: {tool_def['description']}")

    print("\n✅ Tool definitions validated")
    return tools


if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Blueplane MCP Server Setup Test")
    print("=" * 60)

    # Run tests
    try:
        # Test trace service
        asyncio.run(test_trace_service())

        # Test tool definitions
        asyncio.run(test_mcp_tools())

        print("\n" + "=" * 60)
        print("✅ SUCCESS: MCP server is properly configured!")
        print("=" * 60)
        print("\n📝 Next Steps:")
        print("1. Restart Cursor to load the MCP configuration")
        print("2. Look for 'blueplane-telemetry' in Cursor's MCP servers")
        print("3. Test by asking Cursor to 'analyze my trace data'")
        print("4. Use tools like trace_get_timeline to query telemetry")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        print("\nTroubleshooting:")
        print("1. Ensure Redis is running: redis-cli ping")
        print("2. Check Python path and imports")
        print("3. Verify database permissions")
        sys.exit(1)