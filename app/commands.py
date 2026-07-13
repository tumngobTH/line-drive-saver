HELP_TEXT = (
    "คำสั่งที่ใช้ได้:\n"
    "/folder <ชื่อ> — ตั้งชื่อโฟลเดอร์ของแชตนี้ใน Drive\n"
    "/help — แสดงคำสั่ง\n"
    "ไฟล์ที่แชร์ในแชตนี้จะถูกบันทึกลง Google Drive อัตโนมัติ"
)


def parse_command(text: str) -> tuple[str, str] | None:
    """Return (verb, arg) for a '/command', else None."""
    if not text or not text.startswith("/"):
        return None
    parts = text[1:].split(maxsplit=1)
    if not parts:
        return None
    verb = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    return verb, arg
