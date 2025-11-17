#!/usr/bin/env python3
"""Test script to find the correct MCP tool call format."""

import sys
import asyncio
import json
from pathlib import Path

# Add src to path  
sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from mcp.mcp_server import BlueplanceMCPServer

async def test_tool_calls():
    """Test calling the tool with different formats."""
    print("=" * 60)
    print("Testing MCP Tool Call Formats")
    print("=" * 60)
    
    server = BlueplanceMCPServer()
    
    # List available tools
    print("\n1. Listing available tools...")
    try:
        tools = await server.server.list_tools()
        # FastMCP list_tools might return a list directly or a response object
        if isinstance(tools, list):
            tools_list = tools
        elif hasattr(tools, 'tools'):
            tools_list = tools.tools
        else:
            tools_list = [tools]
        
        print(f"   Found {len(tools_list)} tools:")
        for tool in tools_list:
            tool_name = tool.name if hasattr(tool, 'name') else str(tool)
            tool_desc = tool.description if hasattr(tool, 'description') else "No description"
            print(f"     - {tool_name}: {tool_desc}")
            if hasattr(tool, 'inputSchema') and tool_name == "trace_get_timeline":
                print(f"       Parameters schema:")
                print(json.dumps(tool.inputSchema, indent=8))
    except Exception as e:
        print(f"   Error listing tools: {e}")
        import traceback
        traceback.print_exc()
        # Continue anyway
    
    # Test Format 1: Direct dict matching Pydantic fields
    print("\n2. Testing Format 1: Direct dict (session_id as top-level key)")
    try:
        result = await server.server.call_tool(
            "trace_get_timeline",
            arguments={
                "session_id": "35559e21-c94c-4be2-ac73-905da9ebc449",
                "limit": 5
            }
        )
        print(f"   ✅ Format 1 SUCCESS!")
        print(f"   Result: {len(result.content)} items")
        if result.content:
            print(f"   First item: {result.content[0]}")
    except Exception as e:
        print(f"   ❌ Format 1 FAILED: {e}")
        import traceback
        traceback.print_exc()
    
    # Test Format 2: Nested arguments (CORRECT FORMAT!)
    print("\n3. Testing Format 2: Nested arguments (CORRECT FORMAT)")
    try:
        result = await server.server.call_tool(
            "trace_get_timeline",
            arguments={
                "arguments": {
                    "session_id": "35559e21-c94c-4be2-ac73-905da9ebc449",
                    "limit": 5
                }
            }
        )
        print(f"   ✅ Format 2 SUCCESS!")
        # Result might be a tuple or have different structure
        if isinstance(result, tuple):
            print(f"   Result type: tuple with {len(result)} items")
            print(f"   First item: {result[0] if result else 'empty'}")
        elif hasattr(result, 'content'):
            print(f"   Result: {len(result.content)} items")
        else:
            print(f"   Result type: {type(result)}")
            print(f"   Result: {result}")
    except Exception as e:
        print(f"   ❌ Format 2 FAILED: {e}")
        import traceback
        traceback.print_exc()
    
    # Test Format 3: Just session_id
    print("\n4. Testing Format 3: Just session_id")
    try:
        result = await server.server.call_tool(
            "trace_get_timeline",
            arguments={
                "session_id": "35559e21-c94c-4be2-ac73-905da9ebc449"
            }
        )
        print(f"   ✅ Format 3 SUCCESS!")
        print(f"   Result: {len(result.content)} items")
    except Exception as e:
        print(f"   ❌ Format 3 FAILED: {e}")

if __name__ == "__main__":
    asyncio.run(test_tool_calls())

