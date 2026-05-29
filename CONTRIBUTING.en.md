<div align="right"><a href="CONTRIBUTING.md">中文</a> · <b>English</b></div>

# Contributing

PRs and issues welcome. But the blunt truth up front: this is built for **small-team, LAN-only requirement management**, and some things are **left out on purpose**. Don't take a rejection to heart.

## Left out on purpose

- **Passwords / RBAC** — LAN trust model, nickname = identity.
- **Public-internet deploy** — add HTTPS and auth *before* you even think about it.
- **WeCom / DingTalk push** — notifications are in-app + OS-native, no third-party integrations.

## Good PRs

- Bug fixes — especially the cursed **concurrency / state-machine / data-consistency** kind.
- Missing end-to-end tests.
- A **concrete, real problem** — not "I feel like adding X would look nicer."

---

## How the code is laid out

| Dir | What |
|---|---|
| `app/` | FastAPI backend (Python 3.12): models, routes, permissions, services |
| `web/` | browser dispatch + admin app (React + strict TypeScript) |
| `client-tauri/` | **Rust + Tauri v2** desktop client. `src-tauri/` is the Rust core, `web-src/` is its React webview |
| `shared/` | shared frontend lib: UI / types / API client |
| `scripts/` | deploy, smoke, E2E, install verification |

> ⚠️ **The desktop client is Rust/Tauri, not Python.** The `.py` files under `client/` are legacy-tray compat + install scripts — don't read them as the client itself.

---

## Conventions before you touch code

- Backend Python 3.12; web is TypeScript **strict**; desktop is Rust (Tauri v2).
- Touching **status transitions / concurrency**? Use atomic CAS (`UPDATE … WHERE status=<old>` + check rowcount). Never read-then-write — it races.
- Background (detached asyncio) tasks **must reach a terminal state** on every path. No zombie jobs.
- Changed an LLM prompt? Note it in [DEPLOY.md](DEPLOY.md) (model, endpoint, impact).
- **Never commit real API keys / LAN IPs / passwords.** `scripts/server_creds.py` is gitignored — fill in your local copy from `server_creds.example.py`.

---

## Run before you open a PR

```bash
# 1) backend smoke: no LLM, full workflow on a temp SQLite
python scripts/smoke_workflow.py

# 2) full build (shared + web + client webview, incl. tsc typecheck)
npm run build

# 3) web E2E (spins its own backend)
cd web && npx playwright test --project=chromium

# 4) only if you touched the Rust client
cargo check --manifest-path client-tauri/src-tauri/Cargo.toml
npm run tauri:build --workspace=client-tauri
```

Touched a specific milestone module? There's a matching `scripts/smoke_m*.py` you can run on its own.

---

## When filing an issue, include

- Browser / Python version
- The error at the tail of the server log: `/srv/yqgl/data/web.log`
- The error at the tail of the client log (for desktop/tray issues): `%APPDATA%/yqgl/`
- Repro steps — the more specific the better. "It just doesn't work" doesn't help.

---

> 中文版 👉 [CONTRIBUTING.md](CONTRIBUTING.md)
> Think the docs are unclear? Open an issue and roast us — docs are code too.
