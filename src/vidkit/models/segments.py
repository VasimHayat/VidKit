"""Models describing split plans."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SplitMode(StrEnum):
    DURATION = "by-duration"
    COUNT = "by-count"
    TIMESTAMPS = "by-timestamps"


class Segment(BaseModel):
    """A half-open [start, end) range in seconds within the source video."""

    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=0)
    start: float = Field(ge=0)
    end: float = Field(gt=0)

    @model_validator(mode="after")
    def _check_order(self) -> Segment:
        if self.end <= self.start:
            msg = f"segment end ({self.end}) must be greater than start ({self.start})"
            raise ValueError(msg)
        return self

    @property
    def duration(self) -> float:
        return self.end - self.start


class SegmentPlan(BaseModel):
    """A fully validated plan for splitting one source file."""

    model_config = ConfigDict(frozen=True)

    source: Path
    mode: SplitMode
    total_duration: float = Field(gt=0)
    segments: tuple[Segment, ...] = Field(min_length=1)
    precise: bool = False

    @property
    def part_count(self) -> int:
        return len(self.segments)
