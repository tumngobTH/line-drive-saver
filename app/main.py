import asyncio
import logging

from fastapi import FastAPI, Header, HTTPException, Request
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent

from app.commands import parse_command
from app.config import get_settings
from app.drive import DriveStore, build_service
from app.line_client import LineClient
from app.mapping import Mapping
from app.processor import MEDIA_TYPES, Deps, handle_command_event, process_media_event

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="line-drive-saver")


class _State:
    line: LineClient = None  # type: ignore[assignment]
    deps: Deps = None  # type: ignore[assignment]


state = _State()


@app.on_event("startup")
def _startup() -> None:
    settings = get_settings()
    state.line = LineClient(settings.line_channel_secret, settings.line_channel_access_token)
    service = build_service(settings.google_application_credentials)
    drive = DriveStore(service, settings.shared_drive_id, settings.root_folder_id, settings.mapping_filename)
    mapping = Mapping(drive.load_mapping())
    state.deps = Deps(
        mapping=mapping,
        drive=drive,
        line=state.line,
        root_folder_id=settings.root_folder_id,
        max_file_mb=settings.max_file_mb,
        error_replies=settings.error_replies,
        sidecar_json=settings.sidecar_json,
    )
    logger.info("Startup complete; %d chats mapped", len(mapping.to_dict()))


@app.get("/")
def health() -> dict:
    return {"status": "ok"}


async def _dispatch(events) -> None:
    # Process every event WITHIN the request so the work finishes before we
    # return 200. This lets Cloud Run run with CPU throttling on (billed per
    # request) instead of CPU-always-allocated: a detached background task
    # would be starved once the response returns.
    coros = []
    for event in events:
        if not isinstance(event, MessageEvent):
            continue
        msg_type = event.message.type
        if msg_type in MEDIA_TYPES:
            coros.append(process_media_event(event, state.deps))
        elif msg_type == "text":
            parsed = parse_command(event.message.text)
            if parsed:
                verb, arg = parsed
                coros.append(handle_command_event(verb, arg, event.source, state.deps))
    if not coros:
        return
    # return_exceptions: a failing handler must never turn the webhook into a
    # non-200 (LINE would retry the whole batch). Handlers log their own errors;
    # anything that still escapes is logged here.
    results = await asyncio.gather(*coros, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            logger.error("Event handler raised", exc_info=result)


@app.post("/callback")
async def callback(request: Request, x_line_signature: str = Header(default="")):
    body = (await request.body()).decode("utf-8")
    try:
        events = state.line.parse(body, x_line_signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="invalid signature")
    await _dispatch(events)
    return {"status": "ok"}
