"""Auto-process simple requirements via the Anthropic SDK tool_use loop against DeepSeek.

Sandboxed: every tool call is path-restricted to a workdir per requirement. Runs as an
asyncio task in the FastAPI process; pushes progress events via push_bus on topic
`req:<id>` so the web UI can render a live "AI 处理中…" view.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from anthropic import AsyncAnthropic

from config import settings
from prompts import load as load_prompt
from services.push_bus import bus

logger = logging.getLogger("yqgl.auto_agent")

_client = AsyncAnthropic(base_url=settings.llm_base_url, api_key=settings.llm_api_key)

MAX_TURNS = 15
TOTAL_TIMEOUT_DEFAULT = 5 * 60  # 5 minutes


# ---------- tools ----------

TOOLS = [
    {
        "name": "list_files",
        "description": "List all files (recursively) in the working directory.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_file",
        "description": "Read the full text contents of a file (UTF-8).",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "path relative to workdir"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write UTF-8 text to a file (creates parent dirs).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "submit",
        "description": "Declare the task done. Pass a short note describing what was produced.",
        "input_schema": {
            "type": "object",
            "properties": {"notes": {"type": "string"}},
            "required": ["notes"],
        },
    },
]


def _safe_path(workdir: Path, rel: str) -> Path:
    """Resolve `rel` against workdir, ensuring it stays inside."""
    p = (workdir / rel).resolve()
    workdir_r = workdir.resolve()
    if workdir_r not in p.parents and p != workdir_r:
        raise ValueError(f"path escapes workdir: {rel}")
    return p


def _tool_list_files(workdir: Path) -> str:
    files = []
    for p in sorted(workdir.rglob("*")):
        if p.is_file():
            try:
                files.append(f"{p.relative_to(workdir).as_posix()}  ({p.stat().st_size}B)")
            except Exception:
                pass
    return "\n".join(files) if files else "(empty)"


def _tool_read_file(workdir: Path, path: str) -> str:
    p = _safe_path(workdir, path)
    if not p.exists():
        return f"[error] file not found: {path}"
    if not p.is_file():
        return f"[error] not a regular file: {path}"
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"[error] binary file (cannot decode as UTF-8): {path}"


def _tool_write_file(workdir: Path, path: str, content: str) -> str:
    p = _safe_path(workdir, path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {p.relative_to(workdir).as_posix()}  ({len(content)} bytes)"


# ---------- agent loop ----------

@dataclass
class AutoResult:
    success: bool
    reason: str           # short description of outcome
    notes: str            # agent's own notes (from submit) or error
    turns: int
    seconds: float
    file_count: int       # files in deliverables dir at end


async def run_auto(
    *,
    req_id: str,
    req_title: str,
    summary_md: str,
    workdir: Path,
    timeout: int = TOTAL_TIMEOUT_DEFAULT,
) -> AutoResult:
    """Execute one auto-process attempt. Returns AutoResult."""
    workdir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    system = load_prompt("auto_agent")

    messages: list[dict] = [
        {
            "role": "user",
            "content": (
                f"# Requirement Title\n{req_title}\n\n"
                f"# Requirement Details\n{summary_md}\n\n"
                f"The working directory is currently empty. Start implementing now."
            ),
        }
    ]

    await bus.publish(f"req:{req_id}", "ai.started", {"max_turns": MAX_TURNS, "timeout_s": timeout})

    final_notes = ""
    turn = 0
    try:
        for turn in range(1, MAX_TURNS + 1):
            if time.monotonic() - started > timeout:
                return _result(False, "总耗时超过预算", "timeout", turn, started, workdir)

            try:
                # 必须用 streaming API：anthropic SDK 在 max_tokens > ~21k 时强制要求
                # （write_file 可能一次塞较大文件，DeepSeek v4 pro 输出上限 128k）
                async def _do_call():
                    async with _client.messages.stream(
                        model=settings.llm_model,
                        max_tokens=32768,
                        system=system,
                        tools=TOOLS,
                        messages=messages,
                    ) as stream_ctx:
                        return await stream_ctx.get_final_message()

                resp = await asyncio.wait_for(
                    _do_call(),
                    timeout=max(30, timeout - int(time.monotonic() - started)),
                )
            except asyncio.TimeoutError:
                return _result(False, "单轮 LLM 调用超时", "llm_timeout", turn, started, workdir)
            except Exception as e:
                logger.exception("LLM call failed")
                return _result(False, f"LLM 调用失败: {type(e).__name__}", str(e)[:300], turn, started, workdir)

            # echo back: append assistant message (must use raw content blocks per Anthropic API)
            messages.append({"role": "assistant", "content": [b.model_dump() for b in resp.content]})

            tool_results: list[dict] = []
            for block in resp.content:
                if block.type == "thinking":
                    await bus.publish(f"req:{req_id}", "ai.thinking", {"turn": turn, "text": block.thinking[:200]})
                elif block.type == "text" and block.text.strip():
                    await bus.publish(f"req:{req_id}", "ai.text", {"turn": turn, "text": block.text[:200]})
                elif block.type == "tool_use":
                    name = block.name
                    inp = block.input or {}
                    await bus.publish(f"req:{req_id}", "ai.tool_call", {
                        "turn": turn, "name": name,
                        "input_preview": json.dumps(inp, ensure_ascii=False)[:200],
                    })

                    if name == "submit":
                        final_notes = str(inp.get("notes", ""))
                        success = _has_deliverables(workdir)
                        if success:
                            return _result(True, "AI 已交付", final_notes, turn, started, workdir)
                        else:
                            return _result(False, "AI 调用 submit 但产物目录为空", final_notes, turn, started, workdir)

                    try:
                        if name == "list_files":
                            content = _tool_list_files(workdir)
                        elif name == "read_file":
                            content = _tool_read_file(workdir, str(inp.get("path", "")))
                        elif name == "write_file":
                            content = _tool_write_file(workdir, str(inp.get("path", "")), str(inp.get("content", "")))
                        else:
                            content = f"[error] unknown tool: {name}"
                    except Exception as e:
                        content = f"[error] {type(e).__name__}: {e}"

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": content,
                    })

            if tool_results:
                messages.append({"role": "user", "content": tool_results})
            elif resp.stop_reason == "end_turn":
                # model decided to stop without submitting → treat as no-op failure
                return _result(False, "AI 未调用 submit 就结束", final_notes or "", turn, started, workdir)

        return _result(False, f"达到最大轮次 {MAX_TURNS} 未完成", final_notes, MAX_TURNS, started, workdir)
    finally:
        await bus.publish(f"req:{req_id}", "ai.done", {"turns": turn})


def _has_deliverables(workdir: Path) -> bool:
    for p in workdir.rglob("*"):
        if p.is_file():
            return True
    return False


def _result(success: bool, reason: str, notes: str, turn: int, started: float, workdir: Path) -> AutoResult:
    file_count = sum(1 for p in workdir.rglob("*") if p.is_file())
    return AutoResult(
        success=success,
        reason=reason,
        notes=notes,
        turns=turn,
        seconds=time.monotonic() - started,
        file_count=file_count,
    )


# ---------- LLM review (4th failure-mode check) ----------

REVIEW_SYSTEM = """You are a quality reviewer. You will receive a requirement and the files produced by an AI worker.
Judge whether the deliverables truly satisfy the requirement.

