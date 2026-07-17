"""Models describing probed media files."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class StreamInfo(BaseModel):
    """One stream (video/audio/subtitle/data) inside a container."""

    model_config = ConfigDict(frozen=True)

    index: int
    codec_type: str
    codec_name: str = "unknown"
    tags: dict[str, str] = Field(default_factory=dict)


class MediaInfo(BaseModel):
    """Container-level inspection result produced by ffprobe."""

    model_config = ConfigDict(frozen=True)

    path: Path
    format_name: str
    duration: float = Field(gt=0)
    size_bytes: int = Field(ge=0)
    bit_rate: int | None = None
    streams: tuple[StreamInfo, ...] = ()
    format_tags: dict[str, str] = Field(default_factory=dict)
    chapter_count: int = 0

    @property
    def has_video(self) -> bool:
        return any(s.codec_type == "video" for s in self.streams)

    @property
    def tag_inventory(self) -> dict[str, dict[str, str]]:
        """All metadata locations mapped to their tags (for display/verify)."""
        inventory: dict[str, dict[str, str]] = {}
        if self.format_tags:
            inventory["format"] = dict(self.format_tags)
        for stream in self.streams:
            if stream.tags:
                inventory[f"stream:{stream.index}:{stream.codec_type}"] = dict(stream.tags)
        return inventory
