# Mini-Spec: Cut Cloud Run cost — synchronous upload + CPU throttling

**Date:** 2026-10-28
**Type:** 3 (Rush Improvement)
**Repo:** `line-drive-saver` (serves both Cloud Run services: `line-drive-saver` and `line-slip-saver`, same image/source, different env)
**Project:** GCP `sjrlms-462004`, region `asia-southeast1`

## Problem
Both services run with `run.googleapis.com/cpu-throttling: false` ("CPU always allocated"). Cloud Run then bills the **full 1 vCPU + 512 MiB for the entire instance lifetime**, not per request. Because LINE groups send messages throughout the day, the instance rarely scales to zero, so it bills close to 24/7 for a workload that does a few seconds of real work. Estimated waste: ~$25–65/month **per service**.

Why it was set that way: `app/main.py` ACKs the LINE webhook immediately, then runs the Drive upload in a **detached `asyncio` background task** (`_spawn`). A detached task only keeps running after the HTTP response if CPU stays allocated — hence `cpu-throttling: false`.

## Goal
Bill **per request** (a couple of seconds per message) instead of 24/7, with **no change to behaviour** (still real-time, still one folder per chat, same naming/dedup/sidecar/commands).

## Non-goals
- **No "save every 4 hours" batching.** Infeasible and risky: LINE only lets you download a message's media for a short window after it arrives; deferring 4 h would lose files. It also wouldn't address the real cost driver.
- No change to Drive folder structure, naming, dedup, sidecar JSON, or `/folder` `/help` commands.
- No new routes, collections, or packages.

## Change
**`app/main.py` only:**
1. Make `_dispatch` an `async` coroutine that builds the per-event coroutines and `await`s them (via `asyncio.gather`) **inside** the request.
2. `callback` `await`s `_dispatch(events)` before returning `200`.
3. Remove the `_spawn` / `_background_tasks` machinery (no longer needed).

**Deploy config (both services):** redeploy from source with `--cpu-throttling` (request-based CPU). Keep `--min-instances=0`, `--max-instances=1`, memory `512Mi`, timeout `300s`.

## Risks & mitigations
- **LINE webhook latency.** Slip/image uploads are ~1–3 s — well inside LINE's webhook timeout. Large files (drive-saver allows up to 200 MB) could exceed it → LINE retries → but `exists_message` (keyed on `lineMessageId` appProperty) + the in-memory `_inflight` guard already prevent duplicate saves. Net effect: at worst a retry, never a dup.
- **Blocking LINE SDK calls on the event loop.** They already block the loop in today's detached-task design, so awaiting them inline is no regression; a single low-volume webhook has nothing else to serve meanwhile.

## Acceptance
1. `.venv/Scripts/python -m pytest -v` passes.
2. Live smoke: send an image to a mapped LINE group → file appears in the Shared Drive folder within a few seconds (unchanged behaviour).
3. Post-deploy: `cpu-throttling` reads `true`; billable instance time drops toward per-request.

## Rollback
Redeploy the previous revision, or re-run the deploy with `--no-cpu-throttling`. Config-only; no data migration.
