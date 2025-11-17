#!/usr/bin/env python3
# Copyright © 2025 Sierra Labs LLC
# SPDX-License-Identifier: AGPL-3.0-only
# License-Filename: LICENSE

"""
Phase 2: Composer Metadata Extraction

Extracts composer metadata from Cursor databases.
"""

import sys
import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.test_composer_data_discovery import discover_cursor_databases, analyze_database


def get_composer_metadata_from_itemtable(db_path: Path) -> Optional[Dict]:
    """Get composer metadata from ItemTable."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.cursor()
        
        cursor.execute('SELECT value FROM ItemTable WHERE key = ?', ('composer.composerData',))
        row = cursor.fetchone()
        
        if row and row[0]:
            value = row[0]
            if isinstance(value, bytes):
                value = value.decode('utf-8')
            return json.loads(value)
        
        conn.close()
        return None
    except Exception as e:
        print(f"   Error reading ItemTable: {e}")
        return None


def get_composer_metadata_from_cursordiskkv(db_path: Path, composer_id: Optional[str] = None) -> List[Dict]:
    """Get composer metadata from cursorDiskKV table."""
    composers = []
    
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.cursor()
        
        if composer_id:
            # Get specific composer
            cursor.execute('SELECT value FROM cursorDiskKV WHERE key = ?', (f'composerData:{composer_id}',))
            row = cursor.fetchone()
            if row and row[0]:
                value = row[0]
                if isinstance(value, bytes):
                    value = value.decode('utf-8')
                composers.append(json.loads(value))
        else:
            # Get all composers
            cursor.execute('SELECT key, value FROM cursorDiskKV WHERE key LIKE ?', ('composerData:%',))
            for row in cursor.fetchall():
                try:
                    value = row[1]
                    if isinstance(value, bytes):
                        value = value.decode('utf-8')
                    composer = json.loads(value)
                    composers.append(composer)
                except json.JSONDecodeError as e:
                    print(f"   Error parsing composer data: {e}")
                    continue
        
        conn.close()
    except Exception as e:
        print(f"   Error reading cursorDiskKV: {e}")
    
    return composers


def extract_composer_fields(composer: Dict) -> Dict:
    """Extract and validate composer fields."""
    extracted = {
        "composerId": composer.get("composerId"),
        "name": composer.get("name"),
        "createdAt": composer.get("createdAt"),
        "lastUpdatedAt": composer.get("lastUpdatedAt"),
        "status": composer.get("status"),
        "isAgentic": composer.get("isAgentic"),
        "_v": composer.get("_v"),
        "fullConversationHeadersOnly": composer.get("fullConversationHeadersOnly", []),
        "conversation": composer.get("conversation", []),  # Alternative field name
        "latestConversationSummary": composer.get("latestConversationSummary"),
        "usageData": composer.get("usageData"),
        "context": composer.get("context"),
    }
    
    # Count bubbles - check both field names
    conversation_array = extracted["fullConversationHeadersOnly"] or extracted["conversation"]
    extracted["bubble_count"] = len(conversation_array)
    
    # Extract bubble IDs
    extracted["bubble_ids"] = [
        bubble.get("bubbleId") 
        for bubble in conversation_array
        if bubble.get("bubbleId")
    ]
    
    # Store which field was used
    extracted["has_full_conversation"] = bool(extracted["fullConversationHeadersOnly"])
    extracted["has_conversation"] = bool(extracted["conversation"])
    
    return extracted


def main():
    """Main extraction function."""
    print("=" * 70)
    print("Phase 2: Composer Metadata Extraction")
    print("=" * 70)
    print()
    
    # Discover databases
    databases = discover_cursor_databases()
    
    if not databases:
        print("❌ No Cursor database files found!")
        return 1
    
    print(f"Found {len(databases)} database file(s)")
    print()
    
    all_composers = []
    
    # Process each database
    for db_path in databases:
        print(f"Processing: {db_path.name}")
        print(f"  Path: {db_path}")
        
        # Check database structure
        analysis = analyze_database(db_path)
        has_itemtable = "ItemTable" in analysis["tables"]
        has_cursordiskkv = "cursorDiskKV" in analysis["tables"]
        
        print(f"  Tables: ItemTable={'✅' if has_itemtable else '❌'}, cursorDiskKV={'✅' if has_cursordiskkv else '❌'}")
        
        # Try ItemTable first
        if has_itemtable:
            print("  Checking ItemTable for composer.composerData...")
            composer_data = get_composer_metadata_from_itemtable(db_path)
            
            if composer_data:
                print(f"  ✅ Found composer data in ItemTable")
                
                # Handle different structures
                if "allComposers" in composer_data:
                    # This is the list format
                    print(f"    Found {len(composer_data.get('allComposers', []))} composer(s) in list")
                    for composer_ref in composer_data.get("allComposers", []):
                        composer_id = composer_ref.get("composerId")
                        if composer_id:
                            # Try to get full data from cursorDiskKV
                            full_composers = get_composer_metadata_from_cursordiskkv(db_path, composer_id)
                            if full_composers:
                                all_composers.extend(full_composers)
                            else:
                                # Use metadata only
                                all_composers.append(composer_ref)
                else:
                    # Single composer object
                    all_composers.append(composer_data)
            else:
                print("    No composer.composerData found in ItemTable")
        
        # Try cursorDiskKV
        if has_cursordiskkv:
            print("  Checking cursorDiskKV for composerData:* keys...")
            composers = get_composer_metadata_from_cursordiskkv(db_path)
            
            if composers:
                print(f"  ✅ Found {len(composers)} composer(s) in cursorDiskKV")
                all_composers.extend(composers)
            else:
                print("    No composerData:* keys found in cursorDiskKV")
        
        # Also check global storage database (it has cursorDiskKV with composer data)
        if "globalStorage" in str(db_path):
            print("  Checking global storage cursorDiskKV...")
            composers = get_composer_metadata_from_cursordiskkv(db_path)
            if composers:
                print(f"  ✅ Found {len(composers)} composer(s) in global storage")
                all_composers.extend(composers)
        
        print()
    
    # Deduplicate by composerId
    seen_ids = set()
    unique_composers = []
    for composer in all_composers:
        composer_id = composer.get("composerId")
        if composer_id and composer_id not in seen_ids:
            seen_ids.add(composer_id)
            unique_composers.append(composer)
    
    print("=" * 70)
    print(f"Found {len(unique_composers)} unique composer(s)")
    print("=" * 70)
    print()
    
    # Extract and validate fields
    extracted_composers = []
    for composer in unique_composers:
        extracted = extract_composer_fields(composer)
        extracted_composers.append(extracted)
        
        print(f"Composer: {extracted['name'] or 'Untitled'}")
        print(f"  ID: {extracted['composerId']}")
        print(f"  Created: {extracted['createdAt']}")
        print(f"  Updated: {extracted['lastUpdatedAt']}")
        print(f"  Status: {extracted['status']}")
        print(f"  Is Agentic: {extracted['isAgentic']}")
        print(f"  Schema Version: {extracted['_v']}")
        print(f"  Bubbles: {extracted['bubble_count']}")
        print(f"  Bubble IDs: {len(extracted['bubble_ids'])}")
        if extracted['usageData']:
            print(f"  Usage Data: {len(extracted['usageData'])} model(s)")
        if extracted['context']:
            print(f"  Context: present")
        print()
    
    # Save results
    output = {
        "total_composers": len(extracted_composers),
        "composers": extracted_composers
    }
    
    report_path = project_root / "docs" / "composer_metadata_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(output, f, indent=2)
    
    print(f"✅ Metadata report saved to: {report_path}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

