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

from anthropic import AsyncAnthropic

from config import settings
from services.file_parser import is_parseable, parse_file

logger = logging.getLogger("yqgl.delivery_doc")

_client = AsyncAnthropic(base_url=settings.llm_base_url, api_key=settings.llm_api_key)

SYSTEM = """你是交付文档撰写助理。基于原始需求和接单方提交的交付物清单，
写一份对提需求方友好的 markdown 交付说明。

输出格式（直接给 markdown，无 JSON 包装）：
## 交付概述
（一两句话说清楚做完了什么）

## 交付物清单
- `file1.ext` —— 这是什么 / 怎么用
- `file2.ext` —— ...

## 如何使用 / 验收
（步骤，命令，预期结果）

## 原始需求映射
（针对需求里每条要点，说明在哪个文件 / 怎么实现了）

## 已知限制 / 后续建议
（可选；若都满足就写"无"）
"""


async def generate_doc(req_title: str, req_summary_md: str, zip_path: Path,
                       prior_round_files: list[str] | None = None) -> str:
    """Returns delivery_doc_md (a markdown string)."""
    with tempfile.TemporaryDirectory(prefix="yqgl-deliv-") as td:
        tmp = Path(td)
        try:
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(tmp)
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
                    body = preview or "(空)"
                else:
                    try:
                        body = p.read_text(encoding="utf-8")[:2000]
                    except Exception:
                        body = f"(二进制文件, {p.stat().st_size}B)"
            except Exception as e:
                body = f"(读取失败: {e})"
            chunks.append(f"### {rel}  ({p.stat().st_size}B)\n```\n{body[:2000]}\n```")
            if files_seen >= 25:
                chunks.append(f"... (还有更多文件未展示)")
                break

        files_block = "\n\n".join(chunks) or "(空交付包)"

        diff_block = ""
        if prior_round_files:
            new_files = {p.relative_to(tmp).as_posix() for p in tmp.rglob("*") if p.is_file()}
            added = sorted(new_files - set(prior_round_files))
            removed = sorted(set(prior_round_files) - new_files)
            if added or removed:
                diff_block = f"\n\n# 与上一轮交付的差异\n新增: {added}\n移除: {removed}"

        user_msg = (
            f"# 原始需求\n标题: {req_title}\n\n{req_summary_md}\n\n"
            f"# 接单方提交的交付包文件清单 + 内容预览\n{files_block}"
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
        with zipfile.ZipFile(zip_path) as z:
            return [i.filename for i in z.infolist() if not i.is_dir()]
    except Exception:
        return []
