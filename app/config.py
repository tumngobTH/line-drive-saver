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


@lru_cache
def get_settings() -> Settings:
    return Settings()
