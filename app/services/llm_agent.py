"""LLM-driven requirement clarification agent.

Talks to DeepSeek via the Anthropic-compatible endpoint. Uses streaming so we can
forward `thinking_delta` events to the frontend's "思考中..." bubble. The final
`text_delta` stream is expected to be a JSON object matching our action/payload
contract; we parse it strictly and retry once on JSON failure.
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

from anthropic import AsyncAnthropic

from config import settings
from models import Attachment, ChatMessage, Requirement
from prompts import load as load_prompt

logger = logging.getLogger("yqgl.llm_agent")

_client = AsyncAnthropic(base_url=settings.llm_base_url, api_key=settings.llm_api_key)

PREVIEW_BUDGET = 4000  # chars of parsed_text per file
HISTORY_BUDGET = 20    # most recent chat messages


# ---------- streaming event type ----------

@dataclass
class AgentEvent:
    kind: Literal["thinking", "text", "parsed", "error"]
    data: Any  # str for thinking/text; dict for parsed; str for error


# ---------- context building ----------

def _attachments_block(attachments: list[Attachment]) -> str:
    if not attachments:
        return "（无附件）"
    parts = []
    for a in attachments:
        preview = (a.parsed_text or "")[:PREVIEW_BUDGET]
        if a.parsed_text and len(a.parsed_text) > PREVIEW_BUDGET:
            preview += f"\n... [truncated]"
        parts.append(
            f"### 附件 id={a.id}  filename={a.filename}  size={a.size_bytes}B  mime={a.mime or '?'}  role={a.role_in_req or '未确定'}\n"
            f"```\n{preview or '(无可解析文本)'}\n```"
        )
    return "\n\n".join(parts)


def _history_block(messages: list[ChatMessage]) -> list[dict]:
    """Convert stored chat messages into Anthropic message format."""
    out: list[dict] = []
    for m in messages[-HISTORY_BUDGET:]:
        try:
            payload = json.loads(m.content_json)
        except Exception:
            payload = {"raw": m.content_json}

        if m.role == "user":
            # User messages: free text, or {answer_to: ..., selected: ..., other_text: ...}
            text = _format_user_message(payload, m)
            out.append({"role": "user", "content": text})
        elif m.role == "assistant":
            # Echo back the JSON we last produced; helps the model recall what it asked
            out.append({"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)})
    return out


def _format_user_message(payload: dict, m: ChatMessage) -> str:
    if m.selected_option_key:
        bits = [f"[用户选择] key={m.selected_option_key}"]
        if m.user_other_text:
            bits.append(f"[用户补充] {m.user_other_text}")
        return "\n".join(bits)
    if "text" in payload:
        return str(payload["text"])
    return json.dumps(payload, ensure_ascii=False)


def build_user_turn(req: Requirement, attachments: list[Attachment]) -> str:
    return (
        f"# 用户提交的需求原文\n{req.raw_description or '(空)'}\n\n"
        f"# 用户上传的附件解析摘要\n{_attachments_block(attachments)}\n\n"
        f"请按规则输出下一步：澄清问题（ask_choice / ask_open）或最终总结（summarize）。"
    )


# ---------- agent step ----------

async def step(
    req: Requirement,
    attachments: list[Attachment],
    history: list[ChatMessage],
    *,
    force_summarize: bool = False,
) -> AsyncIterator[AgentEvent]:
    """Run one LLM turn. Yields streaming events. Final event is `parsed` or `error`."""
    system_prompt = load_prompt("summarize" if force_summarize else "clarify_system")
    messages = _history_block(history)
    if not messages or messages[0].get("role") != "user":
        messages.insert(0, {"role": "user", "content": build_user_turn(req, attachments)})
    elif messages[0]["role"] == "user":
        # Ensure the first user message always carries the context block.
        messages[0]["content"] = build_user_turn(req, attachments) + "\n\n" + messages[0]["content"]

    if force_summarize:
        messages.append({
            "role": "user",
            "content": '（用户已点击"够了，开始整理"，请直接产出 summarize JSON。）',
        })

    text_accum: list[str] = []
    json_payload: dict | None = None
    last_err: Exception | None = None

    for attempt in range(2):
        text_accum.clear()
        try:
            async for ev in _stream_once(system_prompt, messages, text_accum):
                yield ev
            raw = "".join(text_accum).strip()
            json_payload = _safe_parse_json(raw)
            if json_payload is not None:
                break
            # parse failed; ask the model to retry with stricter instruction
            messages.append({"role": "assistant", "content": raw[:500]})
            messages.append({
                "role": "user",
                "content": "你上一次的输出不是合法的 JSON。请严格按契约重新输出单个 JSON 对象，不要任何额外文字、不要 markdown 围栏。",
            })
        except Exception as e:
            last_err = e
            logger.exception("llm step failed (attempt %d)", attempt)

    if json_payload is None:
        msg = f"LLM 输出无法解析为 JSON（重试 1 次后仍失败）{': ' + repr(last_err) if last_err else ''}"
        yield AgentEvent(kind="error", data=msg)
        return

    yield AgentEvent(kind="parsed", data=json_payload)


async def _stream_once(
    system_prompt: str,
    messages: list[dict],
    text_accum: list[str],
) -> AsyncIterator[AgentEvent]:
    """One streaming call. Yields thinking_delta / text_delta events."""
    async with _client.messages.stream(
        model=settings.llm_model,
        max_tokens=16384,  # summarize 可能很长；DeepSeek v4 pro 支持到 128k
        system=system_prompt,
        messages=messages,
    ) as stream:
        async for event in stream:
            etype = getattr(event, "type", None)
            if etype == "content_block_delta":
                delta = event.delta
                dtype = getattr(delta, "type", None)
                if dtype == "thinking_delta":
                    yield AgentEvent(kind="thinking", data=delta.thinking)
                elif dtype == "text_delta":
                    text_accum.append(delta.text)
                    yield AgentEvent(kind="text", data=delta.text)
            # other event types ignored (message_start/stop, content_block_start, etc.)


# ---------- JSON tolerance ----------

def _safe_parse_json(raw: str) -> dict | None:
    if not raw:
        return None
    raw = raw.strip()
    # strip accidental markdown fences
    if raw.startswith("```"):
        first_nl = raw.find("\n")
        if first_nl != -1:
            raw = raw[first_nl + 1:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        # second-chance: take from first '{' to last '}'
        first = raw.find("{")
        last = raw.rfind("}")
        if first == -1 or last == -1 or last <= first:
            return None
        try:
            d = json.loads(raw[first : last + 1])
        except json.JSONDecodeError:
            return None

    if not isinstance(d, dict):
        return None
    if d.get("action") not in {"ask_choice", "ask_open", "summarize"}:
        return None
    return d
