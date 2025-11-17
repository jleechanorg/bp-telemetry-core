# Cursor MCP Integration - Final Setup

## ✅ Working Configuration

The MCP server for Blueplane Telemetry is now configured and ready for Cursor.

### Configuration File: `.cursor/mcp.json`

```json
{
  "mcpServers": {
    "blueplane-telemetry": {
      "command": "python3",
      "args": ["${workspaceFolder}/src/mcp/mcp_server.py"],
      "env": {
        "PYTHONPATH": "${workspaceFolder}/src:${workspaceFolder}",
        "BLUEPLANE_DB_PATH": "${userHome}/.blueplane/telemetry.db"
      }
    }
  }
}
```

### Server Location
- **File**: `src/mcp/mcp_server.py`
- **Database**: `~/.blueplane/telemetry.db`

### Available MCP Tools

1. **trace_get_timeline**
   - Get paginated timeline of trace events
   - Parameters: session_id, limit, cursor, project_name, start, end, event_types

2. **trace_find_gaps**
   - Find gaps in trace timeline
   - Parameters: session_id, project_name, minimum_gap_seconds, since

3. **trace_inspect_payload**
   - Inspect specific fields in trace payload
   - Parameters: sequence, uuid, selectors

4. **trace_compare_generation**
   - Compare a generation UUID against surrounding events
   - Parameters: generation_id, tolerance_seconds

## How to Use in Cursor

### 1. Restart Cursor
After adding the `.cursor/mcp.json` configuration, restart Cursor to load the MCP server.

### 2. Check MCP Panel
Look for "blueplane-telemetry" in Cursor's MCP panel or server list.

### 3. Use Natural Language
Ask Cursor questions like:
- "Show me the trace timeline for session test-session-20251117-013433"
- "Find any gaps in my traces"
- "What events happened in my last coding session?"
- "Analyze the tool usage patterns in my traces"

### 4. Direct Tool Calls (if supported)
```
@blueplane-telemetry trace_get_timeline session_id="test-session-20251117-013433"
```

## Test Data Available

Multiple test sessions in database:
- **Latest**: `test-session-20251117-015337` (20 events)
- **Previous**: `test-session-20251117-015144` (10 events)
- **More**: Several other test sessions available

All sessions contain a mix of message and tool_use events ready for testing.

## Troubleshooting

### If MCP server doesn't start:
1. Check Python path: `which python3`
2. Verify database exists: `ls ~/.blueplane/telemetry.db`
3. Check Cursor logs: View → Output → MCP

### If tools aren't working:
1. Ensure the server is running (check Cursor's MCP panel)
2. Try restarting Cursor
3. Test with the test session ID above

## Implementation Details

- **MCP SDK**: Using `FastMCP` from the `mcp` package
- **Protocol**: JSON-RPC over stdio
- **Database**: SQLite with claude_raw_traces table
- **Compression**: zlib for event data storage

## Next Steps

1. **Test in Cursor**: Restart and test the tools
2. **Add more tools**: Extend with metrics, analysis, optimization tools
3. **Monitor usage**: Track how the tools are being used
4. **Iterate**: Improve based on usage patterns