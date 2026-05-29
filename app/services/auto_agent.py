"""Auto-process simple requirements via the Anthropic SDK tool_use loop against DeepSeek.

Sandboxed: every tool call is path-restricted to a workdir per requirement. Runs as an
asyncio task in the FastAPI process; pushes progress events via push_bus on topic
`req:<id>` so the web UI can render a live "AI 处理中…" view.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import resource  # POSIX only; absent on Windows (dev). Used to cap the
    # blast radius of LLM-driven run_command on the Linux prod box.
except ImportError:  # pragma: no cover - Windows dev
    resource = None  # type: ignore[assignment]

from anthropic import AsyncAnthropic

from config import settings
from prompts import load as load_prompt
from services.push_bus import bus

logger = logging.getLogger("yqgl.auto_agent")

_client = AsyncAnthropic(base_url=settings.llm_base_url, api_key=settings.llm_api_key)

MAX_TURNS = 15
TOTAL_TIMEOUT_DEFAULT = 5 * 60  # 5 minutes
MAX_SANDBOX_FILES = 800
MAX_SANDBOX_BYTES = 200 * 1024 * 1024
COMMAND_TIMEOUT = 45
COMMAND_OUTPUT_LIMIT = 12000
ALLOWED_COMMANDS = {
    "python", "python3", "py",
    "node", "npm", "pnpm", "bun",
    "pytest", "ruff", "tsc",
}


# ---------- tools ----------

TOOLS = [
    {
        "name": "list_files",
        "description": "List files recursively under a relative directory in the sandbox.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "relative directory; default is ."}},
        },
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
        "name": "write_base64_file",
        "description": "Write a binary file from base64 content (creates parent dirs).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "base64_content": {"type": "string"},
            },
            "required": ["path", "base64_content"],
        },
    },
    {
        "name": "mkdir",
        "description": "Create a directory inside the sandbox.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "move_path",
        "description": "Move or rename a file/directory inside the sandbox.",
        "input_schema": {
            "type": "object",
            "properties": {"src": {"type": "string"}, "dest": {"type": "string"}},
            "required": ["src", "dest"],
        },
    },
    {
        "name": "delete_path",
        "description": "Delete one file or directory inside the sandbox.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "run_command",
        "description": "Run an allowlisted command inside the sandbox. No shell is used. Keep commands short and deterministic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "args": {"type": "array", "items": {"type": "string"}, "description": "command argv, e.g. ['python','script.py']"},
                "cwd": {"type": "string", "description": "relative working directory; default is ."},
                "timeout_s": {"type": "integer", "minimum": 1, "maximum": 60},
            },
            "required": ["args"],
        },
    },
    {
        "name": "zip_path",
        "description": "Create a zip file inside the sandbox from a relative source path.",
        "input_schema": {
            "type": "object",
            "properties": {"src": {"type": "string"}, "dest": {"type": "string"}},
            "required": ["src", "dest"],
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


def _sandbox_stats(workdir: Path) -> tuple[int, int]:
    count = 0
    total = 0
    for p in workdir.rglob("*"):
        if p.is_file():
            count += 1
            try:
                total += p.stat().st_size
            except Exception:
                pass
    return count, total


def _enforce_sandbox_budget(workdir: Path) -> None:
    count, total = _sandbox_stats(workdir)
    if count > MAX_SANDBOX_FILES:
        raise ValueError(f"sandbox file limit exceeded: {count}>{MAX_SANDBOX_FILES}")
    if total > MAX_SANDBOX_BYTES:
        raise ValueError(f"sandbox size limit exceeded: {total}>{MAX_SANDBOX_BYTES}")


def _tool_list_files(workdir: Path, path: str = ".") -> str:
    root = _safe_path(workdir, path or ".")
    if not root.exists():
        return f"[error] path not found: {path}"
    if not root.is_dir():
        root = root.parent
    files = []
    for p in sorted(root.rglob("*")):
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
    _enforce_sandbox_budget(workdir)
    return f"wrote {p.relative_to(workdir).as_posix()}  ({len(content)} bytes)"


def _tool_write_base64_file(workdir: Path, path: str, base64_content: str) -> str:
    p = _safe_path(workdir, path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = base64.b64decode(base64_content, validate=True)
    p.write_bytes(data)
    _enforce_sandbox_budget(workdir)
    return f"wrote {p.relative_to(workdir).as_posix()}  ({len(data)} bytes)"


def _tool_mkdir(workdir: Path, path: str) -> str:
    p = _safe_path(workdir, path)
    p.mkdir(parents=True, exist_ok=True)
    return f"created {p.relative_to(workdir).as_posix()}"


def _tool_move_path(workdir: Path, src: str, dest: str) -> str:
    src_p = _safe_path(workdir, src)
    dest_p = _safe_path(workdir, dest)
    if not src_p.exists():
        return f"[error] source not found: {src}"
    dest_p.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src_p), str(dest_p))
    _enforce_sandbox_budget(workdir)
    return f"moved {src} -> {dest}"


def _tool_delete_path(workdir: Path, path: str) -> str:
    p = _safe_path(workdir, path)
    if not p.exists():
        return f"[error] path not found: {path}"
    if p.is_dir():
        shutil.rmtree(p)
    else:
        p.unlink()
    return f"deleted {path}"


def _set_rlimit(which, value: int) -> None:
    if resource is None:
        return
    try:
        _soft, hard = resource.getrlimit(which)
        cap = value if hard == resource.RLIM_INFINITY else min(value, hard)
        resource.setrlimit(which, (cap, cap))
    except (ValueError, OSError):
        pass  # best-effort; never block the run on a platform quirk


def _sandbox_rlimits() -> None:
    """preexec_fn (POSIX) — runs in the forked child just before exec. The
    path-prefix enforcement only governs the *tool* layer; once a real
    interpreter runs it can open absolute paths. These per-process caps bound
    the blast radius so an LLM-driven (or prompt-injected) script can't
    exhaust memory, write a disk-filling file, or leak file descriptors. CPU
    is a backstop below typical wall-clock; the asyncio per-command timeout is
    still the primary kill. RLIMIT_NPROC is deliberately NOT set — it is
    per-UID and would risk failing exec on a busy server. Network egress is
    NOT blocked here (would need a netns); that residual is accepted under the
    trusted-LAN, opt-in, authenticated-author threat model and documented in
    prompts/auto_agent.md."""
    if resource is None:
        return
    _set_rlimit(resource.RLIMIT_CPU, 120)                      # CPU seconds
    _set_rlimit(resource.RLIMIT_AS, 2 * 1024 * 1024 * 1024)    # 2 GiB address space
    _set_rlimit(resource.RLIMIT_FSIZE, 256 * 1024 * 1024)      # 256 MiB single-file write
    _set_rlimit(resource.RLIMIT_NOFILE, 512)                   # open file descriptors


def _tool_run_command(workdir: Path, args: list[str], cwd: str = ".", timeout_s: int | None = None) -> str:
    if not args:
        return "[error] args must not be empty"
    exe = Path(args[0]).name.lower()
    if exe.endswith(".exe"):
        exe = exe[:-4]
    if exe not in ALLOWED_COMMANDS:
        return f"[error] command not allowlisted: {args[0]}"
    if exe in {"npm", "pnpm", "bun"} and len(args) > 1 and args[1] in {"install", "add", "i"}:
        return "[error] dependency installation is disabled in the sandbox"
    cwd_p = _safe_path(workdir, cwd or ".")
    if not cwd_p.exists() or not cwd_p.is_dir():
        return f"[error] cwd is not a directory: {cwd}"
    for arg in args[1:]:
        if "\x00" in arg:
            return "[error] invalid null byte in args"
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(workdir),
        "HOME": str(workdir),
        "TMPDIR": str(workdir / ".tmp"),
        "TEMP": str(workdir / ".tmp"),
        "TMP": str(workdir / ".tmp"),
        "NO_COLOR": "1",
    }
    (workdir / ".tmp").mkdir(exist_ok=True)
    timeout = max(1, min(int(timeout_s or COMMAND_TIMEOUT), 60))
    try:
        proc = subprocess.run(
            args,
            cwd=cwd_p,
            env=env,
            shell=False,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            preexec_fn=_sandbox_rlimits if resource is not None else None,
        )
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") + "\n" + (exc.stderr or "")
        return f"[timeout after {timeout}s]\n{out[:COMMAND_OUTPUT_LIMIT]}"
    _enforce_sandbox_budget(workdir)
    output = (
        f"exit_code={proc.returncode}\n"
        f"stdout:\n{proc.stdout}\n"
        f"stderr:\n{proc.stderr}"
    )
    if len(output) > COMMAND_OUTPUT_LIMIT:
        output = output[:COMMAND_OUTPUT_LIMIT] + "\n...[truncated]"
    return output


def _tool_zip_path(workdir: Path, src: str, dest: str) -> str:
    src_p = _safe_path(workdir, src)
    dest_p = _safe_path(workdir, dest)
    if not src_p.exists():
        return f"[error] source not found: {src}"
    if src_p == dest_p or src_p in dest_p.parents:
        return "[error] destination cannot be inside source"
    dest_p.parent.mkdir(parents=True, exist_ok=True)
    made_name = shutil.make_archive(
        str(dest_p.with_suffix("")),
        "zip",
        root_dir=src_p if src_p.is_dir() else src_p.parent,
        base_dir="." if src_p.is_dir() else src_p.name,
    )
    made = Path(made_name)
    if made != dest_p and made.exists():
        shutil.move(str(made), str(dest_p))
    _enforce_sandbox_budget(workdir)
    return f"zipped {src} -> {dest}"


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
                f"The sandbox may contain user attachments under `inputs/`. "
                f"Put final deliverables under `outputs/` and add `outputs/README.md` when useful. "
                f"Start by inspecting files, then implement."
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
                            content = _tool_list_files(workdir, str(inp.get("path", ".")))
                        elif name == "read_file":
                            content = _tool_read_file(workdir, str(inp.get("path", "")))
                        elif name == "write_file":
                            content = _tool_write_file(workdir, str(inp.get("path", "")), str(inp.get("content", "")))
                        elif name == "write_base64_file":
                            content = _tool_write_base64_file(workdir, str(inp.get("path", "")), str(inp.get("base64_content", "")))
                        elif name == "mkdir":
                            content = _tool_mkdir(workdir, str(inp.get("path", "")))
                        elif name == "move_path":
                            content = _tool_move_path(workdir, str(inp.get("src", "")), str(inp.get("dest", "")))
                        elif name == "delete_path":
                            content = _tool_delete_path(workdir, str(inp.get("path", "")))
                        elif name == "run_command":
                            raw_args = inp.get("args", [])
                            args = [str(x) for x in raw_args] if isinstance(raw_args, list) else []
                            # Off the event loop — subprocess.run blocks up to
                            # 60s; running it inline would freeze every SSE
                            # stream, health check, and request for that whole
                            # window. The other tools are sub-ms fs ops.
                            content = await asyncio.to_thread(
                                _tool_run_command,
                                workdir,
                                args,
                                str(inp.get("cwd", ".")),
                                int(inp.get("timeout_s", COMMAND_TIMEOUT) or COMMAND_TIMEOUT),
                            )
                        elif name == "zip_path":
                            content = _tool_zip_path(workdir, str(inp.get("src", "")), str(inp.get("dest", "")))
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
    outdir = workdir / "outputs"
    if not outdir.exists():
        return False
    for p in outdir.rglob("*"):
        if p.is_file():
            return True
    return False


def _result(success: bool, reason: str, notes: str, turn: int, started: float, workdir: Path) -> AutoResult:
    outdir = workdir / "outputs"
    file_count = sum(1 for p in outdir.rglob("*") if p.is_file()) if outdir.exists() else 0
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
    review_root = workdir / "outputs"
    files = sorted(p for p in review_root.rglob("*") if p.is_file()) if review_root.exists() else []
    chunks = []
    for p in files[:20]:  # cap
        try:
            text = p.read_text(encoding="utf-8")[:2000]
        except Exception:
            text = "(binary or unreadable)"
        chunks.append(f"### {p.relative_to(review_root).as_posix()} ({p.stat().st_size}B)\n```\n{text}\n```")
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


def _preload_inputs(workdir: Path, input_files: list[tuple[str, Path]] | None) -> None:
    if not input_files:
        return
    inputs = workdir / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    for filename, source in input_files:
        clean = Path(filename or source.name).name or source.name
        candidate = clean
        stem = Path(clean).stem or "file"
        suffix = Path(clean).suffix
        n = 2
        while candidate in used or (inputs / candidate).exists():
            candidate = f"{stem}-{n}{suffix}"
            n += 1
        used.add(candidate)
        if source.exists() and source.is_file():
            shutil.copy2(source, inputs / candidate)


async def auto_process(
    *,
    req_id: str,
    req_title: str,
    summary_md: str,
    workdir: Path,
    timeout: int = TOTAL_TIMEOUT_DEFAULT,
    input_files: list[tuple[str, Path]] | None = None,
) -> AutoOutcome:
    """Run agent + LLM review. Returns final outcome."""
    # fresh workdir
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "outputs").mkdir(parents=True, exist_ok=True)
    _preload_inputs(workdir, input_files)

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
