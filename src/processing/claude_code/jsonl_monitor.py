# Copyright © 2025 Sierra Labs LLC
# SPDX-License-Identifier: AGPL-3.0-only
# License-Filename: LICENSE

"""
JSONL File Monitor for Claude Code sessions.

Monitors JSONL files for active sessions with:
- 30-second polling interval
- Incremental file reading (offset tracking)
- Dynamic agent file detection
- Zero-impact on Claude Code performance
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Dict, Optional, Set
import redis

from .session_monitor import ClaudeCodeSessionMonitor

logger = logging.getLogger(__name__)

# Claude Code JSONL file locations
CLAUDE_PROJECTS_BASE = Path.home() / ".claude" / "projects"


class FileState:
    """Track state of a monitored JSONL file."""

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.line_offset = 0  # Number of lines already processed
        self.last_size = 0
        self.last_mtime = 0.0
        self.last_read_time = 0.0

    def has_changed(self) -> bool:
        """Check if file has changed since last read."""
        if not self.file_path.exists():
            return False

        stat = self.file_path.stat()
        return stat.st_size > self.last_size or stat.st_mtime > self.last_mtime

    def update_state(self, size: int, mtime: float):
        """Update file state after reading."""
        self.last_size = size
        self.last_mtime = mtime
        self.last_read_time = time.time()


class ClaudeCodeJSONLMonitor:
    """
    Monitor Claude Code JSONL files for active sessions.

    Design Principles:
    1. Zero impact on Claude Code (read-only, incremental reads)
    2. Track file state (offset, size, mtime) to avoid re-reading
    3. Dynamic agent file detection via toolUseResult.agentId
    4. Maintain map of session → monitored agent files
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        session_monitor: ClaudeCodeSessionMonitor,
        poll_interval: float = 30.0,
    ):
        self.redis_client = redis_client
        self.session_monitor = session_monitor
        self.poll_interval = poll_interval

        # Track file states: file_path → FileState
        self.file_states: Dict[Path, FileState] = {}

        # Track agent files per session: session_id → set of agent_ids
        self.session_agents: Dict[str, Set[str]] = {}

        # Track which sessions we're currently monitoring
        self.monitored_sessions: Set[str] = set()

        self.running = False

    async def start(self):
        """Start JSONL file monitoring."""
        self.running = True

        # Start monitoring loop
        asyncio.create_task(self._monitor_loop())

        logger.info("Claude Code JSONL monitor started")

    async def stop(self):
        """Stop JSONL file monitoring."""
        self.running = False
        logger.info("Claude Code JSONL monitor stopped")

    async def _monitor_loop(self):
        """Main monitoring loop - polls every 30 seconds."""
        while self.running:
            try:
                # Get active sessions from session monitor
                active_sessions = self.session_monitor.get_active_sessions()

                # Monitor each active session
                for session_id, session_info in active_sessions.items():
                    await self._monitor_session(session_id, session_info)

                # Clean up inactive sessions
                await self._cleanup_inactive_sessions(set(active_sessions.keys()))

                await asyncio.sleep(self.poll_interval)

            except Exception as e:
                logger.error(f"Error in JSONL monitor loop: {e}")
                await asyncio.sleep(5)

    async def _monitor_session(self, session_id: str, session_info: dict):
        """Monitor JSONL files for a specific session."""
        try:
            workspace_path = session_info.get("workspace_path", "")
            if not workspace_path:
                logger.warning(f"No workspace_path for session {session_id}")
                return

            # Find project directory
            project_dir = self._find_project_dir(workspace_path)
            if not project_dir:
                logger.warning(f"No project directory found for {workspace_path}")
                return

            # On first monitoring, read the main session file
            if session_id not in self.monitored_sessions:
                self.monitored_sessions.add(session_id)
                self.session_agents[session_id] = set()
                logger.info(f"Started monitoring session: {session_id}")

            # Monitor main session file
            session_file = project_dir / "session.jsonl"
            if session_file.exists():
                await self._monitor_file(session_file, session_id, session_info)

            # Monitor agent files
            await self._monitor_agent_files(project_dir, session_id, session_info)

        except Exception as e:
            logger.error(f"Error monitoring session {session_id}: {e}")

    def _find_project_dir(self, workspace_path: str) -> Optional[Path]:
        """
        Find Claude project directory for workspace.

        Claude creates project dirs like: ~/.claude/projects/-Users-username-path-to-workspace/
        """
        # Convert workspace path to project dir format
        # Example: /Users/bbalaran/Dev/project → -Users-bbalaran-Dev-project
        normalized = workspace_path.replace("/", "-")
        if normalized.startswith("-"):
            normalized = normalized[1:]  # Remove leading dash

        project_dir = CLAUDE_PROJECTS_BASE / f"-{normalized}"

        if project_dir.exists() and project_dir.is_dir():
            return project_dir

        # Try without leading dash
        project_dir_alt = CLAUDE_PROJECTS_BASE / normalized
        if project_dir_alt.exists() and project_dir_alt.is_dir():
            return project_dir_alt

        return None

    async def _monitor_file(
        self,
        file_path: Path,
        session_id: str,
        session_info: dict
    ):
        """Monitor a single JSONL file for changes."""
        # Get or create file state
        if file_path not in self.file_states:
            self.file_states[file_path] = FileState(file_path)

        file_state = self.file_states[file_path]

        # Check if file has changed
        if not file_state.has_changed():
            return

        try:
            # Read new lines only
            new_events = await self._read_new_lines(file_path, file_state)

            if not new_events:
                return

            logger.info(f"Read {len(new_events)} new events from {file_path.name}")

            # Process each event
            for entry_data in new_events:
                await self._process_event(entry_data, session_id, session_info)

            # Update file state
            stat = file_path.stat()
            file_state.update_state(stat.st_size, stat.st_mtime)

        except Exception as e:
            logger.error(f"Error monitoring file {file_path}: {e}")

    async def _read_new_lines(
        self,
        file_path: Path,
        file_state: FileState
    ) -> list:
        """Read only new lines from JSONL file since last read."""
        new_events = []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                # Skip already-processed lines
                for _ in range(file_state.line_offset):
                    f.readline()

                # Read new lines
                line_count = 0
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        entry = json.loads(line)
                        new_events.append(entry)
                        line_count += 1
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON in {file_path}: {e}")
                        continue

                # Update line offset
                file_state.line_offset += line_count

        except Exception as e:
            logger.error(f"Error reading {file_path}: {e}")

        return new_events

    async def _process_event(
        self,
        entry_data: dict,
        session_id: str,
        session_info: dict
    ):
        """Process a single JSONL event."""
        try:
            # Extract timestamp
            timestamp = entry_data.get("timestamp", "")
            if not timestamp:
                timestamp = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())

            # Check for new agent IDs in tool results
            await self._detect_new_agents(entry_data, session_id)

            # Build event for Redis
            event = {
                "version": "0.1.0",
                "hook_type": "JSONLTrace",
                "event_type": entry_data.get("type", "unknown"),
                "timestamp": timestamp,
                "platform": "claude_code",
                "session_id": session_id,
                "external_session_id": session_id,
                "metadata": {
                    "workspace_hash": session_info.get("workspace_hash"),
                    "source": "jsonl_monitor",
                },
                "payload": {
                    "entry_data": entry_data,
                },
            }

            # Send to Redis stream
            self.redis_client.xadd(
                "telemetry:events",
                {
                    k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                    for k, v in event.items()
                },
                maxlen=10000,
                approximate=True
            )

            logger.debug(f"Captured event: {entry_data.get('type')} (uuid: {entry_data.get('uuid')})")

        except Exception as e:
            logger.error(f"Error processing event: {e}")

    async def _detect_new_agents(self, entry_data: dict, session_id: str):
        """
        Detect new agent IDs in tool results and add agent file monitors.

        When a TOOL-USE event completes, check if toolUseResult contains agentId.
        If it's a new agent for this session, start monitoring that agent file.
        """
        # Check for ASSISTANT events with tool_use content
        if entry_data.get("type") != "ASSISTANT":
            return

        message = entry_data.get("message", {})
        if not isinstance(message, dict):
            return

        content = message.get("content", [])
        if not isinstance(content, list):
            return

        # Look for tool_use items with toolUseResult containing agentId
        for item in content:
            if not isinstance(item, dict):
                continue

            if item.get("type") != "tool_use":
                continue

            tool_use_result = item.get("toolUseResult", {})
            if not isinstance(tool_use_result, dict):
                continue

            agent_id = tool_use_result.get("agentId")
            if not agent_id:
                continue

            # Check if this is a new agent for this session
            if session_id not in self.session_agents:
                self.session_agents[session_id] = set()

            if agent_id in self.session_agents[session_id]:
                continue  # Already monitoring this agent

            # New agent detected!
            self.session_agents[session_id].add(agent_id)
            logger.info(f"Detected new agent for session {session_id}: {agent_id}")

    async def _monitor_agent_files(
        self,
        project_dir: Path,
        session_id: str,
        session_info: dict
    ):
        """Monitor all agent files for a session."""
        # Get known agent IDs for this session
        agent_ids = self.session_agents.get(session_id, set())

        for agent_id in agent_ids:
            agent_file = project_dir / f"agent-{agent_id}.jsonl"

            if not agent_file.exists():
                logger.debug(f"Agent file not found yet: {agent_file}")
                continue

            # Monitor the agent file
            await self._monitor_file(agent_file, session_id, session_info)

    async def _cleanup_inactive_sessions(self, active_session_ids: Set[str]):
        """Clean up resources for inactive sessions."""
        inactive = self.monitored_sessions - active_session_ids

        for session_id in inactive:
            # Remove from monitored sessions
            self.monitored_sessions.discard(session_id)

            # Remove agent tracking
            if session_id in self.session_agents:
                del self.session_agents[session_id]

            logger.info(f"Cleaned up inactive session: {session_id}")

        # Clean up file states for files that no longer belong to active sessions
        # (This is a bit complex, so we'll just keep them for now - they're lightweight)
