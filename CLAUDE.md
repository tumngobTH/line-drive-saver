# line-drive-saver

## Overview
LINE bot that saves files shared in group chats to Google Drive, one folder per
chat, filenames prefixed with the share date (yyyymmdd). See
`docs/superpowers/specs/2026-07-13-line-drive-saver-design.md`.

## Tech Stack
- FastAPI + line-bot-sdk v3 (Python 3.12)
- Google Drive via service account -> Shared Drive
- Deploy: Cloud Run (asia-southeast1, min=max=1, CPU always allocated)

## Project Structure
- `app/main.py` — FastAPI webhook + dispatch
- `app/processor.py` — orchestrates one event (save / command)
- `app/drive.py` — Drive wrapper (Shared Drive flags on every call)
- `app/line_client.py` — LINE SDK wrapper
- `app/mapping.py` — groupId -> folder mapping (persisted as JSON in Drive)
- `app/naming.py` — filename builder
- `app/commands.py` — /folder, /help

## Rules
- Never commit `.env` or `service-account*.json`.
- No new packages without approval.
- All calls that touch Drive must pass supportsAllDrives / driveId flags.
- Bot replies only on error or command; silent on successful save. The error
  notice is opt-out via `ERROR_REPLIES=false` (used by the `line-slip-saver`
  service) — failures are then log-only.
- With `SIDECAR_JSON=true` (default false; `line-slip-saver` only) every saved
  media file gets a `<stem>.json` sidecar (groupId/userId/messageId/sourceId/
  timestamp/type/filename). Sidecar is best-effort and must never undo the save.
- Reply/notice language: Thai.

## Testing
`.venv/Scripts/python -m pytest -v`
