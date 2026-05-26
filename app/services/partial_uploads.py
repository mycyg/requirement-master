"""Maintenance helpers for abandoned chunked uploads."""
from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

logger = logging.getLogger("yqgl.partial_uploads")

PARTIAL_UPLOAD_DIRS = (
    Path("uploads") / "_partial",
    Path("deliveries") / "_partial",
)


def cleanup_stale_partials(data_dir: Path, *, max_age_seconds: int = 24 * 60 * 60) -> int:
    cutoff = time.time() - max_age_seconds
    removed = 0

    for rel in PARTIAL_UPLOAD_DIRS:
        root = data_dir / rel
        if not root.exists():
            continue
        for child in root.iterdir():
            if not child.is_dir():
                continue
            try:
                newest_mtime = max(
                    (p.stat().st_mtime for p in child.rglob("*")),
                    default=child.stat().st_mtime,
                )
                if newest_mtime < cutoff:
                    shutil.rmtree(child, ignore_errors=True)
                    removed += 1
            except Exception:
                logger.exception("failed to inspect partial upload directory: %s", child)

    if removed:
        logger.info("removed %s stale partial upload directories", removed)
    return removed
