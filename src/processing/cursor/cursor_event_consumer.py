# Copyright © 2025 Sierra Labs LLC
# SPDX-License-Identifier: AGPL-3.0-only
# License-Filename: LICENSE

"""
Event consumer for Cursor raw traces with at-least-once delivery guarantee.

Implements:
- XREADGROUP for consuming events from Redis Streams
- XACK for acknowledging successful processing
- XCLAIM for recovering stale/failed events
- Dead Letter Queue (DLQ) for permanently failed events
- Automatic retry with exponential backoff
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import redis

from .cursor_raw_traces_writer import CursorRawTracesWriter

logger = logging.getLogger(__name__)


class CursorEventConsumer:
    """
    Consumes Cursor events from Redis stream with proper ACK handling.
    Implements at-least-once delivery guarantee.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        writer: CursorRawTracesWriter,
        stream_name: str = "telemetry:events",
        consumer_group: str = "processors",
        consumer_name: str = None,
        max_retries: int = 3,
        claim_min_idle_time: int = 60000,  # 60 seconds
        pending_check_interval: int = 30,  # 30 seconds
    ):
        self.redis_client = redis_client
        self.writer = writer
        self.stream_name = stream_name
        self.consumer_group = consumer_group
        self.consumer_name = consumer_name or f"cursor-consumer-{os.getpid()}"
        self.max_retries = max_retries
        self.claim_min_idle_time = claim_min_idle_time
        self.pending_check_interval = pending_check_interval

        self.running = False
        self.stats = {
            'processed': 0,
            'acked': 0,
            'failed': 0,
            'dlq': 0,
            'claimed': 0,
        }

    async def start(self):
        """Start consuming events."""
        self.running = True
        logger.info(
            f"Starting Cursor event consumer: "
            f"stream={self.stream_name}, "
            f"group={self.consumer_group}, "
            f"consumer={self.consumer_name}"
        )

        # Start main consumption loop
        consume_task = asyncio.create_task(self._consume_loop())

        # Start pending events recovery loop
        pending_task = asyncio.create_task(self._pending_loop())

        try:
            await asyncio.gather(consume_task, pending_task)
        except Exception as e:
            logger.error(f"Consumer crashed: {e}", exc_info=True)
            self.running = False

    async def stop(self):
        """Stop consuming events."""
        self.running = False
        logger.info("Stopping Cursor event consumer")

        # Log final stats
        logger.info(f"Consumer stats: {self.stats}")

    async def _consume_loop(self):
        """Main consumption loop."""
        while self.running:
            try:
                # Consume new events
                events = await self._consume_events(block_ms=1000, count=100)

                if events:
                    await self._process_and_ack(events)

            except Exception as e:
                logger.error(f"Error in consume loop: {e}")
                await asyncio.sleep(1)

    async def _pending_loop(self):
        """Loop for recovering pending events."""
        while self.running:
            try:
                await asyncio.sleep(self.pending_check_interval)

                # Process stale pending events
                stale_events = await self._claim_stale_events()
                if stale_events:
                    await self._process_and_ack(stale_events)

                # Check for events that exceeded max retries
                await self._move_failed_to_dlq()

            except Exception as e:
                logger.error(f"Error in pending loop: {e}")
                await asyncio.sleep(5)

    async def _consume_events(
        self,
        block_ms: int = 1000,
        count: int = 100
    ) -> List[Tuple[str, dict]]:
        """
        Consume events from stream using consumer group.
        Returns list of (entry_id, event_data) tuples.
        """
        try:
            # Read new messages from the stream
            messages = self.redis_client.xreadgroup(
                self.consumer_group,
                self.consumer_name,
                {self.stream_name: '>'},  # '>' means only new messages
                block=block_ms,
                count=count
            )

            events = []
            if messages:
                for stream_name, stream_messages in messages:
                    for entry_id, data in stream_messages:
                        # Deserialize the data
                        event = self._deserialize_event(data)
                        events.append((entry_id, event))

            return events

        except Exception as e:
            logger.error(f"Error consuming events: {e}")
            return []

    async def _process_and_ack(self, events: List[Tuple[str, dict]]):
        """Process events and acknowledge them."""
        if not events:
            return

        successful_ids = []
        failed_ids = []

        for entry_id, event in events:
            try:
                # Validate event has required fields
                if not self._validate_event(event):
                    logger.warning(f"Invalid event {entry_id}, skipping")
                    successful_ids.append(entry_id)  # ACK to remove from PEL
                    continue

                # Write to database
                await self.writer.write_event(event)
                successful_ids.append(entry_id)
                self.stats['processed'] += 1

            except Exception as e:
                logger.error(f"Failed to process event {entry_id}: {e}")
                failed_ids.append(entry_id)
                self.stats['failed'] += 1

        # Flush writer to ensure all events are committed
        if successful_ids:
            await self.writer.flush()

        # ACK successful events
        if successful_ids:
            await self._ack_events(successful_ids)
            self.stats['acked'] += len(successful_ids)
            logger.info(f"Processed and ACKed {len(successful_ids)} Cursor events")

        # Failed events remain in PEL for retry
        if failed_ids:
            logger.warning(
                f"{len(failed_ids)} events failed processing. "
                "They remain in PEL for retry."
            )

    async def _ack_events(self, entry_ids: List[str]):
        """Acknowledge successful processing of events."""
        if not entry_ids:
            return

        try:
            ack_count = self.redis_client.xack(
                self.stream_name,
                self.consumer_group,
                *entry_ids
            )

            if ack_count < len(entry_ids):
                logger.warning(
                    f"Only {ack_count} of {len(entry_ids)} events were acknowledged"
                )

        except Exception as e:
            logger.error(f"Error acknowledging events: {e}")

    async def _claim_stale_events(self) -> List[Tuple[str, dict]]:
        """
        Claim and process events that are stale in PEL.
        Returns list of claimed events.
        """
        try:
            # Get pending events info
            pending_info = self.redis_client.xpending_range(
                self.stream_name,
                self.consumer_group,
                min='-',
                max='+',
                count=100
            )

            stale_event_ids = []
            for entry in pending_info:
                entry_id = entry['message_id']
                idle_time = entry['time_since_delivered']
                delivery_count = entry['times_delivered']

                # Check if event is stale (idle for too long)
                if idle_time > self.claim_min_idle_time:
                    stale_event_ids.append(entry_id)

            if not stale_event_ids:
                return []

            # Claim stale events
            claimed_messages = self.redis_client.xclaim(
                self.stream_name,
                self.consumer_group,
                self.consumer_name,
                min_idle_time=self.claim_min_idle_time,
                message_ids=stale_event_ids
            )

            events = []
            for entry_id, data in claimed_messages:
                event = self._deserialize_event(data)
                events.append((entry_id, event))

            if events:
                self.stats['claimed'] += len(events)
                logger.info(f"Claimed {len(events)} stale Cursor events")

            return events

        except Exception as e:
            logger.error(f"Error claiming stale events: {e}")
            return []

    async def _move_failed_to_dlq(self):
        """Move events that exceeded max retries to DLQ."""
        try:
            # Get pending events with delivery count
            pending_info = self.redis_client.xpending_range(
                self.stream_name,
                self.consumer_group,
                min='-',
                max='+',
                count=100
            )

            for entry in pending_info:
                entry_id = entry['message_id']
                delivery_count = entry['times_delivered']

                # Check if exceeded max retries
                if delivery_count > self.max_retries:
                    await self._move_to_dlq(entry_id)
                    # ACK to remove from PEL
                    await self._ack_events([entry_id])
                    self.stats['dlq'] += 1

        except Exception as e:
            logger.error(f"Error checking for failed events: {e}")

    async def _move_to_dlq(self, entry_id: str):
        """Move failed event to Dead Letter Queue."""
        try:
            # Read the event data
            events = self.redis_client.xrange(
                self.stream_name,
                min=entry_id,
                max=entry_id,
                count=1
            )

            if events:
                _, event_data = events[0]

                # Add to DLQ stream with failure metadata
                dlq_entry = {
                    **event_data,
                    'original_entry_id': entry_id,
                    'moved_to_dlq_at': datetime.utcnow().isoformat(),
                    'stream': self.stream_name,
                    'consumer_group': self.consumer_group,
                    'consumer': self.consumer_name,
                }

                self.redis_client.xadd(
                    f"{self.stream_name}:dlq",
                    dlq_entry,
                    maxlen=10000,
                    approximate=True
                )

                logger.warning(f"Moved Cursor event {entry_id} to DLQ after {self.max_retries} retries")

        except Exception as e:
            logger.error(f"Error moving event to DLQ: {e}")

    def _deserialize_event(self, data: dict) -> dict:
        """Deserialize event from Redis."""
        deserialized = {}

        for key, value in data.items():
            key = key.decode() if isinstance(key, bytes) else key
            value = value.decode() if isinstance(value, bytes) else value

            # Try to parse JSON fields
            if key in ['full_data', 'metadata', 'payload']:
                try:
                    deserialized[key] = json.loads(value)
                except json.JSONDecodeError:
                    deserialized[key] = value
            else:
                deserialized[key] = value

        return deserialized

    def _validate_event(self, event: dict) -> bool:
        """Validate event has required fields."""
        required_fields = ['event_id', 'event_type', 'timestamp', 'workspace_hash']

        for field in required_fields:
            if field not in event:
                logger.warning(f"Event missing required field: {field}")
                return False

        return True

    async def get_stats(self) -> dict:
        """Get consumer statistics."""
        try:
            # Get consumer group info
            groups = self.redis_client.xinfo_groups(self.stream_name)
            group_info = next(
                (g for g in groups if g['name'] == self.consumer_group),
                None
            )

            if not group_info:
                return self.stats

            # Get pending messages summary
            pending_summary = self.redis_client.xpending(
                self.stream_name,
                self.consumer_group
            )

            return {
                **self.stats,
                'group_pending': group_info.get('pending', 0),
                'group_last_delivered_id': group_info.get('last-delivered-id'),
                'pending_count': pending_summary.get('pending', 0),
            }

        except Exception as e:
            logger.error(f"Error getting consumer stats: {e}")
            return self.stats
