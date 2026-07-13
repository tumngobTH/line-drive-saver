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
    drive = DriveStore(service, settings.shared_drive_id, settings.root_folder_id)
    mapping = Mapping(drive.load_mapping(settings.mapping_filename))
    state.deps = Deps(
        mapping=mapping,
        drive=drive,
        line=state.line,
        root_folder_id=settings.root_folder_id,
        max_file_mb=settings.max_file_mb,
    )
    logger.info("Startup complete; %d chats mapped", len(mapping.to_dict()))


@app.get("/")
def health() -> dict:
    return {"status": "ok"}


def _dispatch(events) -> None:
    for event in events:
        if not isinstance(event, MessageEvent):
            continue
        msg_type = event.message.type
        if msg_type in MEDIA_TYPES:
            asyncio.create_task(process_media_event(event, state.deps))
        elif msg_type == "text":
            parsed = parse_command(event.message.text)
            if parsed:
                verb, arg = parsed
                asyncio.create_task(
                    handle_command_event(verb, arg, event.source, state.deps)
                )


@app.post("/callback")
async def callback(request: Request, x_line_signature: str = Header(default="")):
    body = (await request.body()).decode("utf-8")
    try:
        events = state.line.parse(body, x_line_signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="invalid signature")
    _dispatch(events)
    return {"status": "ok"}
