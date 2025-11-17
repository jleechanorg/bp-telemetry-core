#!/usr/bin/env python3
"""Test script to debug MCP tool call format."""

import sys
import json
from pathlib import Path

# Add src to path  
sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from mcp.mcp_server import BlueplanceMCPServer, TraceTimelineParams
from pydantic import ValidationError

def test_pydantic_model():
    """Test creating TraceTimelineParams directly."""
    print("Testing TraceTimelineParams Pydantic model...")
    
    # Test 1: Create with just session_id
    try:
        params = TraceTimelineParams(session_id="35559e21-c94c-4be2-ac73-905da9ebc449")
        print(f"✅ Test 1 passed: {params.session_id}")
    except ValidationError as e:
        print(f"❌ Test 1 failed: {e}")
    
    # Test 2: Create with dict
    try:
        params = TraceTimelineParams(**{"session_id": "35559e21-c94c-4be2-ac73-905da9ebc449"})
        print(f"✅ Test 2 passed: {params.session_id}")
    except ValidationError as e:
        print(f"❌ Test 2 failed: {e}")
    
    # Test 3: Create with limit
    try:
        params = TraceTimelineParams(
            session_id="35559e21-c94c-4be2-ac73-905da9ebc449",
            limit=10
        )
        print(f"✅ Test 3 passed: session_id={params.session_id}, limit={params.limit}")
    except ValidationError as e:
        print(f"❌ Test 3 failed: {e}")

def test_mcp_server_tool_registration():
    """Test that tools are registered correctly."""
    print("\nTesting MCP server tool registration...")
    
    try:
        server = BlueplanceMCPServer()
        print(f"✅ Server created: {server.server.name}")
        
        # Check if tools are registered
        # FastMCP stores tools in server._tools or similar
        # Let's try to inspect the server object
        if hasattr(server.server, '_tools'):
            print(f"  Tools registered: {len(server.server._tools)}")
            for tool_name in server.server._tools.keys():
                print(f"    - {tool_name}")
        elif hasattr(server.server, 'tools'):
            print(f"  Tools registered: {len(server.server.tools)}")
            for tool_name in server.server.tools.keys():
                print(f"    - {tool_name}")
        else:
            print("  ⚠️  Could not inspect registered tools")
            print(f"  Server attributes: {[attr for attr in dir(server.server) if not attr.startswith('_')]}")
            
    except Exception as e:
        print(f"❌ Server creation failed: {e}")
        import traceback
        traceback.print_exc()

def test_tool_call_format():
    """Test different argument formats that might work."""
    print("\nTesting different tool call formats...")
    
    # Format 1: Direct dict matching Pydantic fields
    format1 = {
        "session_id": "35559e21-c94c-4be2-ac73-905da9ebc449"
    }
    print(f"\nFormat 1 (direct dict): {json.dumps(format1, indent=2)}")
    
    # Format 2: Nested arguments
    format2 = {
        "arguments": {
            "session_id": "35559e21-c94c-4be2-ac73-905da9ebc449"
        }
    }
    print(f"\nFormat 2 (nested arguments): {json.dumps(format2, indent=2)}")
    
    # Format 3: With limit
    format3 = {
        "session_id": "35559e21-c94c-4be2-ac73-905da9ebc449",
        "limit": 10
    }
    print(f"\nFormat 3 (with limit): {json.dumps(format3, indent=2)}")

if __name__ == "__main__":
    print("=" * 60)
    print("MCP Tool Call Format Debugging")
    print("=" * 60)
    
    test_pydantic_model()
    test_mcp_server_tool_registration()
    test_tool_call_format()
    
    print("\n" + "=" * 60)
    print("Next steps:")
    print("1. Check FastMCP documentation for tool call format")
    print("2. Inspect actual MCP protocol messages")
    print("3. Test with actual MCP client")
    print("=" * 60)

