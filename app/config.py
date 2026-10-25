from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    line_channel_secret: str
    line_channel_access_token: str
    google_application_credentials: str
    shared_drive_id: str
    root_folder_id: str
    max_file_mb: int = 200
    mapping_filename: str = "line-drive-mapping.json"
    # Push a Thai error notice to the chat when a save fails. Set to false for
    # services that must stay fully silent (e.g. line-slip-saver); failures are
    # still logged. pydantic parses "false" / "0" / "no" / "off" as False.
    error_replies: bool = True
    # Also upload `<stem>.json` next to every saved media file (sender, message
    # id, timestamp). Off by default so the original line-drive-saver service is
    # unchanged on redeploy; line-slip-saver sets SIDECAR_JSON=true.
    sidecar_json: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
