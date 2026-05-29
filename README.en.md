<div align="right"><a href="README.md">中文</a> · <b>English</b></div>

# Requirement Master

**Boss:** "Just build something roughly like that."
**You:** "...roughly like *what*?"
**Boss:** "You know what I mean."
**You:** *(does not know, has already started building)*

Every software team runs this exact loop. Requirement Master exists to break it — a **LAN-only** requirement hub that turns "something somebody said in the group chat" into **real work with a status, a deadline, an owner, and a sign-off.**

No signups, no cloud, no wiring up eighteen SaaS tools. Stand up one box on your network and the whole team gets to work.

![Rust frosted-glass client](screenshots/readme/rust-client-glass.png)

---

## A few questions for your soul

- Boss says "use your judgment," and somehow your judgment ends up holding the bag?
- A requirement drifts through chat for three days — nobody can find the attachment, nobody remembers the deadline, and when you ask "who asked for this?" everyone goes silent?
- Is `final_v2_actually_final_for_real_this_time.zip` buried 800 messages deep?
- Everyone leaves the meeting fired up, and by morning nobody remembers what was decided?
- Leadership asks "how's the project?" and you hand-roll a status report to make it go away?

If even one hit home, keep reading.

---

## What it actually fixes

| The disease | The cure |
|---|---|
| Vague requirements | The AI interrogates the boss *for* you — who uses it, when's it due, acceptance criteria, attachments, owner, deadline — until it's buildable |
| Forgotten requirements | Every requirement has a state machine, a deadline, an owner, collaborators, and a personal workspace |
| Files everywhere | One project drive: preview, trash/restore, feed into the knowledge base |
| Pointless meetings | Audio/text auto-generates minutes and auto-flags "new requirement / requirement change" |
| Black-box projects | Health + planning + notifications + knowledge in one screen — no more hand-rolled weekly reports |

---

## Two ends: one talks, one works

This thing is **dual-end**, with a clear division of labor:

- **Web dispatch deck** = the war room. File requirements, run AI clarification, name an assignee, browse projects/planning/health/knowledge, accept work, send it back for rework. **But the browser can't touch "claim" or "deliver."**
- **Rust frosted-glass desktop** = the workbench. Dispatch *and* claim, plus local files, a resident tray, OS notifications, drive sync, and packaged delivery.

Why can't the browser claim work? Because claiming/delivering has to be bound to "which device is this" — the desktop carries a client-device token the server **hard-verifies**. Try to bypass the UI and hit the API raw to sneak a claim? The backend has one word for you: **no**.

---

## Screenshots, because a README without them is a crime

**Dispatch deck — who sent it, who took it, who signs off, who's on the hook, all in one screen**
![Dispatch deck](screenshots/readme/dispatch-space.png)

**New requirement — say it clearly first, then let people build**
![New requirement](screenshots/readme/new-requirement.png)

**Project drive — stop burying files 800 messages deep in chat**
![Project drive](screenshots/readme/project-drive.png)

**Project health — know which requirement is about to blow up before the boss bangs the table**
![Project health](screenshots/readme/project-health.png)

---

## Features, one by one

**🤖 AI requirement clarification**
You drop "I want some kind of management system," and the AI doesn't start building — it grills you back: Who uses it? When's it due? What's the acceptance bar? Where are the attachments? Who owns it? What's the deadline? Once it's pinned down, it writes a summary, and **only the submitter can ship it after confirming.** Prompts are written in English internally; the replies you see speak your language. Clarification streams a "thinking…" bubble plus the final result — no frozen spinner.

**👥 Multiple assignees**
One requirement = 1 lead + N collaborators, each with their own workspace: current phase, progress %, blocker reason, to-do checklist, activity feed. No assignee named? It drops into the public pool, and whoever claims it on the desktop becomes the lead.

**⏰ Deadlines & calendar**
Shipping a requirement **requires** a deadline — non-negotiable. The deadline auto-syncs to the calendar, and the desktop reminds you at 24h / 2h / due / overdue. Say "I thought next Friday meant the Friday after" one more time and the system sighs on your behalf.

**📁 Project drive**
Folder / list / card views; upload, download, bulk-download as a zip; preview for PDF / Markdown / text / code / HTML / Office; soft-delete, trash, and undo; plus a folder comment board — every comment passes through an LLM, small talk stays a comment, but the moment it reads as a **requirement change it spawns a draft requirement for you.**

**🎙️ Meeting minutes**
Drop in audio or text → a background job shows a progress bar → ASR transcribes → an LLM writes the minutes → an LLM decides whether there's a new or changed requirement → and only after a **human confirms** does it enter the clarify flow. Meeting insights **never edit the original requirement directly** — so one teammate's passionate meeting rant can't nuke production state.

**🔎 Knowledge base (search without a vector DB)**
This project deliberately skips embeddings. The backend mashes projects, requirements, meetings, comments, workspaces, parsed drive text, and delivery docs into a Markdown corpus; search and the Q&A agent run on **controlled grep**, and answers **must cite evidence.** If it's not there, it says so — it will never feed you "I feel like it's probably this."

**📊 Planning / notifications / health**
Planning shows each person's open tasks, estimated hours, overdue, blocked, and load; the notification center splits unread/read with deep links, the desktop fires OS notifications for key events, and the web pops live toasts; health tracks overdue, blocked, unclaimed, rework rate, change count, throughput, and average cycle time.

