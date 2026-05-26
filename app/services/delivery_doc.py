"""LLM-generated 交付文档 for human-submitted delivery packages.

Unpacks the zip to a temp dir, parses each file with markitdown, then asks the LLM
to write a customer-facing markdown doc explaining what was delivered.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic

from config import settings
from services.file_parser import is_parseable, parse_file

logger = logging.getLogger("yqgl.delivery_doc")

_client = AsyncAnthropic(base_url=settings.llm_base_url, api_key=settings.llm_api_key)

MAX_ZIP_FILES = 2000
MAX_ZIP_ENTRY_BYTES = 100 * 1024 * 1024
MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 200

SYSTEM = """You are a delivery-documentation assistant. Based on the original requirement and the package submitted by the implementer, write a requester-friendly markdown delivery note.

Use the user's language for all output. If the original requirement is in Chinese, write the markdown in Chinese. If it is in English, write it in English. Translate section headings accordingly.

Output markdown directly. Do not wrap it in JSON.

Required structure:

## Delivery Overview
One or two sentences explaining what was completed.

## Delivered Files
- `file1.ext`: what it is and how to use it.
- `file2.ext`: ...

## How To Use / Verify
Steps, commands, expected results, and acceptance checks.

## Mapping To The Original Requirement
For each important requirement point, explain which file or behavior satisfies it.

## Known Limits / Follow-Up Suggestions
Optional. If there are no known limits, say so in the user's language.
"""


async def generate_doc(req_title: str, req_summary_md: str, zip_path: Path,
                       prior_round_files: list[str] | None = None) -> str:
    """Returns delivery_doc_md (a markdown string)."""
    with tempfile.TemporaryDirectory(prefix="yqgl-deliv-") as td:
        tmp = Path(td)
        try:
            entries = inspect_zip_entries(zip_path)
            with zipfile.ZipFile(zip_path) as z:
                _safe_extract_entries(z, entries, tmp)
        except Exception as e:
            return f"## 交付文档生成失败\n\n解包失败: {e}"

        chunks: list[str] = []
        files_seen = 0
        for p in sorted(tmp.rglob("*")):
            if not p.is_file():
                continue
            files_seen += 1
            rel = p.relative_to(tmp).as_posix()
            try:
                if is_parseable(p.name, None):
                    preview, _ = parse_file(p)
                    body = preview or "(empty)"
                else:
                    try:
                        body = p.read_text(encoding="utf-8")[:2000]
                    except Exception:
                        body = f"(binary file, {p.stat().st_size}B)"
            except Exception as e:
                body = f"(read failed: {e})"
            chunks.append(f"### {rel}  ({p.stat().st_size}B)\n```\n{body[:2000]}\n```")
            if files_seen >= 25:
                chunks.append(f"... (more files omitted)")
                break

        files_block = "\n\n".join(chunks) or "(empty delivery package)"

        diff_block = ""
        if prior_round_files:
            new_files = {p.relative_to(tmp).as_posix() for p in tmp.rglob("*") if p.is_file()}
            added = sorted(new_files - set(prior_round_files))
            removed = sorted(set(prior_round_files) - new_files)
            if added or removed:
                diff_block = f"\n\n# Difference From Previous Delivery Round\nAdded: {added}\nRemoved: {removed}"

        user_msg = (
            f"# Original Requirement\nTitle: {req_title}\n\n{req_summary_md}\n\n"
            f"# Submitted Delivery Package: File List And Content Previews\n{files_block}"
            f"{diff_block}"
        )

        try:
            resp = await _client.messages.create(
                model=settings.llm_model,
                max_tokens=8192,
                system=SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
            )
        except Exception as e:
            logger.exception("delivery doc LLM call failed")
            return f"## 交付文档生成失败\n\nLLM 调用失败: {e}"

        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        if not text:
            return "## 交付文档\n\n(LLM 未返回任何文本)"
        return text


def list_zip_files(zip_path: Path) -> list[str]:
    try:
        return [str(e["safe_name"]) for e in inspect_zip_entries(zip_path)]
    except Exception:
        return []


def inspect_zip_entries(zip_path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    total_uncompressed = 0

    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue

            safe_name = _safe_zip_name(info.filename)
            if not safe_name:
                raise ValueError(f"unsafe zip path: {info.filename}")
            if info.file_size > MAX_ZIP_ENTRY_BYTES:
                raise ValueError(f"zip entry too large: {safe_name}")

            total_uncompressed += info.file_size
            if total_uncompressed > MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES:
                raise ValueError("zip uncompressed size too large")

            if info.compress_size > 0 and info.file_size > 1024 * 1024:
                ratio = info.file_size / info.compress_size
                if ratio > MAX_ZIP_COMPRESSION_RATIO:
                    raise ValueError(f"suspicious compression ratio: {safe_name}")

            entries.append({
                "name": info.filename,
                "safe_name": safe_name,
                "size": info.file_size,
            })

    if len(entries) > MAX_ZIP_FILES:
        raise ValueError(f"too many files in zip: {len(entries)}")
    return entries


def _safe_zip_name(name: str) -> str | None:
    if name.startswith(("/", "\\")) or (len(name) >= 2 and name[1] == ":"):
        return None
    parts = [p for p in name.replace("\\", "/").split("/") if p not in {"", "."}]
    if not parts or any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def _safe_extract_entries(z: zipfile.ZipFile, entries: list[dict[str, Any]], target_dir: Path) -> None:
    root = target_dir.resolve()
    for entry in entries:
        dest = (root / str(entry["safe_name"])).resolve()
        if root not in dest.parents and dest != root:
            raise ValueError(f"unsafe zip path: {entry['safe_name']}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with z.open(str(entry["name"])) as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out, length=1024 * 1024)
