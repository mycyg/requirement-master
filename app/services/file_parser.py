"""Parse uploaded files to text via markitdown.

Returns (preview_text, full_text). full_text may be very long; preview_text is truncated
for storage in DB / for LLM context.
"""
from __future__ import annotations

from pathlib import Path

PREVIEW_CHARS = 6000


def parse_file(path: Path) -> tuple[str, str]:
    """Returns (preview, full). Falls back to empty on unsupported types or errors."""
    try:
        from markitdown import MarkItDown
    except ImportError:
        return ("", "")

    md = MarkItDown()
    try:
        result = md.convert(str(path))
        full = (result.text_content or "").strip()
    except Exception as e:  # markitdown is opinionated and can throw on weird files
        full = f"[parse error: {type(e).__name__}: {e}]"

    preview = full[:PREVIEW_CHARS]
    if len(full) > PREVIEW_CHARS:
        preview += f"\n\n... [truncated {len(full) - PREVIEW_CHARS} more chars]"
    return (preview, full)


def is_parseable(filename: str, mime: str | None) -> bool:
    """Quick filter — extensions/MIME types markitdown handles. Used to skip giant binaries."""
    ext = Path(filename).suffix.lower()
    if ext in {
        ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
        ".html", ".htm", ".xml", ".csv", ".tsv", ".json", ".md", ".txt",
        ".rtf", ".epub", ".zip",
    }:
        return True
    if mime and mime.startswith(("text/", "application/json")):
        return True
    return False
