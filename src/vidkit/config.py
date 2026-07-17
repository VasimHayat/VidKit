"""Settings: env vars (``VIDKIT_``-prefixed) > optional ``vidkit.toml`` > defaults.

CLI flags override everything; the CLI layer applies them on top of the
resolved ``Settings`` instance.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

MAX_WORKERS_CAP = 8


def default_workers() -> int:
    return min(os.cpu_count() or 1, MAX_WORKERS_CAP)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VIDKIT_",
        toml_file="vidkit.toml",
        extra="ignore",
    )

    ffmpeg_path: Path | None = None
    ffprobe_path: Path | None = None
    output_dir: Path = Path("./vidkit_out")
    workers: int = Field(default_factory=default_workers, ge=1)
    ffmpeg_timeout: float = Field(default=3600.0, gt=0)
    log_level: str = "INFO"
    log_format: Literal["auto", "console", "json"] = "auto"

    @field_validator("workers")
    @classmethod
    def _cap_workers(cls, v: int) -> int:
        return min(v, MAX_WORKERS_CAP)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Precedence (first wins): explicit kwargs, environment, vidkit.toml.
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls),
        )


def load_settings() -> Settings:
    return Settings()