Output exactly one JSON object and no extra text:
{"meets_requirement": true/false, "reason": "..."}

Write the `reason` in the user's language. If the requirement is in Chinese, write the reason in Chinese. If it is in English, write it in English."""


async def llm_review(req_title: str, summary_md: str, workdir: Path) -> tuple[bool, str]:
    """Run a separate LLM call to judge if AI's deliverables actually satisfy the requirement."""
    files = sorted(p for p in workdir.rglob("*") if p.is_file())
    chunks = []
    for p in files[:20]:  # cap
        try:
            text = p.read_text(encoding="utf-8")[:2000]
        except Exception:
            text = "(binary or unreadable)"
        chunks.append(f"### {p.relative_to(workdir).as_posix()} ({p.stat().st_size}B)\n```\n{text}\n```")
    file_dump = "\n\n".join(chunks) or "(no files)"

    try:
        resp = await _client.messages.create(
            model=settings.llm_model,
            max_tokens=2048,  # 评审输出短 JSON
            system=REVIEW_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"# Requirement\n{req_title}\n\n{summary_md}\n\n"
                    f"# Files Produced By The AI Worker\n{file_dump}\n\n"
                    f"Judge whether the produced files satisfy the requirement."
                ),
            }],
        )
    except Exception as e:
        return False, f"复审 LLM 调用失败: {e}"

    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if text.startswith("```"):
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        d = json.loads(text)
        return bool(d.get("meets_requirement")), str(d.get("reason", ""))
    except Exception:
        return False, f"复审输出无法解析: {text[:200]}"


# ---------- end-to-end orchestrator ----------

@dataclass
class AutoOutcome:
    success: bool
    reason: str
    notes: str
    review_passed: bool
    review_reason: str
    workdir: str
    file_count: int
    seconds: float


async def auto_process(*, req_id: str, req_title: str, summary_md: str, workdir: Path, timeout: int = TOTAL_TIMEOUT_DEFAULT) -> AutoOutcome:
    """Run agent + LLM review. Returns final outcome."""
    # fresh workdir
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    result = await run_auto(
        req_id=req_id, req_title=req_title, summary_md=summary_md,
        workdir=workdir, timeout=timeout,
    )
    if not result.success:
        return AutoOutcome(
            success=False, reason=result.reason, notes=result.notes,
            review_passed=False, review_reason="(跳过复审，agent 阶段已失败)",
            workdir=str(workdir), file_count=result.file_count, seconds=result.seconds,
        )

    passed, why = await llm_review(req_title, summary_md, workdir)
    final = AutoOutcome(
        success=result.success and passed,
        reason=("LLM 复审通过" if passed else "LLM 复审不通过") if result.success else result.reason,
        notes=result.notes,
        review_passed=passed,
        review_reason=why,
        workdir=str(workdir),
        file_count=result.file_count,
        seconds=result.seconds,
    )
    return final
