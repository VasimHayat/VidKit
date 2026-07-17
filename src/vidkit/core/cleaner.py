"""Metadata removal via stream copy, with ffprobe verification afterwards."""

from __future__ import annotations

from typing import TYPE_CHECKING

from vidkit.core.outputs import atomic_output, check_output, clean_output_path
from vidkit.exceptions import VerificationError
from vidkit.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from vidkit.core.ffmpeg import CancelEvent, FFmpeg
    from vidkit.core.probe import ProbeService
    from vidkit.models import MediaInfo

log = get_logger(__name__)

# Structural container fields that ffprobe surfaces as "tags" but that a
# stream-copy remux cannot omit. Format level: the mp4 ftyp box (brand
# identifiers set by the muxer from codec/flag choices, never copied from
# input metadata). Stream level: mp4 hdlr/vendor boxes and track language —
# only ffmpeg's own neutral defaults are accepted, so a leaked device string
# like "Core Media Video" in handler_name still fails verification.
_ALLOWED_FORMAT_TAGS: frozenset[str] = frozenset(
    {"major_brand", "minor_version", "compatible_brands"}
)
_ALLOWED_STREAM_TAGS: dict[str, frozenset[str]] = {
    "handler_name": frozenset(
        {"VideoHandler", "SoundHandler", "SubtitleHandler", "DataHandler", "TimecodeHandler"}
    ),
    "vendor_id": frozenset({"[0][0][0][0]", "FFMP"}),
    "language": frozenset({"und"}),
}


def build_clean_command(input_path: Path, output_path: Path) -> list[str]:
    """The exact ffmpeg argv (minus binary) for a metadata-stripping remux."""
    return [
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-c",
        "copy",
        "-fflags",
        "+bitexact",
        "-flags:v",
        "+bitexact",
        "-flags:a",
        "+bitexact",
        str(output_path),
    ]


def find_residual_tags(info: MediaInfo) -> list[str]:
    """Return human-readable descriptions of tags that should not be present."""
    residual: list[str] = [
        f"format tag {key}={value!r}"
        for key, value in info.format_tags.items()
        if key.lower() not in _ALLOWED_FORMAT_TAGS
    ]
    for stream in info.streams:
        for key, value in stream.tags.items():
            allowed = _ALLOWED_STREAM_TAGS.get(key)
            if allowed is None or value not in allowed:
                residual.append(f"stream {stream.index} tag {key}={value!r}")
    if info.chapter_count > 0:
        residual.append(f"{info.chapter_count} chapter(s) still present")
    return residual


class CleanerService:
    def __init__(self, ffmpeg: FFmpeg, probe: ProbeService) -> None:
        self._ffmpeg = ffmpeg
        self._probe = probe

    def clean(
        self,
        input_path: Path,
        output_dir: Path,
        *,
        overwrite: bool = False,
        cancel_event: CancelEvent | None = None,
    ) -> Path:
        """Strip all metadata from ``input_path``; returns the output path.

        Raises InvalidMediaError, OutputExistsError, FFmpegExecutionError, or
        VerificationError. The output only appears once fully written and
        verified (temp file + atomic rename).
        """
        self._probe.probe_video(input_path, cancel_event=cancel_event)
        output_path = clean_output_path(input_path, output_dir)
        check_output(input_path, output_path, overwrite=overwrite)

        with atomic_output(output_path) as tmp_path:
            argv = build_clean_command(input_path, tmp_path)
            log.info("clean_start", input=str(input_path), output=str(output_path))
            self._ffmpeg.run_ffmpeg(argv, cancel_event=cancel_event)
            self._verify(tmp_path, cancel_event=cancel_event)

        log.info("clean_done", input=str(input_path), output=str(output_path))
        return output_path

    def _verify(self, path: Path, *, cancel_event: CancelEvent | None = None) -> None:
        info = self._probe.probe(path, cancel_event=cancel_event)
        residual = find_residual_tags(info)
        if residual:
            raise VerificationError(
                f"metadata remains after clean of {path.name}: " + "; ".join(residual)
            )
