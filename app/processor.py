import asyncio
import json
import logging
from dataclasses import dataclass

from app import naming
from app.commands import HELP_TEXT
from app.line_client import source_id_of
from app.mapping import Mapping

logger = logging.getLogger(__name__)

MEDIA_TYPES = {"image", "file", "video", "audio"}

MIME_BY_TYPE = {
    "image": "image/jpeg",
    "video": "video/mp4",
    "audio": "audio/m4a",
    "file": "application/octet-stream",
}

_inflight: set[str] = set()
_inflight_lock = asyncio.Lock()


@dataclass
class Deps:
    mapping: Mapping
    drive: object
    line: object
    root_folder_id: str
    max_file_mb: int = 200
    error_replies: bool = True
    sidecar_json: bool = False


def _write_sidecar(event, deps: Deps, folder_id: str, filename: str, existing) -> None:
    """Upload `<stem>.json` next to the saved media file. Best-effort: the caller
    logs failures and never lets them undo the media save."""
    source = event.source
    message = event.message
    payload = {
        "groupId": deps.line.group_id_of(source),
        "userId": getattr(source, "user_id", None),
        "messageId": message.id,
        "sourceId": source_id_of(source),
        "timestamp": event.timestamp,
        "type": message.type,
        "filename": filename,
    }
    # A media file named *.json would share the sidecar's name; keep them apart.
    name = naming.resolve_unique(naming.sidecar_name(filename), set(existing) | {filename})
    deps.drive.upload_bytes(
        folder_id=folder_id,
        filename=name,
        data=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        mime_type="application/json",
        # Deliberately NOT lineMessageId: exists_message() must key on the media file.
        app_properties={"lineSidecarFor": message.id, "lineSourceId": source_id_of(source)},
    )
    logger.info("Saved sidecar %s for %s", name, message.id)


async def _ensure_folder(source, deps: Deps) -> str:
    source_id = source_id_of(source)
    async with deps.mapping.lock:
        folder_id = deps.mapping.folder_id_for(source_id)
        if folder_id:
            return folder_id
        group_id = deps.line.group_id_of(source)
        summary = deps.line.get_group_summary_name(group_id) if group_id else None
        name = deps.mapping.folder_name_for(source_id, fallback=summary or source_id)
        folder_id = deps.drive.ensure_folder(name, deps.root_folder_id)
        deps.mapping.set_folder(source_id, name, folder_id)
        deps.drive.save_mapping(deps.mapping.to_dict())
        return folder_id


async def process_media_event(event, deps: Deps) -> None:
    source = event.source
    source_id = source_id_of(source)
    message = event.message
    msg_type = message.type
    message_id = message.id

    async with _inflight_lock:
        if message_id in _inflight:
            logger.info("Already processing %s; skip", message_id)
            return
        _inflight.add(message_id)

    try:
        try:
            folder_id = await _ensure_folder(source, deps)
            if deps.drive.exists_message(folder_id, message_id):
                logger.info("Skip duplicate %s in %s", message_id, source_id)
                return
            original = getattr(message, "file_name", None)
            base = naming.build_filename(msg_type, event.timestamp, original_name=original)
            existing = deps.drive.list_names_in_folder(folder_id)
            filename = naming.resolve_unique(base, existing)
            data = deps.line.download_content(message_id)
            deps.drive.upload(
                folder_id=folder_id,
                filename=filename,
                data=data,
                mime_type=MIME_BY_TYPE.get(msg_type, "application/octet-stream"),
                message_id=message_id,
                source_id=source_id,
            )
            logger.info("Saved %s as %s", message_id, filename)
            if deps.sidecar_json:
                try:
                    _write_sidecar(event, deps, folder_id, filename, existing)
                except Exception:  # noqa: BLE001 — sidecar is best-effort; media is already saved
                    logger.exception("Failed to write sidecar for %s", message_id)
        except Exception:  # noqa: BLE001 — report to chat, never crash the worker
            logger.exception("Failed to save %s", message_id)
            if not deps.error_replies:
                logger.info("ERROR_REPLIES disabled; not notifying %s", source_id)
            else:
                try:
                    deps.line.push_text(source_id, "⚠️ บันทึกไฟล์ลง Drive ไม่สำเร็จ กรุณาลองส่งใหม่อีกครั้ง")
                except Exception:
                    logger.exception("Failed to push error notice")
    finally:
        async with _inflight_lock:
            _inflight.discard(message_id)


async def handle_command_event(verb: str, arg: str, source, deps: Deps) -> None:
    source_id = source_id_of(source)
    if verb == "help":
        deps.line.push_text(source_id, HELP_TEXT)
        return
    if verb == "folder":
        if not arg:
            deps.line.push_text(source_id, "ใช้: /folder <ชื่อโฟลเดอร์>")
            return
        async with deps.mapping.lock:
            deps.mapping.rename(source_id, arg)
            folder_id = deps.mapping.folder_id_for(source_id)
            if folder_id:
                deps.drive.rename_folder(folder_id, arg)
            deps.drive.save_mapping(deps.mapping.to_dict())
        deps.line.push_text(source_id, f"เปลี่ยนชื่อโฟลเดอร์เป็น: {arg} ✅")
        return
    deps.line.push_text(source_id, "ไม่รู้จักคำสั่งนี้ ลอง /help")
