#!/usr/bin/env python3
# Copyright © 2025 Sierra Labs LLC
# SPDX-License-Identifier: AGPL-3.0-only
# License-Filename: LICENSE

"""
Phase 3: Bubble Data Extraction

Extracts full bubble (message) data from Cursor databases.
"""

import sys
import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.test_composer_metadata import (
    discover_cursor_databases,
    get_composer_metadata_from_itemtable,
    get_composer_metadata_from_cursordiskkv,
    extract_composer_fields
)


def get_bubble_data(db_path: Path, bubble_id: str) -> Optional[Dict]:
    """Get bubble data from cursorDiskKV."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.cursor()
        
        cursor.execute('SELECT value FROM cursorDiskKV WHERE key = ?', (f'bubbleData:{bubble_id}',))
        row = cursor.fetchone()
        
        if row and row[0]:
            value = row[0]
            if isinstance(value, bytes):
                value = value.decode('utf-8')
            return json.loads(value)
        
        conn.close()
        return None
    except Exception as e:
        print(f"   Error reading bubble {bubble_id}: {e}")
        return None


def extract_bubble_fields(bubble: Dict) -> Dict:
    """Extract and validate bubble fields."""
    extracted = {
        # Basic fields
        "bubbleId": bubble.get("bubbleId"),
        "serverBubbleId": bubble.get("serverBubbleId"),
        "type": bubble.get("type"),  # 1=user, 2=ai
        "_v": bubble.get("_v"),
        
        # Message Content
        "text": bubble.get("text"),
        "rawText": bubble.get("rawText"),
        "richText": bubble.get("richText"),
        "delegate": bubble.get("delegate"),
        "has_content": bool(
            bubble.get("text") or 
            bubble.get("rawText") or 
            bubble.get("delegate")
        ),
        
        # Model Configuration (may not be present in this schema version)
        "modelType": bubble.get("modelType"),
        "aiStreamingSettings": bubble.get("aiStreamingSettings"),
        "has_model_config": bool(bubble.get("modelType") or bubble.get("aiStreamingSettings")),
        
        # Thinking/Reasoning (check multiple possible locations)
        "thinking": bubble.get("thinking"),
        "isThought": bubble.get("isThought"),
        "intermediateChunks": bubble.get("intermediateChunks", []),
        "has_thinking": bool(
            bubble.get("thinking") or 
            bubble.get("isThought") or
            (isinstance(bubble.get("intermediateChunks"), list) and len(bubble.get("intermediateChunks", [])) > 0)
        ),
        
        # Tool Usage (check multiple possible locations)
        "toolFormerdata": bubble.get("toolFormerdata"),
        "codeBlocks": bubble.get("codeBlocks", []),
        "capabilitiesRan": bubble.get("capabilitiesRan", {}),
        "has_tool_usage": bool(
            bubble.get("toolFormerdata") or
            (isinstance(bubble.get("codeBlocks"), list) and len(bubble.get("codeBlocks", [])) > 0) or
            (isinstance(bubble.get("capabilitiesRan"), dict) and len(bubble.get("capabilitiesRan", {})) > 0)
        ),
        "tool_calls": [],
        
        # Capabilities (actual field names)
        "capabilities": bubble.get("capabilities", []),  # May not exist
        "capabilitiesRan": bubble.get("capabilitiesRan", {}),  # Actual field
        "capabilityStatuses": bubble.get("capabilityStatuses", {}),  # Actual field
        "has_capabilities": bool(
            bubble.get("capabilities") or
            (isinstance(bubble.get("capabilitiesRan"), dict) and len(bubble.get("capabilitiesRan", {})) > 0) or
            (isinstance(bubble.get("capabilityStatuses"), dict) and len(bubble.get("capabilityStatuses", {})) > 0)
        ),
        "bubbleDataMap": None,
        
        # Message Metadata (check timingInfo dict)
        "timingInfo": bubble.get("timingInfo", {}),
        "createdAt": bubble.get("createdAt") or (bubble.get("timingInfo", {}).get("clientStartTime") if bubble.get("timingInfo") else None),
        "lastUpdatedAt": bubble.get("lastUpdatedAt") or (bubble.get("timingInfo", {}).get("clientEndTime") if bubble.get("timingInfo") else None),
        "completedAt": bubble.get("completedAt") or (bubble.get("timingInfo", {}).get("clientSettleTime") if bubble.get("timingInfo") else None),
        "tokenCount": bubble.get("tokenCount"),  # May not exist
        "tokenCountUpUntilHere": bubble.get("tokenCountUpUntilHere"),  # Actual field
        "tokenDetailsUpUntilHere": bubble.get("tokenDetailsUpUntilHere"),  # Actual field
        "capabilityType": bubble.get("capabilityType"),
        "unifiedMode": bubble.get("unifiedMode"),
        
        # User-specific fields
        "relevantFiles": bubble.get("relevantFiles"),
        "selections": bubble.get("selections"),
        "image": bubble.get("image"),
    }
    
    # Extract tool calls (check multiple sources)
    tool_calls = []
    
    # Check toolFormerdata (expected format)
    if extracted["toolFormerdata"] and isinstance(extracted["toolFormerdata"], dict):
        tool_calls.extend(extracted["toolFormerdata"].get("toolCalls", []))
    
    # Check codeBlocks (may contain tool execution results)
    if isinstance(extracted["codeBlocks"], list):
        tool_calls.extend(extracted["codeBlocks"])
    
    # Check capabilitiesRan (may contain tool execution metadata)
    if isinstance(extracted["capabilitiesRan"], dict):
        # Extract capability names as tool identifiers
        for cap_name, cap_data in extracted["capabilitiesRan"].items():
            if isinstance(cap_data, dict):
                tool_calls.append({
                    "id": cap_name,
                    "type": cap_name,
                    "status": extracted["capabilityStatuses"].get(cap_name) if isinstance(extracted["capabilityStatuses"], dict) else None,
                    "data": cap_data
                })
    
    extracted["tool_calls"] = tool_calls
    extracted["tool_call_count"] = len(tool_calls)
    
    # Extract bubbleDataMap from capabilities (check both formats)
    if extracted["capabilities"]:
        for cap in extracted["capabilities"]:
            if isinstance(cap, dict) and "bubbleDataMap" in cap:
                extracted["bubbleDataMap"] = cap["bubbleDataMap"]
                break
    
    # Also check capabilityStatuses for metadata
    if isinstance(extracted["capabilityStatuses"], dict) and not extracted["bubbleDataMap"]:
        extracted["bubbleDataMap"] = extracted["capabilityStatuses"]
    
    return extracted


def main():
    """Main extraction function."""
    print("=" * 70)
    print("Phase 3: Bubble Data Extraction")
    print("=" * 70)
    print()
    
    # Load composer metadata
    metadata_path = project_root / "docs" / "composer_metadata_report.json"
    if not metadata_path.exists():
        print("❌ Composer metadata report not found!")
        print("   Run Phase 2 first: python3 scripts/test_composer_metadata.py")
        return 1
    
    with open(metadata_path) as f:
        metadata_report = json.load(f)
    
    composers = metadata_report.get("composers", [])
    
    if not composers:
        print("❌ No composers found in metadata report!")
        return 1
    
    print(f"Found {len(composers)} composer(s) to process")
    print()
    
    # Discover databases
    databases = discover_cursor_databases()
    
    if not databases:
        print("❌ No Cursor database files found!")
        return 1
    
    # Find global storage database with cursorDiskKV table (where full composer data is stored)
    global_db = None
    for db_path in databases:
        if "globalStorage" in str(db_path):
            try:
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cursorDiskKV'")
                if cursor.fetchone():
                    global_db = db_path
                    conn.close()
                    break
                conn.close()
            except:
                continue
    
    if not global_db:
        print("❌ No global storage database with cursorDiskKV table found!")
        return 1
    
    print(f"Using database: {global_db.name}")
    print(f"  Path: {global_db}")
    print()
    
    # Load full composer data from global storage (bubbles are embedded in conversation array)
    print("Loading full composer data from global storage...")
    full_composers = get_composer_metadata_from_cursordiskkv(global_db)
    print(f"  Loaded {len(full_composers)} composer(s) with full data")
    print()
    
    # Create lookup by composerId
    composer_lookup = {c.get("composerId"): c for c in full_composers}
    
    # Process each composer
    all_bubbles = []
    
    for composer_meta in composers:
        composer_id = composer_meta.get("composerId")
        composer_name = composer_meta.get("name") or "Untitled"
        
        # Get full composer data
        full_composer = composer_lookup.get(composer_id)
        if not full_composer:
            print(f"Composer: {composer_name} ({composer_id[:8]}...)")
            print(f"  ⚠️  Full composer data not found in global storage")
            print()
            continue
        
        # Extract conversation array (bubbles are embedded here)
        conversation = full_composer.get("conversation", []) or full_composer.get("fullConversationHeadersOnly", [])
        
        print(f"Composer: {composer_name} ({composer_id[:8]}...)")
        print(f"  Bubbles to extract: {len(conversation)}")
        
        composer_bubbles = []
        
        for bubble_data in conversation:
            if not bubble_data:
                continue
                
            extracted = extract_bubble_fields(bubble_data)
            extracted["composerId"] = composer_id
            composer_bubbles.append(extracted)
            
            # Print summary
            bubble_type = "User" if extracted["type"] == 1 else "AI"
            bubble_id = extracted.get("bubbleId", "unknown")[:8]
            print(f"    ✅ {bubble_type} bubble: {bubble_id}...")
            if extracted["has_content"]:
                content_preview = (
                    extracted.get("text") or 
                    extracted.get("rawText") or 
                    extracted.get("delegate") or 
                    ""
                )[:50]
                print(f"      Content: {content_preview}...")
            if extracted["has_model_config"]:
                print(f"      Model: {extracted['modelType']}")
            if extracted["has_thinking"]:
                print(f"      Thinking: present")
            if extracted["has_tool_usage"]:
                print(f"      Tool calls: {extracted.get('tool_call_count', 0)}")
            if extracted["has_capabilities"]:
                print(f"      Capabilities: {len(extracted['capabilities'])}")
        
        print(f"  Extracted {len(composer_bubbles)}/{len(conversation)} bubbles")
        print()
        
        all_bubbles.extend(composer_bubbles)
    
    # Generate summary
    print("=" * 70)
    print("Extraction Summary")
    print("=" * 70)
    
    total_bubbles = len(all_bubbles)
    user_bubbles = sum(1 for b in all_bubbles if b["type"] == 1)
    ai_bubbles = sum(1 for b in all_bubbles if b["type"] == 2)
    bubbles_with_content = sum(1 for b in all_bubbles if b["has_content"])
    bubbles_with_model = sum(1 for b in all_bubbles if b["has_model_config"])
    bubbles_with_thinking = sum(1 for b in all_bubbles if b["has_thinking"])
    bubbles_with_tools = sum(1 for b in all_bubbles if b["has_tool_usage"])
    bubbles_with_capabilities = sum(1 for b in all_bubbles if b["has_capabilities"])
    
    print(f"Total bubbles extracted: {total_bubbles}")
    print(f"  User messages: {user_bubbles}")
    print(f"  AI messages: {ai_bubbles}")
    if total_bubbles > 0:
        print(f"  With content: {bubbles_with_content} ({bubbles_with_content/total_bubbles*100:.1f}%)")
        print(f"  With model config: {bubbles_with_model} ({bubbles_with_model/total_bubbles*100:.1f}%)")
        print(f"  With thinking: {bubbles_with_thinking} ({bubbles_with_thinking/total_bubbles*100:.1f}%)")
        print(f"  With tool usage: {bubbles_with_tools} ({bubbles_with_tools/total_bubbles*100:.1f}%)")
        print(f"  With capabilities: {bubbles_with_capabilities} ({bubbles_with_capabilities/total_bubbles*100:.1f}%)")
    else:
        print("  ⚠️  No bubbles found - checking global storage database...")
    print()
    
    # Save results
    output = {
        "database_path": str(global_db),
        "total_bubbles": total_bubbles,
        "summary": {
            "user_bubbles": user_bubbles,
            "ai_bubbles": ai_bubbles,
            "with_content": bubbles_with_content,
            "with_model_config": bubbles_with_model,
            "with_thinking": bubbles_with_thinking,
            "with_tool_usage": bubbles_with_tools,
            "with_capabilities": bubbles_with_capabilities,
        },
        "bubbles": all_bubbles
    }
    
    report_path = project_root / "docs" / "bubble_data_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(output, f, indent=2)
    
    print(f"✅ Bubble data report saved to: {report_path}")
    print()
    print("Note: Full bubble data includes all fields. Check the JSON report for details.")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

