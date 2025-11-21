# Copyright © 2025 Sierra Labs LLC
# SPDX-License-Identifier: AGPL-3.0-only
# License-Filename: LICENSE

"""
Claude Code platform-specific processing.

This module contains all Claude Code specific telemetry processing:
- Event consumption from Redis Streams
- Raw traces writing to claude_raw_traces table
- JSONL file monitoring
"""

from .event_consumer import ClaudeEventConsumer

__all__ = ["ClaudeEventConsumer"]
