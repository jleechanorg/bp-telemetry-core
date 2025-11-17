# Test MCP Commands for Cursor

## Quick Test Commands

After restarting Cursor with the MCP configuration, try these commands to test the integration:

### 1. Direct Tool Calls (if supported in your Cursor version)

```
@mcp trace_get_timeline session_id="test-session-20251117-013433" limit=5
```

```
@mcp trace_find_gaps session_id="test-session-20251117-013433" minimum_gap_seconds=10
```

```
@mcp trace_inspect_payload sequence=1 selectors=["payload.entry_data.message.role"]
```

### 2. Natural Language Queries

Ask Cursor these questions to test the MCP integration:

- "Show me the trace timeline for session test-session-20251117-013433"
- "Find any gaps in the test session traces"
- "What events are in the telemetry database?"
- "Analyze the message roles in the trace data"

### 3. Verify Database Content

You can also verify the database directly:

```bash
# Count events
sqlite3 ~/.blueplane/telemetry.db "SELECT COUNT(*) FROM claude_raw_traces;"

# List recent sessions
sqlite3 ~/.blueplane/telemetry.db "SELECT DISTINCT session_id, COUNT(*) as events FROM claude_raw_traces GROUP BY session_id;"

# Check event types
sqlite3 ~/.blueplane/telemetry.db "SELECT event_type, COUNT(*) FROM claude_raw_traces GROUP BY event_type;"
```

## Troubleshooting

If MCP tools aren't working:

1. **Check Cursor logs**: `~/.cursor/logs/`
2. **Verify Python path**: Make sure the Python interpreter can find the modules
3. **Test trace service directly**: Run `python3 test_mcp_setup.py` again
4. **Check Redis**: Ensure Redis is running with `redis-cli ping`

## Success Indicators

You know MCP is working when:
- Cursor recognizes the `blueplane-telemetry` server
- Tool calls return trace data
- Natural language queries about traces work
- No errors in Cursor logs