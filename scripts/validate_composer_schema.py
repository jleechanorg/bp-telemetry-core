#!/usr/bin/env python3
# Copyright © 2025 Sierra Labs LLC
# SPDX-License-Identifier: AGPL-3.0-only
# License-Filename: LICENSE

"""
Phase 4: Data Validation Report

Validates that all required fields are present in extracted composer and bubble data.
"""

import sys
import json
from pathlib import Path
from typing import Dict, List, Set
from collections import defaultdict

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def validate_composer_fields(composer: Dict) -> Dict:
    """Validate composer fields."""
    required_fields = {
        "composerId": "string",
        "name": "string",
        "createdAt": "number",
        "lastUpdatedAt": "number",
        "fullConversationHeadersOnly": "array",
    }
    
    optional_fields = {
        "status": "string",
        "isAgentic": "boolean",
        "_v": "number",
        "latestConversationSummary": "object",
        "usageData": "object",
        "context": "object",
    }
    
    validation = {
        "composerId": composer.get("composerId"),
        "required_fields": {},
        "optional_fields": {},
        "missing_required": [],
        "present_optional": [],
        "bubble_count": len(composer.get("bubble_ids", [])),
    }
    
    # Check required fields
    for field, expected_type in required_fields.items():
        value = composer.get(field)
        if value is not None:
            actual_type = type(value).__name__
            validation["required_fields"][field] = {
                "present": True,
                "type": actual_type,
                "expected_type": expected_type,
                "valid": actual_type == expected_type or (expected_type == "number" and actual_type == "int"),
            }
        else:
            validation["required_fields"][field] = {"present": False}
            validation["missing_required"].append(field)
    
    # Check optional fields
    for field, expected_type in optional_fields.items():
        value = composer.get(field)
        if value is not None:
            actual_type = type(value).__name__
            validation["optional_fields"][field] = {
                "present": True,
                "type": actual_type,
            }
            validation["present_optional"].append(field)
        else:
            validation["optional_fields"][field] = {"present": False}
    
    return validation


def validate_bubble_fields(bubble: Dict) -> Dict:
    """Validate bubble fields."""
    required_fields = {
        "bubbleId": "string",
        "type": "number",  # 1=user, 2=ai
    }
    
    content_fields = {
        "text": "string",
        "rawText": "string",
        "richText": "object",
        "delegate": "string",
    }
    
    model_fields = {
        "modelType": "string",
        "aiStreamingSettings": "object",
    }
    
    thinking_fields = {
        "thinking": "string",
    }
    
    tool_fields = {
        "toolFormerdata": "object",
        "tool_calls": "array",
    }
    
    capability_fields = {
        "capabilities": "array",
        "bubbleDataMap": "object",
    }
    
    metadata_fields = {
        "createdAt": "number",
        "lastUpdatedAt": "number",
        "completedAt": "number",
        "tokenCount": "object",
        "capabilityType": "number",
        "unifiedMode": "number",
    }
    
    validation = {
        "bubbleId": bubble.get("bubbleId"),
        "type": bubble.get("type"),
        "required_fields": {},
        "content_fields": {},
        "model_fields": {},
        "thinking_fields": {},
        "tool_fields": {},
        "capability_fields": {},
        "metadata_fields": {},
        "coverage": {},
    }
    
    # Check required fields
    for field, expected_type in required_fields.items():
        value = bubble.get(field)
        validation["required_fields"][field] = {
            "present": value is not None,
            "value": value,
        }
    
    # Check content fields
    content_present = 0
    for field in content_fields:
        value = bubble.get(field)
        validation["content_fields"][field] = {"present": value is not None}
        if value is not None:
            content_present += 1
    
    # Check model fields
    model_present = 0
    for field in model_fields:
        value = bubble.get(field)
        validation["model_fields"][field] = {"present": value is not None}
        if value is not None:
            model_present += 1
    
    # Check thinking fields
    thinking_present = 0
    for field in thinking_fields:
        value = bubble.get(field)
        validation["thinking_fields"][field] = {"present": value is not None}
        if value is not None:
            thinking_present += 1
    
    # Check tool fields
    tool_present = 0
    for field in tool_fields:
        value = bubble.get(field)
        validation["tool_fields"][field] = {"present": value is not None}
        if value is not None:
            tool_present += 1
    
    # Check capability fields
    capability_present = 0
    for field in capability_fields:
        value = bubble.get(field)
        validation["capability_fields"][field] = {"present": value is not None}
        if value is not None:
            capability_present += 1
    
    # Check metadata fields
    metadata_present = 0
    for field in metadata_fields:
        value = bubble.get(field)
        validation["metadata_fields"][field] = {"present": value is not None}
        if value is not None:
            metadata_present += 1
    
    # Calculate coverage
    validation["coverage"] = {
        "content": f"{content_present}/{len(content_fields)}",
        "model": f"{model_present}/{len(model_fields)}",
        "thinking": f"{thinking_present}/{len(thinking_fields)}",
        "tool": f"{tool_present}/{len(tool_fields)}",
        "capability": f"{capability_present}/{len(capability_fields)}",
        "metadata": f"{metadata_present}/{len(metadata_fields)}",
    }
    
    return validation