---

## Running in five minutes

**Web** — open it on the LAN:

```text
http://192.168.5.53:8080/
```

Requirements are project-scoped — open a project first, then click "New requirement." The URL looks like:

```text
http://192.168.5.53:8080/p/<projectId>/new
```

**Windows** — two ways, take your pick:

Easiest: open http://192.168.5.53:8080/ and hit **Windows 客户端** in the download banner up top — that's the NSIS installer (the real Rust/Tauri client, not the old Python tray). Double-click to install.

Prefer the terminal? One PowerShell line does the same:

```powershell
powershell -ExecutionPolicy Bypass -c "iwr -UseBasicParsing http://192.168.5.53:8080/client/install.ps1 | iex"
```

It drops a 需求管理大师 shortcut in the Start Menu and on the Desktop, writes your server config, and parks a tray icon.
- First launch gets stopped by SmartScreen (unsigned internal build) — click **More info → Run anyway**.
- Can't find the tray icon? Click that little hidden-icons arrow in the corner first — Windows just tucked it away.

**macOS native build** — already published. Just hit the **macOS 客户端** button in the download banner at the top of the web app. Windows folks click Windows, Mac folks click macOS; stop shoving `.exe` files into a Mac and chanting incantations.

> The macOS build is **Universal** (Apple Silicon + Intel), cross-compiled on a macOS runner in GitHub Actions (a Windows box can't produce it — Apple's toolchain insists on running on a Mac). Latest: Release [`client-macos-v0.3.1`](https://github.com/mycyg/requirement-master/releases/tag/client-macos-v0.3.1).
> ⚠️ It's an **unsigned test build** — Gatekeeper blocks the first open, so **right-click → Open** for internal testing. Want a frictionless double-click? That takes a paid Apple Developer signature + notarization. The Apple tax — you know the deal.

**Linux / macOS helper script:**

```bash
curl -fsSL http://192.168.5.53:8080/client/install.sh | bash
```

Mostly for install/launch help; the full frosted-glass desktop experience is the Windows Tauri client.

---

## First desktop launch

Four steps and you're working:

1. Enter the server IP, e.g. `192.168.5.53`
2. Pick a nickname
3. Choose a local work folder
4. Finish device registration

Drive sync currently offers **Off / Download-only**; two-way sync is in protective beta — file sync done right is a productivity tool, done wrong it's disk fireworks, so we're playing it safe.

---

## Dev

```powershell
# backend
python -m uvicorn main:app --app-dir app --reload --host 127.0.0.1 --port 8080

# web dispatch deck
npm run dev --workspace=web

# desktop webview shell
npm run dev --workspace=client-tauri -- --host 127.0.0.1 --port 5174
```

## Verify before you push

```powershell
# backend smoke (no LLM, full workflow on a temp SQLite)
python scripts\smoke_workflow.py

# full build (shared + web + client webview, incl. tsc typecheck)
npm run build

# web E2E (spins its own backend)
cd web; npx playwright test --project=chromium

# only if you touched the Rust client
cargo check --manifest-path client-tauri\src-tauri\Cargo.toml
npm run tauri:build --workspace=client-tauri
```

macOS Universal build (runs on a macOS CI runner):

```bash
npm run tauri:build --workspace=client-tauri -- \
  --bundles dmg,app \
  --target universal-apple-darwin \
  --no-sign
```

## Deploy

```powershell
npm run build
python scripts\deploy.py        # backend app/ + restart yqgl-web
python scripts\deploy_web.py    # atomic web/dist swap, zero 404 window
curl http://192.168.5.53:8080/api/health
```

All three remote services should be active + enabled:

- `yqgl-web` — the main service, and it **must run a single worker.** The SSE push bus, the presence map, and the dedup state are all in-process singletons; a second worker split-brains them (events go out, anyone connected to the other worker never receives them, and nothing errors).
- `yqgl-asr` — speech-to-text (GPU). When it's down the frontend degrades gracefully instead of throwing `Unexpected end of JSON input` in your face.
- `yqgl-tts` — text-to-speech (GPU), same deal.

---

## Repo layout

```text
app/                  FastAPI backend: models, routes, permissions, services
web/                  browser dispatch + admin app (React + strict TS)
client-tauri/         Rust + Tauri v2 frosted-glass desktop (src-tauri = Rust, web-src = its webview)
client/               one-liner install, launch scripts, legacy-tray compat
shared/               shared frontend lib: UI / types / API client
scripts/              deploy, smoke, E2E, install verification
systemd/              yqgl-web / yqgl-asr / yqgl-tts unit files
screenshots/readme/   clean README-only screenshots
```

## Stack

Backend: FastAPI + SQLAlchemy 2 + SQLite (WAL, single worker). LLM: DeepSeek via its Anthropic-compatible API (no tool_use; strict-JSON output). Frontend: React + Vite + shared design tokens. Desktop: Tauri v2 + Rust (transparent window + acrylic + tray + deep links).

## License

MIT. Go wild — just don't use error screenshots as marketing material.

---

> Want the Chinese version? 👉 [中文 README](README.md)
> Think the docs are bad? Open an issue — docs are code too.
