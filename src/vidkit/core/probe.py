"""Media inspection via ffprobe."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from vidkit.exceptions import FFmpegExecutionError, InvalidMediaError
from vidkit.logging import get_logger
from vidkit.models import MediaInfo, StreamInfo

if TYPE_CHECKING:
    from pathlib import Path

    from vidkit.core.ffmpeg import CancelEvent, FFmpeg

log = get_logger(__name__)


def _tags(node: dict[str, Any]) -> dict[str, str]:
    raw = node.get("tags") or {}
    return {str(k): str(v) for k, v in raw.items()}


class ProbeService:
    def __init__(self, ffmpeg: FFmpeg) -> None:
        self._ffmpeg = ffmpeg

    def probe(self, path: Path, *, cancel_event: CancelEvent | None = None) -> MediaInfo:
        """Inspect a file; raise InvalidMediaError for anything unplayable."""
        if not path.exists():
            raise InvalidMediaError(f"input does not exist: {path}")
        if not path.is_file():
            raise InvalidMediaError(f"input is not a file: {path}")

        args = [
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            "-show_chapters",
            str(path),
        ]
        try:
            raw = self._ffmpeg.run_ffprobe(args, cancel_event=cancel_event)
        except FFmpegExecutionError as exc:
            stderr = exc.stderr.strip()
            reason = stderr.splitlines()[-1] if stderr else "ffprobe failed"
            raise InvalidMediaError(f"not a readable media file: {path} ({reason})") from exc

        try:
            data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise InvalidMediaError(f"ffprobe returned unparseable output for: {path}") from exc

        fmt = data.get("format") or {}
        streams_raw = data.get("streams") or []
        if not streams_raw:
            raise InvalidMediaError(f"no media streams found in: {path}")

        duration_str = fmt.get("duration")
        if duration_str is None:
            raise InvalidMediaError(f"container reports no duration (corrupt?): {path}")
        duration = float(duration_str)
        if duration <= 0:
            raise InvalidMediaError(f"container reports non-positive duration: {path}")

        info = MediaInfo(
            path=path,
            format_name=str(fmt.get("format_name", "unknown")),
            duration=duration,
            size_bytes=int(fmt.get("size", 0)),
            bit_rate=int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
            streams=tuple(
                StreamInfo(
                    index=int(s.get("index", i)),
                    codec_type=str(s.get("codec_type", "unknown")),
                    codec_name=str(s.get("codec_name", "unknown")),
                    tags=_tags(s),
                )
                for i, s in enumerate(streams_raw)
            ),
            format_tags=_tags(fmt),
            chapter_count=len(data.get("chapters") or []),
        )
        log.debug(
            "probed",
            path=str(path),
            duration=info.duration,
            streams=len(info.streams),
            chapters=info.chapter_count,
        )
        return info

    def probe_video(self, path: Path, *, cancel_event: CancelEvent | None = None) -> MediaInfo:
        """Like probe() but additionally requires at least one video stream."""
        info = self.probe(path, cancel_event=cancel_event)
        if not info.has_video:
            raise InvalidMediaError(f"file has no video stream: {path}")
        return info
