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
        return "(no attachments)"
    parts = []
    for a in attachments:
        preview = (a.parsed_text or "")[:PREVIEW_BUDGET]
        if a.parsed_text and len(a.parsed_text) > PREVIEW_BUDGET:
            preview += f"\n... [truncated]"
        parts.append(
            f"### Attachment id={a.id}  filename={a.filename}  size={a.size_bytes}B  mime={a.mime or '?'}  role={a.role_in_req or 'unknown'}\n"
            f"```\n{preview or '(no parseable text)'}\n```"
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
        bits = [f"[user selected] key={m.selected_option_key}"]
        if m.user_other_text:
            bits.append(f"[user added] {m.user_other_text}")
        return "\n".join(bits)
    if "text" in payload:
        return str(payload["text"])
    return json.dumps(payload, ensure_ascii=False)


def build_user_turn(req: Requirement, attachments: list[Attachment]) -> str:
    return (
        f"# Original Request From User\n{req.raw_description or '(empty)'}\n\n"
        f"# Parsed Attachment Previews\n{_attachments_block(attachments)}\n\n"
        f"Follow the system instructions and output the next step: a clarification question (`ask_choice` or `ask_open`) or the final summary (`summarize`)."
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
            "content": 'The user clicked "enough, start organizing". Produce the `summarize` JSON directly.',
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
                "content": "Your previous output was not valid JSON. Re-output exactly one JSON object that follows the contract. Do not add extra text or markdown fences.",
            })
        except Exception as e:
            last_err = e
            logger.exception("llm step failed (attempt %d)", attempt)

    if json_payload is None:
        msg = f"LLM output could not be parsed as JSON after one retry{': ' + repr(last_err) if last_err else ''}"
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
