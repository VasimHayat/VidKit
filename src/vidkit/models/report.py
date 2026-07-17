"""Job result and batch report models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class JobResult(BaseModel):
    """Outcome of processing one input file."""

    input_path: Path
    status: JobStatus
    outputs: list[Path] = Field(default_factory=list)
    elapsed_seconds: float = 0.0
    error_type: str | None = None
    error_message: str | None = None

    @classmethod
    def skipped(
        cls, input_path: Path, reason: str, error_type: str = "InvalidMediaError"
    ) -> JobResult:
        return cls(
            input_path=input_path,
            status=JobStatus.SKIPPED,
            error_type=error_type,
            error_message=reason,
        )

    @classmethod
    def failed(cls, input_path: Path, exc: BaseException, elapsed: float = 0.0) -> JobResult:
        return cls(
            input_path=input_path,
            status=JobStatus.FAILED,
            elapsed_seconds=elapsed,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )


class JobReport(BaseModel):
    """Aggregate of a batch run, printable as a table and serializable to JSON."""

    command: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    interrupted: bool = False
    results: list[JobResult] = Field(default_factory=list)

    def add(self, result: JobResult) -> None:
        self.results.append(result)

    def finish(self) -> None:
        self.finished_at = datetime.now(UTC)

    def count(self, status: JobStatus) -> int:
        return sum(1 for r in self.results if r.status == status)

    @property
    def succeeded(self) -> int:
        return self.count(JobStatus.SUCCEEDED)

    @property
    def failed(self) -> int:
        return self.count(JobStatus.FAILED)

    @property
    def skipped(self) -> int:
        return self.count(JobStatus.SKIPPED)

    @property
    def total_elapsed(self) -> float:
        return sum(r.elapsed_seconds for r in self.results)

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
