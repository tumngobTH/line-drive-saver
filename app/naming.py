import re
from datetime import datetime, timedelta, timezone

BANGKOK = timezone(timedelta(hours=7))

EXT_BY_TYPE = {"image": "jpg", "video": "mp4", "audio": "m4a"}

# Strip path separators and ASCII control chars; keep everything else (incl. Thai).
_ILLEGAL = re.compile(r"[\\/\x00-\x1f]")


def _sanitize(name: str) -> str:
    cleaned = _ILLEGAL.sub("", name).strip()
    return cleaned[:200] or "file"


def date_parts(ts_ms: int) -> tuple[str, str]:
    dt = datetime.fromtimestamp(ts_ms / 1000, BANGKOK)
    return dt.strftime("%Y%m%d"), dt.strftime("%H%M%S")


def build_filename(
    msg_type: str,
    ts_ms: int,
    original_name: str | None = None,
    ext: str | None = None,
) -> str:
    ymd, hms = date_parts(ts_ms)
    if msg_type == "file" and original_name:
        return f"{ymd}_{_sanitize(original_name)}"
    extension = ext or EXT_BY_TYPE.get(msg_type, "bin")
    return f"{ymd}_{hms}_{msg_type}.{extension}"


def _with_suffix(filename: str, n: int) -> str:
    stem, dot, ext = filename.rpartition(".")
    if dot:
        return f"{stem}_{n}.{ext}"
    return f"{filename}_{n}"


def sidecar_name(filename: str) -> str:
    """`<stem>.json` for a saved media filename (filename + .json if no extension)."""
    stem, dot, _ext = filename.rpartition(".")
    return f"{stem}.json" if dot else f"{filename}.json"


def resolve_unique(name: str, existing) -> str:
    if name not in existing:
        return name
    n = 2
    while _with_suffix(name, n) in existing:
        n += 1
    return _with_suffix(name, n)
