# line-drive-saver

Saves every file shared in a LINE group chat to Google Drive — one folder per
chat, each file renamed with a `yyyymmdd` date prefix.

## Setup

### 1. LINE Messaging API channel
- Create a Messaging API channel in the LINE Developers console.
- Copy the **Channel secret** and issue a long-lived **Channel access token**.
- Disable auto-reply; enable **Use webhook**.
- Add the bot to your group(s), and enable "Allow bot to join group chats".

### 2. Service account + Shared Drive
- Service account: `service-account@n8nproject-493006.iam.gserviceaccount.com`.
- Ensure the **Google Drive API** is enabled in project `n8nproject-493006`.
- Create (or pick) a **Shared Drive**. Add the service-account email as a
  **Content manager** member.
- Inside that Shared Drive, note the Shared Drive id (`SHARED_DRIVE_ID`) and the
  folder id to use as the root for chat folders + the mapping JSON
  (`ROOT_FOLDER_ID`). Using the Shared Drive root itself for both is fine.
- Download the service-account JSON key and save it as `service-account.json`
  (git-ignored). If no key file exists, create one in the GCP console →
  IAM & Admin → Service Accounts → Keys → Add key.

### 3. Env
Copy `.env.example` to `.env` and fill in every value.

## Run locally
```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
# expose to LINE:
ngrok http 8000    # put https://<id>.ngrok.app/callback in the channel webhook URL
```

## Test
```bash
.venv/Scripts/python -m pytest -v
```

## Deploy (Cloud Run)
```bash
gcloud run deploy line-drive-saver \
  --source . \
  --region asia-southeast1 \
  --min-instances 1 --max-instances 1 \
  --no-cpu-throttling \
  --set-env-vars SHARED_DRIVE_ID=...,ROOT_FOLDER_ID=...,MAPPING_FILENAME=line-drive-mapping.json \
  --set-secrets LINE_CHANNEL_SECRET=line-secret:latest,LINE_CHANNEL_ACCESS_TOKEN=line-token:latest,GOOGLE_APPLICATION_CREDENTIALS=/secrets/sa.json:...
```
Then set the channel webhook URL to `https://<cloud-run-url>/callback`.

> `--no-cpu-throttling` keeps the CPU allocated so background upload tasks finish
> after the 200 response. `--min/max-instances 1` pins to one instance so the
> mapping JSON never has concurrent writers.
