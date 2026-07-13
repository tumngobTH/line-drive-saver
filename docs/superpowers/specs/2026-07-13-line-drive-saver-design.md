# LINE → Google Drive File Saver — Design

**Date:** 2026-07-13
**Status:** Approved (design), pending implementation plan
**Owner:** Kim

## 1. Purpose

A LINE bot that automatically saves every file shared in a LINE group chat
into Google Drive, organised into one Drive folder per chat, with each file
renamed to carry a `yyyymmdd` date prefix.

## 2. Scope

**In scope**
- Capture all shared media message types: **images, files/documents, videos, audio/voice**.
- One Drive folder per LINE chat (group / room / 1:1), stored in a Shared Drive.
- Friendly folder names via a mapping, with a `/folder <name>` rename command.
- Date-prefixed filenames from the share event timestamp (Asia/Bangkok).
- Dedupe against LINE's webhook retries.
- Silent on success; reply only on save error or to a command.

**Out of scope (YAGNI)**
- No OCR / content parsing of the saved files.
- No web UI or admin dashboard.
- No multi-tenant support beyond one LINE channel + one Shared Drive.
- No Pub/Sub / Cloud Tasks queue (revisit only if volume demands it).

## 3. Architecture

**Approach A — single always-on Cloud Run instance, ack-fast + background processing.**

```
LINE group ──file──▶ LINE Platform ──POST /callback──▶ FastAPI (Cloud Run)
                                                          │ 1. verify signature
                                                          │ 2. return 200 immediately
                                                          ▼
                                              background task (asyncio)
                                                  ├─ resolve chat folder (mapping)
                                                  ├─ dedupe check (appProperties)
                                                  ├─ download content from LINE
                                                  ├─ build filename
                                                  └─ upload to Shared Drive
```

- **Runtime:** Python 3.12, FastAPI + `uvicorn`.
- **Cloud Run:** region `asia-southeast1`, `min-instances=1`, `max-instances=1`,
  CPU **always allocated** (so background tasks complete after the 200 response).
  The single pinned instance also removes write races on the mapping JSON.
- **Auth to Drive:** Google **service account**, targeting a **Shared Drive**
  the service account has been granted access to.

### Rejected alternatives
- **B — synchronous (process inside the webhook request):** simplest code, but a
  large video download+upload can exceed LINE's webhook timeout and trigger retries.
- **C — Pub/Sub + Cloud Tasks queue:** bulletproof at scale, overkill for this volume.

### Cost note
Always-on (`min=1`) ≈ USD $5–12/month. A `min=0` (scale-to-zero, near-free-when-idle)
variant is a one-line change; the trade-off is occasional 1–2s cold starts and needing
more defensive handling of dedupe / concurrent writes. Default = always-on.

## 4. Modules

| Module | Responsibility | Depends on |
|---|---|---|
| `app/main.py` | FastAPI app; `POST /callback`; signature verify; return 200; dispatch background task | `line_client`, `config` |
| `app/line_client.py` | Parse webhook events; download message content from LINE Content API; fetch group-summary name; send reply/push | `line-bot-sdk` v3 |
| `app/drive.py` | Ensure/create Drive folder; upload file (resumable for large); dedupe query via `appProperties` | `google-api-python-client`, `google-auth` |
| `app/mapping.py` | Load/save the `groupId → {folderName, folderId}` JSON in the Shared Drive; resolve folder for a source; in-process asyncio lock around read-modify-write | `drive` |
| `app/naming.py` | Build the filename (date prefix, per-type, sanitize, collision suffix) | stdlib |
| `app/commands.py` | Parse & handle text commands: `/folder <name>`, `/help` | `mapping`, `line_client` |
| `app/config.py` | Typed settings from env (`pydantic-settings`) | — |
| `tests/` | Unit tests (mocked LINE + Drive) | `pytest` |

Each module has a single purpose and a narrow interface; `drive.py` and
`line_client.py` are the only modules that touch external APIs, so everything
else is trivially unit-testable with mocks.

## 5. Data flow (detailed)

