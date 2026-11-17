from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    telegram_bot_token: str = ""
    api_football_key: str = ""
    api_football_host: str = "api-football-v1.p.rapidapi.com"
    football_data_token: str = ""
    history_seasons: int = 5
    cache_ttl_hours: int = 6
    league_ids: str = "39,140,135,78,61,2"
    timezone: str = "UTC"
    digest_time: str = "09:00"
    allowed_user_ids: str = ""

    @property
    def leagues(self) -> list[int]:
        return [int(x) for x in self.league_ids.split(",") if x.strip().isdigit()]

    @property
    def allowed_users(self) -> set[int]:
        return {int(x) for x in self.allowed_user_ids.split(",") if x.strip().isdigit()}

    @property
    def provider(self) -> str:
        if self.api_football_key:
            return "api-football"
        if self.football_data_token:
            return "football-data"
        return "demo"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def data_dir() -> str:
    path = os.environ.get("DATA_DIR", ".data")
    os.makedirs(path, exist_ok=True)
    return path
