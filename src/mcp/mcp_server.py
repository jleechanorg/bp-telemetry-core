#!/usr/bin/env python3
"""
MCP Server for Blueplane Telemetry.

This server implements the Model Context Protocol (MCP) to expose
telemetry trace analysis tools to Cursor and other MCP-compatible IDEs.
"""

import sys
import json
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

# Add src to path first (PYTHONPATH should already have it, but ensure it's there)
src_path = Path(__file__).resolve().parent.parent
project_root = src_path.parent
src_path_str = str(src_path)
project_root_str = str(project_root)
if src_path_str not in sys.path:
    sys.path.insert(0, src_path_str)
if project_root_str not in sys.path:
    sys.path.insert(0, project_root_str)

# Import local trace_service and store it
from mcp.trace_service import ClaudeTraceService

# Clear mcp from modules cache so we can import mcp.server from site-packages
# Save trace_service first
trace_service_module = sys.modules['mcp.trace_service']
ClaudeTraceService = trace_service_module.ClaudeTraceService

# Remove mcp from cache so Python will look for mcp.server in site-packages
if 'mcp' in sys.modules:
    del sys.modules['mcp']
if 'mcp.trace_service' in sys.modules:
    del sys.modules['mcp.trace_service']

# Temporarily remove src from path so Python finds mcp.server in site-packages
original_path = sys.path.copy()
sys.path = [p for p in sys.path if p != src_path_str and p != project_root_str]

# Import from site-packages
from mcp.server import FastMCP
from mcp.server.stdio import stdio_server

# Restore path and re-register trace_service in mcp namespace
sys.path = original_path
# Re-add trace_service to mcp namespace
sys.modules['mcp.trace_service'] = trace_service_module
if 'mcp' not in sys.modules:
    # Create a minimal mcp module if it doesn't exist
    import types
    mcp_module = types.ModuleType('mcp')
    sys.modules['mcp'] = mcp_module
sys.modules['mcp'].trace_service = trace_service_module

from pydantic import BaseModel, Field

from processing.database.sqlite_client import SQLiteClient


class TraceTimelineParams(BaseModel):
    """Parameters for trace_get_timeline tool."""
    session_id: str = Field(..., description="Session ID to query")
    limit: int = Field(100, description="Maximum number of events to return")
    cursor: Optional[int] = Field(None, description="Cursor for pagination")
    project_name: Optional[str] = Field(None, description="Filter by project name")
    start: Optional[str] = Field(None, description="Start timestamp (ISO format)")
    end: Optional[str] = Field(None, description="End timestamp (ISO format)")
    event_types: Optional[List[str]] = Field(None, description="Filter by event types")


class TraceFindGapsParams(BaseModel):
    """Parameters for trace_find_gaps tool."""
    session_id: Optional[str] = Field(None, description="Session ID to query")
    project_name: Optional[str] = Field(None, description="Project name to filter by")
    minimum_gap_seconds: float = Field(60.0, description="Minimum gap duration in seconds")
    since: Optional[str] = Field(None, description="Start time (ISO format)")


class TraceInspectPayloadParams(BaseModel):
    """Parameters for trace_inspect_payload tool."""
    sequence: Optional[int] = Field(None, description="Sequence number of the event")
    uuid: Optional[str] = Field(None, description="UUID of the event")
    selectors: List[str] = Field(..., description="Field selectors (e.g., 'payload.entry_data.message.role')")


class TraceCompareGenerationParams(BaseModel):
    """Parameters for trace_compare_generation tool."""
    generation_id: str = Field(..., description="Generation UUID to compare")
    tolerance_seconds: float = Field(10.0, description="Time window in seconds")


