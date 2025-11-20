# Copyright © 2025 Sierra Labs LLC
# SPDX-License-Identifier: AGPL-3.0-only
# License-Filename: LICENSE

"""
Supporting utilities for UnifiedCursorMonitor.

Includes:
- FileWatcher: Hybrid file watching with filesystem events + polling fallback
- IncrementalSync: Track last processed state for incremental updates
- SmartCache: TTL-based caching to minimize database reads
"""

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class FileWatcher:
    """
    Watches database files for changes using filesystem events with fallback.

    Strategy:
    1. Primary: watchdog library for filesystem events
    2. Fallback: stat-based polling every 60 seconds
    3. Debounce: 10-second delay after change detection
    """

    def __init__(self, db_path: Path, callback: Callable):
        self.db_path = db_path
        self.callback = callback
        self.last_modified = None
        self.last_size = None
        self.watchdog_observer = None
        self.active = True
        self.debounce_task = None
        self.debounce_delay = 10.0  # seconds

    async def start_watching(self):
        """Start file watching with fallback."""
        # Record initial state
        try:
            stat = self.db_path.stat()
            self.last_modified = stat.st_mtime
            self.last_size = stat.st_size
        except FileNotFoundError:
            logger.warning(f"Database not found: {self.db_path}")
            return

        # Try watchdog first
        if await self._try_watchdog():
            logger.info(f"Using watchdog for {self.db_path}")
        else:
            logger.info(f"Watchdog unavailable, using polling for {self.db_path}")

    async def _try_watchdog(self) -> bool:
        """Try to use watchdog for filesystem events."""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class DBChangeHandler(FileSystemEventHandler):
                def __init__(self, watcher):
                    self.watcher = watcher

                def on_modified(self, event):
                    if event.src_path == str(self.watcher.db_path):
                        asyncio.create_task(
                            self.watcher._handle_change_with_debounce()
                        )

            self.watchdog_observer = Observer()
            self.watchdog_observer.schedule(
                DBChangeHandler(self),
                str(self.db_path.parent),
                recursive=False
            )
            self.watchdog_observer.start()
            return True

        except Exception as e:
            logger.warning(f"Watchdog failed: {e}")
            return False

    async def _handle_change_with_debounce(self):
        """Handle change with debouncing."""
        # Cancel existing debounce task
        if self.debounce_task:
            self.debounce_task.cancel()

        # Schedule new callback after delay
        self.debounce_task = asyncio.create_task(
            self._debounced_callback()
        )

    async def _debounced_callback(self):
        """Execute callback after debounce delay."""
        await asyncio.sleep(self.debounce_delay)
        await self.callback()

    async def check_for_changes(self) -> bool:
        """Polling fallback: check if file changed."""
        try:
            stat = self.db_path.stat()
            changed = (
                stat.st_mtime != self.last_modified or
                stat.st_size != self.last_size
            )
            if changed:
                self.last_modified = stat.st_mtime
                self.last_size = stat.st_size
                return True
        except FileNotFoundError:
            return False
        return False

    async def stop(self):
        """Stop watching and cleanup."""
        self.active = False

        if self.debounce_task:
            self.debounce_task.cancel()

        if self.watchdog_observer:
            self.watchdog_observer.stop()
            self.watchdog_observer.join(timeout=1)


class IncrementalSync:
    """
    Tracks last processed state for incremental updates.
    Ensures we only process new or changed data.
    """

    def __init__(self):
        self.last_timestamps = {}  # (storage_level, workspace, key) -> timestamp_ms
        self.last_hashes = {}  # (storage_level, workspace, key) -> content_hash
        self.last_counts = {}  # (storage_level, workspace, key) -> item_count

    def should_process(
        self,
        storage_level: str,
        workspace_hash: str,
        key: str,
        data: Any
    ) -> bool:
        """
        Determine if data should be processed.
        Returns True if data is new or changed.
        """
        cache_key = (storage_level, workspace_hash, key)

        # For timestamped array data (generations, prompts)
        if isinstance(data, list) and key in (
            "aiService.generations",
            "aiService.prompts"
        ):
            # Check if we have new items based on timestamp
            last_ts = self.last_timestamps.get(cache_key, 0)

            new_items = []
            max_ts = last_ts

            for item in data:
                if isinstance(item, dict):
                    item_ts = item.get("unixMs", 0)
                    if item_ts > last_ts:
                        new_items.append(item)
                        max_ts = max(max_ts, item_ts)

            if new_items:
                self.last_timestamps[cache_key] = max_ts
                return True
            return False

        # For non-timestamped data, use content hash
        content_hash = self._compute_hash(data)

        if self.last_hashes.get(cache_key) != content_hash:
            self.last_hashes[cache_key] = content_hash
            return True

        return False

    def get_new_items(
        self,
        storage_level: str,
        workspace_hash: str,
        key: str,
        data: List[dict]
    ) -> List[dict]:
        """Get only new items from timestamped array."""
        cache_key = (storage_level, workspace_hash, key)
        last_ts = self.last_timestamps.get(cache_key, 0)

        new_items = []
        max_ts = last_ts

        for item in data:
            if isinstance(item, dict):
                item_ts = item.get("unixMs", 0)
                if item_ts > last_ts:
                    new_items.append(item)
                    max_ts = max(max_ts, item_ts)

        if new_items:
            self.last_timestamps[cache_key] = max_ts

        return new_items

    def _compute_hash(self, data: Any) -> str:
        """Compute hash of data for change detection."""
        json_str = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(json_str.encode()).hexdigest()

    def clear_workspace(self, workspace_hash: str):
        """Clear state for a workspace (on session end)."""
        keys_to_remove = [
            key for key in self.last_timestamps.keys()
            if key[1] == workspace_hash
        ]
        for key in keys_to_remove:
            del self.last_timestamps[key]

        keys_to_remove = [
            key for key in self.last_hashes.keys()
            if key[1] == workspace_hash
        ]
        for key in keys_to_remove:
            del self.last_hashes[key]


class SmartCache:
    """
    Intelligent caching to minimize database reads and API calls.
    """

    def __init__(self, ttl_seconds: int = 300):
        self.cache = {}  # key -> (value, timestamp)
        self.ttl = ttl_seconds
        self.lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        """Get from cache if not expired."""
        async with self.lock:
            if key in self.cache:
                value, timestamp = self.cache[key]
                if time.time() - timestamp < self.ttl:
                    return value
                else:
                    del self.cache[key]
        return None

    async def set(self, key: str, value: Any):
        """Set cache value with TTL."""
        async with self.lock:
            self.cache[key] = (value, time.time())

    async def get_or_fetch(
        self,
        key: str,
        fetcher: Callable,
        force_refresh: bool = False
    ) -> Any:
        """Get from cache or fetch if stale."""
        if not force_refresh:
            cached = await self.get(key)
            if cached is not None:
                return cached

        # Fetch fresh data
        value = await fetcher()
        await self.set(key, value)
        return value

    def invalidate(self, pattern: str = None):
        """
        Invalidate cache entries.
        If pattern provided, invalidates matching keys (glob pattern).
        """
        if pattern:
            import fnmatch
            keys_to_remove = [
                k for k in self.cache.keys()
                if fnmatch.fnmatch(k, pattern)
            ]
            for key in keys_to_remove:
                del self.cache[key]
        else:
            self.cache.clear()

    async def cleanup_expired(self):
        """Remove expired entries."""
        now = time.time()
        async with self.lock:
            expired = [
                key for key, (_, ts) in self.cache.items()
                if now - ts >= self.ttl
            ]
            for key in expired:
                del self.cache[key]