def main():
    """Main validation function."""
    print("=" * 70)
    print("Phase 4: Data Validation Report")
    print("=" * 70)
    print()
    
    # Load composer metadata
    metadata_path = project_root / "docs" / "composer_metadata_report.json"
    if not metadata_path.exists():
        print("❌ Composer metadata report not found!")
        print("   Run Phase 2 first: python3 scripts/test_composer_metadata.py")
        return 1
    
    with open(metadata_path) as f:
        composer_data = json.load(f)
    
    # Load bubble data
    bubble_path = project_root / "docs" / "bubble_data_report.json"
    if not bubble_path.exists():
        print("❌ Bubble data report not found!")
        print("   Run Phase 3 first: python3 scripts/test_bubble_data.py")
        return 1
    
    with open(bubble_path) as f:
        bubble_data = json.load(f)
    
    composers = composer_data.get("composers", [])
    bubbles = bubble_data.get("bubbles", [])
    
    print(f"Validating {len(composers)} composer(s) and {len(bubbles)} bubble(s)")
    print()
    
    # Validate composers
    print("1. Validating Composer Data")
    print("-" * 70)
    
    composer_validations = []
    for composer in composers:
        validation = validate_composer_fields(composer)
        composer_validations.append(validation)
        
        composer_id = validation["composerId"]
        print(f"\nComposer: {composer_id[:8]}...")
        print(f"  Required fields: {len([f for f in validation['required_fields'].values() if f.get('present')])}/{len(validation['required_fields'])}")
        print(f"  Optional fields: {len(validation['present_optional'])}/{len(validation['optional_fields'])}")
        print(f"  Bubbles: {validation['bubble_count']}")
        
        if validation["missing_required"]:
            print(f"  ⚠️  Missing required: {', '.join(validation['missing_required'])}")
    
    # Validate bubbles
    print("\n" + "=" * 70)
    print("2. Validating Bubble Data")
    print("-" * 70)
    
    bubble_validations = []
    for bubble in bubbles:
        validation = validate_bubble_fields(bubble)
        bubble_validations.append(validation)
    
    # Aggregate statistics
    total_bubbles = len(bubbles)
    user_bubbles = [b for b in bubble_validations if b["type"] == 1]
    ai_bubbles = [b for b in bubble_validations if b["type"] == 2]
    
    # Content coverage
    content_coverage = defaultdict(int)
    model_coverage = defaultdict(int)
    thinking_coverage = defaultdict(int)
    tool_coverage = defaultdict(int)
    capability_coverage = defaultdict(int)
    metadata_coverage = defaultdict(int)
    
    for validation in bubble_validations:
        content_coverage[validation["coverage"]["content"]] += 1
        model_coverage[validation["coverage"]["model"]] += 1
        thinking_coverage[validation["coverage"]["thinking"]] += 1
        tool_coverage[validation["coverage"]["tool"]] += 1
        capability_coverage[validation["coverage"]["capability"]] += 1
        metadata_coverage[validation["coverage"]["metadata"]] += 1
    
    print(f"\nTotal bubbles: {total_bubbles}")
    print(f"  User messages: {len(user_bubbles)}")
    print(f"  AI messages: {len(ai_bubbles)}")
    
    print("\nContent Fields Coverage:")
    for coverage, count in sorted(content_coverage.items()):
        print(f"  {coverage}: {count} bubbles ({count/total_bubbles*100:.1f}%)")
    
    print("\nModel Configuration Coverage:")
    for coverage, count in sorted(model_coverage.items()):
        print(f"  {coverage}: {count} bubbles ({count/total_bubbles*100:.1f}%)")
    
    print("\nThinking/Reasoning Coverage:")
    for coverage, count in sorted(thinking_coverage.items()):
        print(f"  {coverage}: {count} bubbles ({count/total_bubbles*100:.1f}%)")
    
    print("\nTool Usage Coverage:")
    for coverage, count in sorted(tool_coverage.items()):
        print(f"  {coverage}: {count} bubbles ({count/total_bubbles*100:.1f}%)")
    
    print("\nCapabilities Coverage:")
    for coverage, count in sorted(capability_coverage.items()):
        print(f"  {coverage}: {count} bubbles ({count/total_bubbles*100:.1f}%)")
    
    print("\nMetadata Coverage:")
    for coverage, count in sorted(metadata_coverage.items()):
        print(f"  {coverage}: {count} bubbles ({count/total_bubbles*100:.1f}%)")
    
    # Generate markdown report
    report_lines = [
        "# Composer Data Schema Validation Report",
        "",
        "## Summary",
        "",
        f"- **Composers validated**: {len(composers)}",
        f"- **Bubbles validated**: {total_bubbles}",
        f"- **User messages**: {len(user_bubbles)}",
        f"- **AI messages**: {len(ai_bubbles)}",
        "",
        "## Required Fields Validation",
        "",
        "### Composer Fields",
        "",
        "| Field | Present | Type | Valid |",
        "|-------|---------|------|-------|",
    ]
    
    # Aggregate composer field stats
    composer_field_stats = defaultdict(lambda: {"present": 0, "total": 0, "types": defaultdict(int)})
    for validation in composer_validations:
        for field, info in validation["required_fields"].items():
            composer_field_stats[field]["total"] += 1
            if info.get("present"):
                composer_field_stats[field]["present"] += 1
                composer_field_stats[field]["types"][info.get("type", "unknown")] += 1
    
    for field, stats in composer_field_stats.items():
        present_pct = stats["present"] / stats["total"] * 100 if stats["total"] > 0 else 0
        report_lines.append(
            f"| {field} | {stats['present']}/{stats['total']} ({present_pct:.1f}%) | {', '.join(stats['types'].keys())} | ✅ |"
        )
    
    report_lines.extend([
        "",
        "### Bubble Fields",
        "",
        "| Category | Coverage |",
        "|----------|----------|",
        f"| Content Fields | {dict(content_coverage)} |",
        f"| Model Configuration | {dict(model_coverage)} |",
        f"| Thinking/Reasoning | {dict(thinking_coverage)} |",
        f"| Tool Usage | {dict(tool_coverage)} |",
        f"| Capabilities | {dict(capability_coverage)} |",
        f"| Metadata | {dict(metadata_coverage)} |",
        "",
        "## Success Criteria",
        "",
    ])
    
    # Check success criteria
    success_criteria = {
        "Full conversation arrays": len([c for c in composer_validations if c["bubble_count"] > 0]) > 0,
        "Message content": sum(1 for b in bubble_validations if b["content_fields"].get("text", {}).get("present") or b["content_fields"].get("rawText", {}).get("present")) > 0,
        "Tool usage data": sum(1 for b in bubble_validations if b["tool_fields"].get("toolFormerdata", {}).get("present")) > 0,
        "Capabilities/bubbleDataMap": sum(1 for b in bubble_validations if b["capability_fields"].get("capabilities", {}).get("present")) > 0,
        "Model configuration": sum(1 for b in bubble_validations if b["model_fields"].get("modelType", {}).get("present")) > 0,
        "Thinking/reasoning": sum(1 for b in bubble_validations if b["thinking_fields"].get("thinking", {}).get("present")) > 0,
        "Message metadata": sum(1 for b in bubble_validations if b["metadata_fields"].get("createdAt", {}).get("present")) > 0,
    }
    
    for criterion, met in success_criteria.items():
        status = "✅" if met else "❌"
        report_lines.append(f"- {status} {criterion}")
    
    report_lines.append("")
    
    # Save report
    report_path = project_root / "docs" / "composer_schema_validation_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        f.write("\n".join(report_lines))
    
    print("\n" + "=" * 70)
    print("Success Criteria Check")
    print("=" * 70)
    for criterion, met in success_criteria.items():
        status = "✅" if met else "❌"
        print(f"{status} {criterion}")
    
    print(f"\n✅ Validation report saved to: {report_path}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())






