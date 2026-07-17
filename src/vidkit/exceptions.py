"""Typed exception hierarchy for VidKit.

Every exception carries the process exit code the CLI must use when it is the
terminal failure. The full table is documented in README.md and must stay in
sync with ``EXIT_*`` constants below.
"""

from __future__ import annotations

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_USAGE = 2
EXIT_FFMPEG_MISSING = 3
EXIT_INVALID_MEDIA = 4
EXIT_SPLIT_PLAN = 5
EXIT_FFMPEG_FAILED = 6
EXIT_OUTPUT_EXISTS = 7
EXIT_VERIFICATION = 8
EXIT_PARTIAL_FAILURE = 10
EXIT_INTERRUPTED = 130


class VidKitError(Exception):
    """Base class for all VidKit failures."""

    exit_code: int = EXIT_UNEXPECTED

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class FFmpegNotFoundError(VidKitError):
    """ffmpeg or ffprobe binary could not be located."""

    exit_code = EXIT_FFMPEG_MISSING


class FFmpegVersionError(VidKitError):
    """ffmpeg/ffprobe found but older than the minimum supported version."""

    exit_code = EXIT_FFMPEG_MISSING


class FFmpegExecutionError(VidKitError):
    """An ffmpeg/ffprobe invocation exited non-zero or timed out."""

    exit_code = EXIT_FFMPEG_FAILED

    def __init__(self, message: str, *, argv: list[str], stderr: str = "") -> None:
        super().__init__(message)
        self.argv = argv
        self.stderr = stderr

    def __str__(self) -> str:
        tail = self.stderr.strip().splitlines()[-8:]
        detail = "\n".join(tail)
        return f"{self.message}\ncommand: {' '.join(self.argv)}\nstderr:\n{detail}"


class InvalidMediaError(VidKitError):
    """Input is missing, unreadable, or not a playable video container."""

    exit_code = EXIT_INVALID_MEDIA


class SplitPlanError(VidKitError):
    """A split plan could not be computed (bad durations, overlaps, ranges)."""

    exit_code = EXIT_SPLIT_PLAN


class OutputExistsError(VidKitError):
    """Output path already exists and --overwrite was not given."""

    exit_code = EXIT_OUTPUT_EXISTS


class VerificationError(VidKitError):
    """Post-clean ffprobe verification found residual metadata tags."""

    exit_code = EXIT_VERIFICATION


class JobCancelledError(VidKitError):
    """The job was interrupted (SIGINT) before completion."""

    exit_code = EXIT_INTERRUPTED


def exit_code_for_error_name(error_type: str | None) -> int:
    """Map a stored exception class name (from a JobResult) to its exit code."""

    def walk(cls: type[VidKitError]) -> int | None:
        if cls.__name__ == error_type:
            return cls.exit_code
        for sub in cls.__subclasses__():
            found = walk(sub)
            if found is not None:
                return found
        return None

    return walk(VidKitError) or EXIT_UNEXPECTED
