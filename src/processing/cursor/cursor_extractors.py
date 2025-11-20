# Copyright © 2025 Sierra Labs LLC
# SPDX-License-Identifier: AGPL-3.0-only
# License-Filename: LICENSE

"""
Data extractors for Cursor telemetry data.

Handles:
- Composer conversation data with nested bubbles
- Background composer data
- Agent mode session data
- AI service generations and prompts
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ComposerDataExtractor:
    """
    Extracts complete composer data including nested bubbles.
    Handles both workspace metadata and global conversation data.
    """

    def extract_composer_events(self, composer_data: dict, workspace_hash: str, external_session_id: str) -> List[dict]:
        """
        Extract all events from a composer conversation with complete hierarchy.
        Returns list of events: 1 composer event + N bubble events + M capability events.

        Handles:
        - Top-level composer metadata
        - All bubbles from conversation array
        - Nested bubbles within bubbles (if any)
        - All capabilities executed
        - Timing, metrics, and context for each level
        """
        events = []
        composer_id = composer_data.get("composerId")

        # Extract composer-level event
        composer_event = self._extract_composer_event(composer_data, workspace_hash, external_session_id)
        events.append(composer_event)

        # Extract bubble events from conversation (handles both full and header-only)
        conversation = (
            composer_data.get("conversation", []) or
            composer_data.get("fullConversationHeadersOnly", []) or
            []
        )

        for bubble_idx, bubble in enumerate(conversation):
            if not isinstance(bubble, dict):
                logger.warning(f"Invalid bubble at index {bubble_idx} in composer {composer_id}")
                continue

            bubble_event = self._extract_bubble_event(
                bubble,
                composer_id,
                workspace_hash,
                external_session_id,
                bubble_idx
            )
            events.append(bubble_event)

            # Check for nested bubbles (some bubbles may contain sub-bubbles)
            nested_bubbles = bubble.get("nestedBubbles", []) or bubble.get("subBubbles", [])
            for nested_idx, nested_bubble in enumerate(nested_bubbles):
                if isinstance(nested_bubble, dict):
                    nested_event = self._extract_bubble_event(
                        nested_bubble,
                        composer_id,
                        workspace_hash,
                        external_session_id,
                        bubble_idx,
                        parent_bubble_id=bubble.get("bubbleId"),
                        is_nested=True
                    )
                    events.append(nested_event)

        # Extract capability events if present
        capabilities = composer_data.get("capabilitiesRan", {})
        if capabilities and isinstance(capabilities, dict):
            for cap_name, cap_data in capabilities.items():
                if isinstance(cap_data, dict):
                    cap_event = self._extract_capability_event(
                        cap_name,
                        cap_data,
                        composer_id,
                        workspace_hash,
                        external_session_id
                    )
                    events.append(cap_event)

        logger.debug(
            f"Extracted {len(events)} events from composer {composer_id}: "
            f"1 composer + {len(conversation)} bubbles + {len(capabilities)} capabilities"
        )

        return events

    def _extract_composer_event(self, data: dict, workspace_hash: str, external_session_id: str) -> dict:
        """Extract composer-level fields."""
        composer_id = data.get("composerId")
        created_at = data.get("createdAt")

        # Convert timestamp to ISO format if it's in milliseconds
        timestamp = datetime.utcnow().isoformat()
        if created_at:
            try:
                timestamp = datetime.fromtimestamp(created_at / 1000).isoformat()
            except:
                pass

        return {
            "event_id": str(uuid.uuid4()),
            "event_type": "composer",
            "timestamp": timestamp,
            "external_session_id": external_session_id,
            "workspace_hash": workspace_hash,
            "storage_level": "global",
            "database_table": "cursorDiskKV",
            "item_key": f"composerData:{composer_id}",

            # Extracted fields
            "composer_id": composer_id,
            "created_at": created_at,
            "last_updated_at": data.get("lastUpdatedAt"),
            "is_agentic": data.get("isAgentic"),
            "is_archived": data.get("isArchived"),
            "has_unread_messages": data.get("hasUnreadMessages"),
            "conversation_count": len(
                data.get("conversation", []) or
                data.get("fullConversationHeadersOnly", [])
            ),
            "lines_added": data.get("totalLinesAdded"),
            "lines_removed": data.get("totalLinesRemoved"),

            # Full data
            "full_data": data,
        }

    def _extract_bubble_event(
        self,
        bubble: dict,
        composer_id: str,
        workspace_hash: str,
        external_session_id: str,
        bubble_idx: int = 0,
        parent_bubble_id: Optional[str] = None,
        is_nested: bool = False
    ) -> dict:
        """
        Extract data from a single bubble (including nested bubbles).

        Args:
            bubble: Bubble data dictionary
            composer_id: Parent composer ID
            workspace_hash: Workspace hash
            external_session_id: Session ID
            bubble_idx: Index in conversation array
            parent_bubble_id: ID of parent bubble (for nested bubbles)
            is_nested: Whether this is a nested bubble
        """
        timing_info = bubble.get("timingInfo", {})
        bubble_id = bubble.get("bubbleId")

        # Determine timestamp (try multiple fields)
        client_start = timing_info.get("clientStartTime")
        created_at = bubble.get("createdAt")
        timestamp = datetime.utcnow().isoformat()

        if client_start:
            try:
                timestamp = datetime.fromtimestamp(client_start / 1000).isoformat()
            except:
                pass
        elif created_at:
            try:
                timestamp = datetime.fromtimestamp(created_at / 1000).isoformat()
            except:
                pass

        event_type = "bubble" if not is_nested else "nested_bubble"

        return {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "timestamp": timestamp,
            "external_session_id": external_session_id,
            "workspace_hash": workspace_hash,
            "storage_level": "global",
            "database_table": "cursorDiskKV",
            "item_key": f"composerData:{composer_id}",

            # Hierarchy fields
            "composer_id": composer_id,
            "bubble_id": bubble_id,
            "server_bubble_id": bubble.get("serverBubbleId"),
            "parent_bubble_id": parent_bubble_id,  # For nested bubbles
            "bubble_index": bubble_idx,
            "is_nested": is_nested,

            # Message fields
            "message_type": bubble.get("type"),  # 1=user, 2=ai
            "text_description": bubble.get("text"),
            "raw_text": bubble.get("rawText"),
            "rich_text": json.dumps(bubble.get("richText")) if bubble.get("richText") else None,

            # Capability execution
            "capabilities_ran": json.dumps(bubble.get("capabilitiesRan")) if bubble.get("capabilitiesRan") else None,
            "capability_statuses": json.dumps(bubble.get("capabilityStatuses")) if bubble.get("capabilityStatuses") else None,

            # Metrics
            "token_count_up_until_here": bubble.get("tokenCountUpUntilHere"),
            "lines_added": bubble.get("linesAdded"),
            "lines_removed": bubble.get("linesRemoved"),

            # Timing
            "client_start_time": timing_info.get("clientStartTime"),
            "client_end_time": timing_info.get("clientEndTime"),
            "created_at": bubble.get("createdAt"),

            # Context
            "relevant_files": json.dumps(bubble.get("relevantFiles")) if bubble.get("relevantFiles") else None,
            "selections": json.dumps(bubble.get("selections")) if bubble.get("selections") else None,
            "codeblock_preview": bubble.get("codeblockPreview"),

            # Full data
            "full_data": bubble,
        }

    def _extract_capability_event(
        self,
        cap_name: str,
        cap_data: dict,
        composer_id: str,
        workspace_hash: str,
        external_session_id: str
    ) -> dict:
        """Extract capability execution data."""
        timestamp = datetime.utcnow().isoformat()

        return {
            "event_id": str(uuid.uuid4()),
            "event_type": "capability",
            "timestamp": timestamp,
            "external_session_id": external_session_id,
            "workspace_hash": workspace_hash,
            "storage_level": "global",
            "database_table": "cursorDiskKV",
            "item_key": f"composerData:{composer_id}:capability:{cap_name}",

            # Capability fields
            "composer_id": composer_id,
            "capability_name": cap_name,
            "capability_type": cap_data.get("type"),
            "capability_status": cap_data.get("status"),
            "duration_ms": cap_data.get("durationMs"),

            # Full data
            "full_data": cap_data,
        }


class BackgroundComposerExtractor:
    """
    Extracts background composer persistent data.
    Background composers run without user interaction.
    """

    def extract_background_composer(self, data: dict, workspace_hash: str, external_session_id: str) -> dict:
        """Extract background composer persistent data."""
        timestamp = datetime.utcnow().isoformat()

        last_active = data.get("lastActiveTimestamp")
        if last_active:
            try:
                timestamp = datetime.fromtimestamp(last_active / 1000).isoformat()
            except:
                pass

        return {
            "event_id": str(uuid.uuid4()),
            "event_type": "background_composer",
            "timestamp": timestamp,
            "external_session_id": external_session_id,
            "workspace_hash": workspace_hash,
            "storage_level": "workspace",
            "database_table": "ItemTable",
            "item_key": "workbench.backgroundComposer.workspacePersistentData",

            # Background composer fields
            "last_active_timestamp": last_active,
            "state": data.get("state"),

            # Full data
            "full_data": data,
        }


class AgentModeExtractor:
    """
    Extracts agent mode session data.
    Agent mode allows Cursor to perform autonomous actions.
    """

    def extract_agent_mode(self, exit_info: dict, workspace_hash: str, external_session_id: str) -> dict:
        """Extract agent mode exit information."""
        timestamp = datetime.utcnow().isoformat()

        exit_ts = exit_info.get("timestamp")
        if exit_ts:
            try:
                timestamp = datetime.fromtimestamp(exit_ts / 1000).isoformat()
            except:
                pass

        return {
            "event_id": str(uuid.uuid4()),
            "event_type": "agent_mode",
            "timestamp": timestamp,
            "external_session_id": external_session_id,
            "workspace_hash": workspace_hash,
            "storage_level": "workspace",
            "database_table": "ItemTable",
            "item_key": "workbench.agentMode.exitInfo",

            # Agent mode fields
            "agent_session_id": exit_info.get("sessionId"),
            "exit_reason": exit_info.get("reason"),
            "exit_timestamp": exit_ts,
            "duration_ms": exit_info.get("duration"),
            "actions_performed": json.dumps(exit_info.get("actionsPerformed", [])),
            "files_modified": json.dumps(exit_info.get("filesModified", [])),
            "commands_executed": json.dumps(exit_info.get("commandsExecuted", [])),
            "success": exit_info.get("success", False),

            # Full data
            "full_data": exit_info,
        }


class GenerationExtractor:
    """
    Extracts AI service generation data.
    """

    def extract_generation(self, gen_data: dict, workspace_hash: str, external_session_id: str) -> dict:
        """Extract generation data."""
        timestamp = datetime.utcnow().isoformat()

        unix_ms = gen_data.get("unixMs")
        if unix_ms:
            try:
                timestamp = datetime.fromtimestamp(unix_ms / 1000).isoformat()
            except:
                pass

        return {
            "event_id": str(uuid.uuid4()),
            "event_type": "generation",
            "timestamp": timestamp,
            "external_session_id": external_session_id,
            "workspace_hash": workspace_hash,
            "storage_level": "workspace",
            "database_table": "ItemTable",
            "item_key": "aiService.generations",

            # Generation fields
            "generation_uuid": gen_data.get("generationUUID"),
            "generation_type": gen_data.get("type"),
            "text_description": gen_data.get("textDescription"),
            "unix_ms": unix_ms,
            "completed_at": gen_data.get("completedAt"),

            # Full data
            "full_data": gen_data,
        }


class PromptExtractor:
    """
    Extracts AI service prompt data.
    """

    def extract_prompt(self, prompt_data: dict, workspace_hash: str, external_session_id: str) -> dict:
        """Extract prompt data."""
        timestamp = datetime.utcnow().isoformat()

        unix_ms = prompt_data.get("unixMs")
        if unix_ms:
            try:
                timestamp = datetime.fromtimestamp(unix_ms / 1000).isoformat()
            except:
                pass

        return {
            "event_id": str(uuid.uuid4()),
            "event_type": "prompt",
            "timestamp": timestamp,
            "external_session_id": external_session_id,
            "workspace_hash": workspace_hash,
            "storage_level": "workspace",
            "database_table": "ItemTable",
            "item_key": "aiService.prompts",

            # Prompt fields
            "command_type": prompt_data.get("commandType"),
            "text_description": prompt_data.get("textDescription"),
            "unix_ms": unix_ms,

            # Full data
            "full_data": prompt_data,
        }