class BlueplanceMCPServer:
    """MCP Server for Blueplane telemetry analysis."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize the MCP server with database connection."""
        # Use provided path or default to ~/.blueplane/telemetry.db
        if not db_path:
            db_path = str(Path.home() / ".blueplane" / "telemetry.db")

        # Initialize database client
        self.sqlite_client = SQLiteClient(db_path)
        self.sqlite_client.initialize_database()

        # Initialize trace service
        self.trace_service = ClaudeTraceService(sqlite_client=self.sqlite_client)

        # Create MCP server
        self.server = FastMCP("blueplane-telemetry")

        # Register tools
        self._register_tools()

    def _register_tools(self):
        """Register all MCP tools."""

        @self.server.tool()
        async def trace_get_timeline(
            session_id: str,
            limit: int = 100,
            cursor: Optional[int] = None,
            project_name: Optional[str] = None,
            start: Optional[str] = None,
            end: Optional[str] = None,
            event_types: Optional[List[str]] = None
        ) -> Dict[str, Any]:
            """Get paginated timeline of trace events for a session."""
            try:
                # Parse timestamps if provided
                start_dt = datetime.fromisoformat(start) if start else None
                end_dt = datetime.fromisoformat(end) if end else None

                # Call trace service
                result = self.trace_service.get_timeline(
                    session_id=session_id,
                    limit=limit,
                    cursor=cursor,
                    start=start_dt,
                    end=end_dt,
                    project_name=project_name,
                    event_types=event_types
                )

                # Convert to dict for JSON serialization
                return {
                    "items": [
                        {
                            "sequence": item.sequence,
                            "timestamp": item.timestamp,  # Already a string
                            "event_type": item.event_type,
                            "uuid": item.uuid,
                            "parent_uuid": item.parent_uuid,
                            "request_id": item.request_id,
                            "project_name": item.project_name,
                            "workspace_hash": item.workspace_hash,
                            "duration_ms": item.duration_ms,
                            "tokens_used": item.tokens_used,
                            "tool_calls_count": item.tool_calls_count,
                        }
                        for item in result.items
                    ],
                    "has_more": result.has_more,
                    "next_cursor": result.next_cursor
                }
            except Exception as e:
                return {"error": str(e)}

        @self.server.tool()
        async def trace_find_gaps(arguments: TraceFindGapsParams) -> Dict[str, Any]:
            """Find gaps in trace timeline where events stop arriving."""
            try:
                # Parse timestamp if provided
                since_dt = datetime.fromisoformat(arguments.since) if arguments.since else None

                # Call trace service
                gaps = self.trace_service.find_gaps(
                    session_id=arguments.session_id,
                    project_name=arguments.project_name,
                    minimum_gap_seconds=arguments.minimum_gap_seconds,
                    since=since_dt
                )

                # Convert to dict for JSON serialization
                return {
                    "gaps": [
                        {
                            "start_sequence": gap.start_sequence,
                            "end_sequence": gap.end_sequence,
                            "start_timestamp": gap.start_timestamp,  # Already a string
                            "end_timestamp": gap.end_timestamp,  # Already a string
                            "gap_seconds": gap.gap_seconds,
                            "session_id": gap.session_id,
                            "project_name": gap.project_name
                        }
                        for gap in gaps
                    ]
                }
            except Exception as e:
                return {"error": str(e)}

        @self.server.tool()
        async def trace_inspect_payload(
            selectors: List[str],
            sequence: Optional[int] = None,
            uuid: Optional[str] = None
        ) -> Dict[str, Any]:
            """Inspect specific fields in a trace payload using selector syntax."""
            try:
                if not sequence and not uuid:
                    return {"error": "Either sequence or uuid must be provided"}

                # Call trace service
                result = self.trace_service.inspect_payload(
                    sequence=sequence,
                    uuid=uuid,
                    selectors=selectors
                )

                # Convert to dict for JSON serialization
                return {
                    "sequence": result.sequence,
                    "uuid": result.uuid,
                    "requested_fields": result.requested_fields,
                    "raw_event": result.raw_event
                }
            except Exception as e:
                return {"error": str(e)}

        @self.server.tool()
        async def trace_compare_generation(arguments: TraceCompareGenerationParams) -> Dict[str, Any]:
            """Compare a generation UUID against surrounding events."""
            try:
                # Call trace service
                comparison = self.trace_service.compare_generation(
                    generation_id=arguments.generation_id,
                    tolerance_seconds=arguments.tolerance_seconds
                )

                if not comparison:
                    return {"error": f"Generation {arguments.generation_id} not found"}

                # Convert to dict for JSON serialization
                return {
                    "target_event": {
                        "sequence": comparison.target_event.sequence,
                        "timestamp": comparison.target_event.timestamp,  # Already a string
                        "event_type": comparison.target_event.event_type,
                        "uuid": comparison.target_event.uuid,
                    },
                    "surrounding_events": [
                        {
                            "sequence": item.sequence,
                            "timestamp": item.timestamp,  # Already a string
                            "event_type": item.event_type,
                            "uuid": item.uuid,
                        }
                        for item in comparison.surrounding_events
                    ],
                    "summary": comparison.summary
                }
            except Exception as e:
                return {"error": str(e)}

    async def run(self):
        """Run the MCP server."""
        # FastMCP has a simpler run method
        await self.server.run()


def main():
    """Main entry point."""
    import os

    # Get database path from environment or use default
    db_path = os.environ.get("BLUEPLANE_DB_PATH")

    # Create and run server
    server = BlueplanceMCPServer(db_path=db_path)
    # FastMCP handles its own async loop
    server.server.run()


if __name__ == "__main__":
    main()