"""E2E: simulate the tray's '完成任务并上传' flow programmatically.

(In real usage the user clicks the menu; here we drive the same code paths.)

1. Add some deliverable files to D:\\工作需求\\e2e\\E2E-001\\
2. Use the tray's own ServerClient.upload_delivery to push them up
3. Wait for the LLM-written delivery doc to populate
4. Verify the requirement is now in 'delivered' state
"""
import json
import os
import sys
import time
import tempfile
import zipfile
import hashlib
from pathlib import Path

# Reuse the tray client modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "client"))
from yqgl_tray import Config, ServerClient, zip_directory, sanitize

APPDATA = Path(os.environ.get("APPDATA", str(Path.home() / ".config")))
CFG_PATH = APPDATA / "yqgl" / "config.json"

cfg = Config(**json.loads(CFG_PATH.read_text(encoding="utf-8")))
client = ServerClient(cfg)

# locate the synced dir for E2E-001
sync = Path(cfg.sync_root) / "e2e" / "E2E-001"
if not sync.exists():
    raise SystemExit(f"sync dir missing: {sync}")

print(f"adding deliverables to {sync}")

# Add a realistic Markdown template (mimicking the접 done work)
(sync / "上线Checklist模板.md").write_text("""# 🚀 产品上线 Checklist

> **🔥 应急回滚 SOP** （上线异常优先看这里）
> - 立刻在监控群 @全员，描述故障范围与严重度
> - 在 CI 找到上一稳定 tag，按需走 `deploy --rollback`
> - 回滚后做冒烟：登录 / 核心交易 / 数据写入
> - 12 小时内出事故报告，含时间线、根因、改进项

---

## ✅ 1. 技术验证（QA-Tech）
- [ ] 主流程冒烟通过（注册 / 登录 / 核心交易 / 退款）
- [ ] 灰度配置已生效，回滚开关可即时生效
- [ ] 缓存预热完成
- [ ] 数据库 schema 已 migration

## ✅ 2. 文案审核（Content）
- [ ] 文案审核单已签署
- [ ] 提示语兜底（网络异常/超时/无数据）
- [ ] 多语言（如有）

## ✅ 3. 数据埋点（Data）
- [ ] 新埋点已上传到埋点平台
- [ ] 关键漏斗 30 分钟内可看到数据
- [ ] AB 实验配置正确

## ✅ 4. 应急回滚（Rollback）
- [ ] 回滚命令验证一次（dry-run）
- [ ] 双值班 oncall 已确认在线
- [ ] 监控大盘已置顶
- [ ] 回滚版本 tag 已记录在变更工单
""", encoding="utf-8")

(sync / "README.md").write_text("""# 上线 Checklist 模板使用说明

把 `上线Checklist模板.md` 复制到本次上线的工单/PR 描述里，逐项打勾。
回滚 SOP 已放在最顶部并加 🔥 emoji，方便事故时一眼看到。

如有改进，欢迎直接编辑模板并通知团队。
""", encoding="utf-8")

print(f"  files in dir now: {sum(1 for _ in sync.rglob('*') if _.is_file())}")

# Find the requirement id from the server
reqs = client.list_all_with_statuses(["ready", "claimed", "doing", "revision_requested"])
me = next((r for r in reqs if r["code"] == "E2E-001"), None)
if not me:
    raise SystemExit("requirement E2E-001 not in actionable state on server")
rid = me["id"]
print(f"\nrequirement id: {rid}, status now: {me['status']}")

# Claim if still 'ready' (tray's flow allows starting deliver from ready/claimed/doing/revision)
if me["status"] == "ready":
    client._client.post(f"/api/requirements/{rid}/claim").raise_for_status()
    print("  claimed")

# Zip the whole sync dir
tmp_zip = Path(tempfile.gettempdir()) / f"e2e-deliver-{int(time.time())}.zip"
count, sha = zip_directory(sync, tmp_zip)
print(f"\nzipped {count} files → {tmp_zip} ({tmp_zip.stat().st_size}B, sha={sha[:12]}…)")

# Upload using the tray's actual method
def prog(sent, total):
    print(f"  uploaded {sent}/{total}")
d = client.upload_delivery(rid, tmp_zip, progress=prog)
print(f"\nfinalize → {d}")

# Wait for LLM doc
print("\nwaiting for LLM doc to populate (up to 30s)...")
for i in range(20):
    time.sleep(1.5)
    deliveries = client._client.get(f"/api/requirements/{rid}/deliveries").json()
    doc = deliveries[0].get("delivery_doc_md") or ""
    if "正在撰写" not in doc and len(doc) > 100:
        print(f"\n=== 交付文档 ({len(doc)} chars) ===")
        print(doc[:1200])
        break
else:
    print("  ⚠ doc didn't fill in 30s")

final = client._client.get(f"/api/requirements/{rid}").json()
print(f"\nfinal requirement status: {final['status']}")

# Cleanup
try: tmp_zip.unlink()
except Exception: pass
client.close()
