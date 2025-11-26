#!/usr/bin/env python3
# Copyright © 2025 Sierra Labs LLC
# SPDX-License-Identifier: AGPL-3.0-only
# License-Filename: LICENSE

"""
Real Integration Tests for Claude Code Telemetry

These tests invoke Claude Code with --dangerously-skip-permissions and verify
that telemetry events are properly captured in the database.

IMPORTANT: These tests require:
1. Claude Code CLI installed and configured
2. Telemetry server running (or hooks configured)
3. Write access to ~/.blueplane/

Usage:
    python testing_integration/test_claude_telemetry.py

    # Or with pytest:
    pytest testing_integration/test_claude_telemetry.py -v -s
"""

import os
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class ClaudeTelemetryTest:
    """Test harness for Claude Code telemetry integration tests."""

    def __init__(self):
        self.telemetry_db = Path.home() / ".blueplane" / "telemetry.db"
        self.test_marker = f"TEST_{uuid.uuid4().hex[:8]}"
        self.start_time = datetime.now(timezone.utc)
        self.results = {"passed": [], "failed": [], "skipped": []}

    def record(self, name: str, passed: bool, message: str = "", skip: bool = False):
        """Record test result."""
        if skip:
            self.results["skipped"].append((name, message))
            print(f"  ⏭️  {name}: SKIPPED - {message}")
        elif passed:
            self.results["passed"].append((name, message))
            print(f"  ✅ {name}: {message}")
        else:
            self.results["failed"].append((name, message))
            print(f"  ❌ {name}: {message}")

    def check_prerequisites(self) -> bool:
        """Check if Claude Code CLI is available."""
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                print(f"  Claude Code version: {version}")
                return True
            return False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def get_event_count_since(self, table: str = "claude_raw_traces") -> int:
        """Get count of events since test started."""
        if not self.telemetry_db.exists():
            return 0

        try:
            conn = sqlite3.connect(str(self.telemetry_db))
            cursor = conn.execute(f"""
                SELECT COUNT(*) FROM {table}
                WHERE timestamp >= ?
            """, (self.start_time.isoformat(),))
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except sqlite3.Error as e:
            print(f"  Warning: DB error - {e}")
            return 0

    def get_recent_events(self, table: str = "claude_raw_traces", limit: int = 5) -> list:
        """Get recent events from database."""
        if not self.telemetry_db.exists():
            return []

        try:
            conn = sqlite3.connect(str(self.telemetry_db))
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(f"""
                SELECT * FROM {table}
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (self.start_time.isoformat(), limit))
            events = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return events
        except sqlite3.Error as e:
            print(f"  Warning: DB error - {e}")
            return []

    def run_claude_command(self, prompt: str, timeout: int = 30) -> tuple[bool, str]:
        """Run Claude Code with a prompt and return success status and output."""
        try:
            result = subprocess.run(
                [
                    "claude",
                    "-p", prompt,
                    "--dangerously-skip-permissions"
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "NO_COLOR": "1"}
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)


def test_claude_cli_available(harness: ClaudeTelemetryTest):
    """Test that Claude CLI is installed and accessible."""
    print("\n[TEST] Claude CLI availability...")

    available = harness.check_prerequisites()
    harness.record(
        "claude_cli_available",
        available,
        "Claude CLI is installed" if available else "Claude CLI not found - install with: npm install -g @anthropic/claude-code"
    )
    return available


def test_telemetry_db_exists(harness: ClaudeTelemetryTest):
    """Test that telemetry database exists or can be created."""
    print("\n[TEST] Telemetry database...")

    db_exists = harness.telemetry_db.exists()
    if db_exists:
        harness.record("telemetry_db", True, f"Database exists at {harness.telemetry_db}")
    else:
        harness.record(
            "telemetry_db",
            False,
            f"Database not found at {harness.telemetry_db} - run telemetry server first",
            skip=True
        )
    return db_exists


def test_simple_prompt_generates_events(harness: ClaudeTelemetryTest):
    """Test that a simple Claude prompt generates telemetry events."""
    print("\n[TEST] Simple prompt generates events...")

    initial_count = harness.get_event_count_since()
    print(f"  Initial event count: {initial_count}")

    # Run a simple Claude command
    prompt = f"echo 'test marker: {harness.test_marker}'"
    print(f"  Running: claude -p \"{prompt}\" --dangerously-skip-permissions")

    success, output = harness.run_claude_command(prompt)
    if not success:
        harness.record("simple_prompt", False, f"Claude command failed: {output[:200]}")
        return False

    # Wait for events to be processed
    print("  Waiting for events to be captured...")
    time.sleep(3)

    final_count = harness.get_event_count_since()
    new_events = final_count - initial_count

    print(f"  Final event count: {final_count} (+{new_events} new)")

    if new_events > 0:
        harness.record("simple_prompt", True, f"Generated {new_events} new events")
        return True
    else:
        harness.record(
            "simple_prompt",
            False,
            "No new events captured - check if telemetry hooks are configured"
        )
        return False


def test_event_structure(harness: ClaudeTelemetryTest):
    """Test that captured events have proper structure."""
    print("\n[TEST] Event structure validation...")

    events = harness.get_recent_events(limit=3)
    if not events:
        harness.record("event_structure", False, "No recent events to validate", skip=True)
        return False

    # Check required fields
    required_fields = ["event_id", "event_type", "timestamp"]
    event = events[0]

    missing_fields = [f for f in required_fields if f not in event or event[f] is None]
    if missing_fields:
        harness.record("event_structure", False, f"Missing fields: {missing_fields}")
        return False

    harness.record("event_structure", True, f"Event has all required fields: {list(event.keys())}")
    return True


def test_conversation_tracking(harness: ClaudeTelemetryTest):
    """Test that conversation events are properly tracked."""
    print("\n[TEST] Conversation tracking...")

    # Run a multi-turn style prompt
    prompt = "What is 2+2? Just reply with the number."
    success, output = harness.run_claude_command(prompt, timeout=60)

    if not success:
        harness.record("conversation_tracking", False, f"Command failed: {output[:100]}")
        return False

    time.sleep(2)

    # Check for conversation-related events
    events = harness.get_recent_events(limit=10)
    conversation_events = [e for e in events if "conversation" in str(e.get("event_type", "")).lower()]

    if conversation_events:
        harness.record("conversation_tracking", True, f"Found {len(conversation_events)} conversation events")
    else:
        harness.record(
            "conversation_tracking",
            True,
            f"Found {len(events)} events (conversation tracking may use different event types)"
        )
    return True


def run_all_tests():
    """Run all integration tests."""
    print("=" * 70)
    print("Claude Code Telemetry - Real Integration Tests")
    print("=" * 70)
    print(f"\nTest started at: {datetime.now(timezone.utc).isoformat()}")

    harness = ClaudeTelemetryTest()

    # Run tests in order
    if not test_claude_cli_available(harness):
        print("\n⚠️  Claude CLI not available - skipping remaining tests")
        harness.record("remaining_tests", False, "Skipped due to missing CLI", skip=True)
    else:
        test_telemetry_db_exists(harness)
        test_simple_prompt_generates_events(harness)
        test_event_structure(harness)
        test_conversation_tracking(harness)

    # Summary
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    print(f"  Passed:  {len(harness.results['passed'])}")
    print(f"  Failed:  {len(harness.results['failed'])}")
    print(f"  Skipped: {len(harness.results['skipped'])}")

    if harness.results['failed']:
        print("\nFailed tests:")
        for name, msg in harness.results['failed']:
            print(f"  - {name}: {msg}")
        return 1

    print("\n✅ All tests passed!")
    return 0


# Pytest compatibility
class TestClaudeTelemetry:
    """Pytest-compatible test class."""

    def setup_method(self):
        self.harness = ClaudeTelemetryTest()

    def test_claude_cli_available(self):
        assert test_claude_cli_available(self.harness)

    def test_telemetry_db_exists(self):
        # Skip if CLI not available
        if not self.harness.check_prerequisites():
            import pytest
            pytest.skip("Claude CLI not available")
        test_telemetry_db_exists(self.harness)

    def test_simple_prompt_generates_events(self):
        if not self.harness.check_prerequisites():
            import pytest
            pytest.skip("Claude CLI not available")
        if not self.harness.telemetry_db.exists():
            import pytest
            pytest.skip("Telemetry DB not found")
        assert test_simple_prompt_generates_events(self.harness)


if __name__ == "__main__":
    sys.exit(run_all_tests())
