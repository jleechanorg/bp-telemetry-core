# MCP Tool Call Format Debugging Results

## Summary

We successfully debugged the MCP tool call format for the `blueplane-telemetry` MCP server. Here are the key findings:

## ✅ Correct Format for FastMCP `call_tool()` Method

When calling FastMCP tools **directly** via the `call_tool()` method, the arguments must be wrapped in an `arguments` key:

```python
result = await server.server.call_tool(
    "trace_get_timeline",
    arguments={
        "arguments": {
            "session_id": "35559e21-c94c-4be2-ac73-905da9ebc449",
            "limit": 5
        }
    }
)
```

## Why This Format?

FastMCP automatically creates a wrapper Pydantic model for tool arguments. When you define a tool like:

```python
@self.server.tool()
async def trace_get_timeline(arguments: TraceTimelineParams) -> Dict[str, Any]:
    ...
```

FastMCP creates a wrapper model `trace_get_timelineArguments` that has this structure:

```json
{
  "properties": {
    "arguments": {
      "$ref": "#/$defs/TraceTimelineParams"
    }
  },
  "required": ["arguments"]
}
```

This means the `arguments` parameter name becomes a required field in the wrapper model.

## Bugs Fixed

1. **Import fix**: Changed `from trace_service import` to `from .trace_service import` in `mcp_server.py`
2. **Timestamp bug**: Removed `.isoformat()` calls on timestamps since `TraceTimelineItem.timestamp` is already a string, not a datetime object
3. **Same fix applied to**: `trace_find_gaps` and `trace_compare_generation` tools

## Testing Results

✅ **Format 2 (nested arguments)**: SUCCESS
- Validation passes
- Tool executes correctly
- Returns proper data structure

❌ **Format 1 (direct dict)**: FAILED
- Error: `Field required [type=missing, input_value={'session_id': '...'}]`
- FastMCP expects the `arguments` wrapper

## MCP Protocol Integration

When calling through Cursor's MCP tool interface, the arguments might be handled differently. The MCP protocol layer may:
- Automatically wrap/unwrap arguments
- Handle serialization differently
- Use a different calling convention

## Example: Successful Direct Call

```python
import asyncio
from mcp.mcp_server import BlueplanceMCPServer

async def test():
    server = BlueplanceMCPServer()
    result = await server.server.call_tool(
        "trace_get_timeline",
        arguments={
            "arguments": {
                "session_id": "35559e21-c94c-4be2-ac73-905da9ebc449",
                "limit": 5
            }
        }
    )
    # Result is a tuple with TextContent objects
    print(result[0][0].text)  # JSON string with timeline data

asyncio.run(test())
```

## Next Steps

1. ✅ Tool call format identified and working
2. ✅ Bugs fixed in timestamp handling
3. ⚠️ MCP protocol integration in Cursor may need different handling
4. 📝 Consider updating tool function signatures to avoid the `arguments` wrapper if possible

## Files Modified

- `src/mcp/mcp_server.py`: Fixed imports and timestamp handling
- `test_mcp_call_format.py`: Test script to verify format
- `test_mcp_tool_call.py`: Test script for Pydantic model validation






