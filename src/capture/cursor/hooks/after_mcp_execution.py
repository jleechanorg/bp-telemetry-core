#!/usr/bin/env python3
# Copyright © 2025 Sierra Labs LLC
# SPDX-License-Identifier: AGPL-3.0-only
# License-Filename: LICENSE

"""
Cursor Hook: afterMCPExecution

Captures event after MCP tool execution completes.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from hook_base import CursorHookBase, str_to_bool
from shared.event_schema import HookType, EventType


class AfterMCPExecutionHook(CursorHookBase):
    """Hook for after MCP tool execution."""

    def __init__(self):
        super().__init__(HookType.AFTER_MCP_EXECUTION)

    def execute(self) -> int:
        """Execute hook logic."""
        args = self.parse_args({
            'tool_name': {'type': str, 'help': 'MCP tool name'},
            'success': {'type': str, 'help': 'Whether execution succeeded (true/false)'},
            'duration_ms': {'type': int, 'help': 'Execution duration in milliseconds'},
            'output_size': {'type': int, 'help': 'Output size in bytes', 'default': 0},
            'error_message': {'type': str, 'help': 'Error message if failed', 'default': None},
        })

        # Properly convert success string to boolean
        success = str_to_bool(args.success) if args.success else False

        payload = {
            'tool_name': args.tool_name,
            'success': success,
            'duration_ms': args.duration_ms,
            'output_size': args.output_size,
        }

        if args.error_message:
            payload['error_message'] = args.error_message

        event = self.build_event(
            event_type=EventType.MCP_EXECUTION,
            payload=payload
        )

        self.enqueue_event(event)
        return 0


def main():
    """Main entry point."""
    hook = AfterMCPExecutionHook()
    sys.exit(hook.run())


if __name__ == '__main__':
    main()