1. File shared in a LINE chat → LINE `POST /callback` with `X-Line-Signature`.
2. `main.py` verifies the signature against `LINE_CHANNEL_SECRET`. Invalid → `400`.
3. Return `200` immediately; enqueue an asyncio background task per media event.
4. Background task, for each message of type `image` / `file` / `video` / `audio`:
   1. Resolve source id (`groupId` / `roomId` / `userId`).
   2. Resolve folder name: mapping entry → else LINE group-summary name → else raw id.
      Ensure the Drive folder exists (create under `ROOT_FOLDER_ID` if missing),
      cache its `folderId` back into the mapping.
   3. **Dedupe:** query the folder for a file with `appProperties.lineMessageId == messageId`.
      If found, skip (a retry).
   4. Download the content bytes from the LINE Content API.
   5. Build the filename (§6).
   6. Upload to the folder with `appProperties = { lineMessageId, lineSourceId }`.
5. Text messages starting with `/` → `commands.py` (see §7).

## 6. Filename rules

- **Date** = the share **event timestamp** (`event.timestamp`, ms epoch) converted to
  **Asia/Bangkok**, formatted `yyyymmdd`.
- **Documents (`file`)** keep their original name: `20260713_Q2-report.pdf`.
- **Images / video / audio** (no original name): `20260713_153012_image.jpg`
  (`HHMMSS` from the same event time; type keyword `image`/`video`/`audio`;
  extension inferred from the LINE content type — e.g. `jpg`, `mp4`, `m4a`).
- **Collision** (same target name already exists, different `lineMessageId`):
  append `_2`, `_3`, …
- **Sanitize:** strip path separators and control characters; **preserve Thai
  characters**; trim length to a safe max.

## 7. Commands

- `/folder <name>` — rename this chat's folder: update the mapping's `folderName`
  and rename the Drive folder (folderId unchanged). Reply with confirmation.
- `/help` — reply with a short usage message (Thai).
- Unknown `/command` — reply with a short "unknown command, try /help".

## 8. Error handling

- **Invalid signature** → `400`, no processing.
- **LINE content download fails** (expired / too large) → log; reply an error notice
  to the chat.
- **Drive API errors** → retry with exponential backoff (a few attempts); on final
  failure, reply an error notice.
- **Mapping JSON read-modify-write** → guarded by an in-process asyncio lock (safe
  because the service is pinned to a single instance).
- **Large files** → use Drive **resumable upload**; enforce a configurable max-size guard.

## 9. Config & secrets

Environment variables (never committed):

| Var | Meaning |
|---|---|
| `LINE_CHANNEL_SECRET` | Verify inbound webhook signatures |
| `LINE_CHANNEL_ACCESS_TOKEN` | Call LINE Content / reply / push APIs |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to mounted service-account JSON |
| `SHARED_DRIVE_ID` | Target Shared Drive |
| `ROOT_FOLDER_ID` | Folder in the Shared Drive that holds per-chat folders + the mapping JSON |
| `MAX_FILE_MB` | Optional upload size guard (default e.g. 200) |

Local: `.env` (git-ignored). Cloud Run: env vars + Secret Manager for the SA JSON.

## 10. Testing

- **Unit (pytest, mocked LINE + Drive):** filename building & sanitize, collision
  suffixing, folder resolution precedence, dedupe decision, command parsing.
- **Manual:** run `uvicorn` locally, expose via **ngrok**, point a throwaway LINE
  group's webhook at it, share each media type, confirm Drive results.
- **Deploy smoke test:** after Cloud Run deploy, share one file, confirm it lands.

## 11. Deliverables

- The `line-drive-saver` project (modules above), `Dockerfile`, `requirements.txt`,
  `.env.example`, `.gitignore`, `README.md` (setup: LINE channel, service account +
  Shared Drive sharing, deploy), and `tests/`.
- A `CLAUDE.md` for the project following the house pattern.

## 12. Open items / assumptions

- Assumes a Google Workspace **Shared Drive** exists (or will be created) and the
  service account is granted Content-Manager access to it.
- Assumes one LINE Messaging API channel dedicated to this bot.
- `min=1` always-on chosen for simplicity; switch to `min=0` if cost-minimising.
