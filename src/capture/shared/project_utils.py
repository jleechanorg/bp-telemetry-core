"""Shared helpers for deriving human-readable project identifiers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def derive_project_name(
    workspace_path: Optional[str],
    fallback_path: Optional[str] = None,
    *,
    max_length: int = 80,
) -> Optional[str]:
    """
    Derive a human-readable project name from a workspace path.

    Args:
        workspace_path: Full path to the workspace root provided by the caller.
        fallback_path: Optional secondary path (e.g., current working directory).
        max_length: Optional maximum length for the returned project name.

    Returns:
        A sanitized project name or None if it cannot be determined.
    """

    candidate = workspace_path or fallback_path
    if not candidate:
        return None

    # Remove trailing path separators to avoid empty stem/name results.
    candidate = candidate.rstrip("/\\")
    if not candidate:
        return None

    # Use pathlib for cross-platform path parsing.
    name = Path(candidate).name

    # As a fallback (e.g., if path ends with drive letter), fall back to basename.
    if not name:
        name = os.path.basename(candidate)

    # Final guard if basename is still empty (unlikely but defensive).
    if not name:
        return None

    name = name.strip()
    if not name:
        return None

    if len(name) > max_length:
        return f"{name[: max_length - 3]}..."

    return name


__all__ = ["derive_project_name"]


