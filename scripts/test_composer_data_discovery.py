#!/usr/bin/env python3
# Copyright © 2025 Sierra Labs LLC
# SPDX-License-Identifier: AGPL-3.0-only
# License-Filename: LICENSE

"""
Phase 1: Database Discovery

Discovers all Cursor database files and analyzes their structure.
"""

import sys
import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.processing.cursor.platform import get_cursor_database_paths


def discover_cursor_databases() -> List[Path]:
    """Discover all Cursor database files (workspace + global storage)."""
    databases = []
    
    # Workspace storage databases
    for base_path in get_cursor_database_paths():
        if base_path.exists():
            for workspace_dir in base_path.iterdir():
                if workspace_dir.is_dir():
                    db_file = workspace_dir / "state.vscdb"
                    if db_file.exists():
                        databases.append(db_file)
    
    # Global storage database (macOS)
    home = Path.home()
    global_storage_paths = [
        home / "Library/Application Support/Cursor/User/globalStorage/state.vscdb",
        home / ".config/Cursor/User/globalStorage/state.vscdb",
        home / "AppData/Roaming/Cursor/User/globalStorage/state.vscdb",
    ]
    
    for global_path in global_storage_paths:
        if global_path.exists():
            databases.append(global_path)
    
    return databases


def analyze_database(db_path: Path) -> Dict:
    """Analyze a single database file."""
    result = {
        "path": str(db_path),
        "exists": db_path.exists(),
        "tables": {},
        "key_patterns": defaultdict(int),
        "errors": []
    }
    
    if not db_path.exists():
        result["errors"].append("Database file does not exist")
        return result
    
    try:
        # Connect in read-only mode
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        # Analyze each table
        for table_name in tables:
            table_info = {
                "row_count": 0,
                "sample_keys": [],
                "key_patterns": defaultdict(int)
            }
            
            try:
                # Count rows
                cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
                table_info["row_count"] = cursor.fetchone()[0]
                
                # Get sample keys (if key-value table)
                if table_name in ["ItemTable", "cursorDiskKV"]:
                    cursor.execute(f'SELECT key FROM "{table_name}" LIMIT 100')
                    keys = [row[0] for row in cursor.fetchall()]
                    table_info["sample_keys"] = keys[:20]  # First 20
                    
                    # Analyze key patterns
                    for key in keys:
                        if key.startswith("composer.composerData"):
                            table_info["key_patterns"]["composer.composerData"] += 1
                        elif key.startswith("composerData:"):
                            table_info["key_patterns"]["composerData:*"] += 1
                        elif key.startswith("bubbleData:"):
                            table_info["key_patterns"]["bubbleData:*"] += 1
                        elif key.startswith("aiService."):
                            table_info["key_patterns"]["aiService.*"] += 1
                        elif "composer" in key.lower():
                            table_info["key_patterns"]["*composer*"] += 1
                        elif "bubble" in key.lower():
                            table_info["key_patterns"]["*bubble*"] += 1
                
                result["tables"][table_name] = table_info
                
            except Exception as e:
                result["errors"].append(f"Error analyzing table {table_name}: {e}")
        
        # Aggregate key patterns across all tables
        for table_info in result["tables"].values():
            for pattern, count in table_info["key_patterns"].items():
                result["key_patterns"][pattern] += count
        
        conn.close()
        
    except Exception as e:
        result["errors"].append(f"Error connecting to database: {e}")
    
    return result


def main():
    """Main discovery function."""
    print("=" * 70)
    print("Phase 1: Cursor Database Discovery")
    print("=" * 70)
    print()
    
    # Discover databases
    print("1. Discovering Cursor database files...")
    databases = discover_cursor_databases()
    
    if not databases:
        print("❌ No Cursor database files found!")
        print("\nChecked locations:")
        for base_path in get_cursor_database_paths():
            print(f"   - {base_path}")
        print("   - ~/Library/Application Support/Cursor/User/globalStorage/state.vscdb")
        return 1
    
    print(f"✅ Found {len(databases)} database file(s)")
    for db in databases:
        print(f"   - {db}")
    print()
    
    # Analyze each database
    print("2. Analyzing database structure...")
    all_results = []
    
    for db_path in databases:
        print(f"\n   Analyzing: {db_path.name}")
        result = analyze_database(db_path)
        all_results.append(result)
        
        if result["errors"]:
            print(f"   ⚠️  Errors: {len(result['errors'])}")
            for error in result["errors"]:
                print(f"      - {error}")
        else:
            print(f"   ✅ Tables found: {len(result['tables'])}")
            for table_name, table_info in result["tables"].items():
                print(f"      - {table_name}: {table_info['row_count']} rows")
                if table_info["key_patterns"]:
                    print(f"        Key patterns:")
                    for pattern, count in table_info["key_patterns"].items():
                        print(f"          - {pattern}: {count}")
    
    # Generate summary report
    print("\n" + "=" * 70)
    print("3. Summary Report")
    print("=" * 70)
    
    summary = {
        "databases_found": len(databases),
        "databases": []
    }
    
    for result in all_results:
        db_summary = {
            "path": result["path"],
            "tables": list(result["tables"].keys()),
            "total_rows": sum(t["row_count"] for t in result["tables"].values()),
            "key_patterns": dict(result["key_patterns"]),
            "has_composer_data": (
                result["key_patterns"]["composer.composerData"] > 0 or
                result["key_patterns"]["composerData:*"] > 0
            ),
            "has_bubble_data": result["key_patterns"]["bubbleData:*"] > 0,
            "errors": result["errors"]
        }
        summary["databases"].append(db_summary)
        
        print(f"\nDatabase: {Path(result['path']).name}")
        print(f"  Location: {result['path']}")
        print(f"  Tables: {', '.join(db_summary['tables'])}")
        print(f"  Total rows: {db_summary['total_rows']}")
        print(f"  Has composer data: {'✅' if db_summary['has_composer_data'] else '❌'}")
        print(f"  Has bubble data: {'✅' if db_summary['has_bubble_data'] else '❌'}")
        if db_summary["key_patterns"]:
            print(f"  Key patterns:")
            for pattern, count in db_summary["key_patterns"].items():
                print(f"    - {pattern}: {count}")
    
    # Save JSON report
    report_path = project_root / "docs" / "composer_data_discovery_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n✅ Detailed report saved to: {report_path}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())






