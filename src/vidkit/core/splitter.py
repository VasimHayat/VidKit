"""Segment planning (pure math) and split execution."""

from __future__ import annotations

from typing import TYPE_CHECKING

from vidkit.core.outputs import atomic_output, check_output, part_output_path
from vidkit.exceptions import SplitPlanError
from vidkit.logging import get_logger
from vidkit.models import Segment, SegmentPlan, SplitMode

if TYPE_CHECKING:
    from pathlib import Path

    from vidkit.core.ffmpeg import CancelEvent, FFmpeg
    from vidkit.core.probe import ProbeService

log = get_logger(__name__)

# Segments shorter than this are almost certainly planning artifacts
# (float dust at the tail), not intentional clips.
MIN_SEGMENT_SECONDS = 0.05
_EPSILON = 1e-6


def plan_by_duration(total_duration: float, segment_duration: float) -> list[Segment]:
    """Equal-length segments; the final one may be shorter."""
    if total_duration <= 0:
        raise SplitPlanError(f"total duration must be positive, got {total_duration}")
    if segment_duration <= 0:
        raise SplitPlanError(f"segment duration must be positive, got {segment_duration}")
    segments: list[Segment] = []
    start = 0.0
    index = 0
    while start < total_duration - _EPSILON:
        end = min(start + segment_duration, total_duration)
        if end - start >= MIN_SEGMENT_SECONDS or not segments:
            segments.append(Segment(index=index, start=start, end=end))
            index += 1
        else:
            # Absorb a dust-sized tail into the previous segment.
            prev = segments.pop()
            segments.append(Segment(index=prev.index, start=prev.start, end=total_duration))
        start += segment_duration
    return segments


def plan_by_count(total_duration: float, count: int) -> list[Segment]:
    """Exactly ``count`` near-equal segments covering the whole duration."""
    if total_duration <= 0:
        raise SplitPlanError(f"total duration must be positive, got {total_duration}")
    if count < 1:
        raise SplitPlanError(f"part count must be >= 1, got {count}")
    if total_duration / count < MIN_SEGMENT_SECONDS:
        raise SplitPlanError(
            f"cannot split {total_duration:.2f}s into {count} parts: "
            f"each part would be shorter than {MIN_SEGMENT_SECONDS}s"
        )
    # Cumulative boundaries avoid float drift accumulating across parts.
    boundaries = [total_duration * i / count for i in range(count + 1)]
    boundaries[-1] = total_duration
    return [Segment(index=i, start=boundaries[i], end=boundaries[i + 1]) for i in range(count)]


def plan_by_timestamps(ranges: list[tuple[float, float]], total_duration: float) -> list[Segment]:
    """Validate explicit ranges: in-bounds, ordered, non-overlapping."""
    if total_duration <= 0:
        raise SplitPlanError(f"total duration must be positive, got {total_duration}")
    if not ranges:
        raise SplitPlanError("no timestamp ranges given")
    ordered = sorted(ranges, key=lambda r: r[0])
    segments: list[Segment] = []
    prev_end = -1.0
    for i, (start, end) in enumerate(ordered):
        if start < 0 or end <= start:
            raise SplitPlanError(f"invalid range {start:.2f}-{end:.2f}")
        if end > total_duration + 1.0:  # 1s grace for container duration rounding
            raise SplitPlanError(
                f"range {start:.2f}-{end:.2f} exceeds video duration ({total_duration:.2f}s)"
            )
        if start < prev_end - _EPSILON:
            raise SplitPlanError(
                f"range {start:.2f}-{end:.2f} overlaps the previous range ending at {prev_end:.2f}"
            )
        segments.append(Segment(index=i, start=start, end=min(end, total_duration)))
        prev_end = end
    return segments


def build_split_command(
    input_path: Path, output_path: Path, segment: Segment, *, precise: bool
) -> list[str]:
    """ffmpeg argv (minus binary) to extract one segment.

    Copy mode seeks before the input (fast, keyframe-aligned); precise mode
    re-encodes for frame-accurate cuts.
    """
    argv = [
        "-y",
        "-ss",
        f"{segment.start:.6f}",
        "-i",
        str(input_path),
        "-t",
        f"{segment.duration:.6f}",
        "-map",
        "0",
    ]
    if precise:
        argv += [
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "medium",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
        ]
    else:
        argv += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
    argv.append(str(output_path))
    return argv


class SplitterService:
    def __init__(self, ffmpeg: FFmpeg, probe: ProbeService) -> None:
        self._ffmpeg = ffmpeg
        self._probe = probe

    def plan(
        self,
        input_path: Path,
        mode: SplitMode,
        *,
        segment_duration: float | None = None,
        count: int | None = None,
        ranges: list[tuple[float, float]] | None = None,
        precise: bool = False,
        cancel_event: CancelEvent | None = None,
    ) -> SegmentPlan:
        info = self._probe.probe_video(input_path, cancel_event=cancel_event)
        if mode is SplitMode.DURATION:
            if segment_duration is None:
                raise SplitPlanError("by-duration mode requires a segment duration")
            segments = plan_by_duration(info.duration, segment_duration)
        elif mode is SplitMode.COUNT:
            if count is None:
                raise SplitPlanError("by-count mode requires a part count")
            segments = plan_by_count(info.duration, count)
        else:
            if not ranges:
                raise SplitPlanError("by-timestamps mode requires at least one range")
            segments = plan_by_timestamps(ranges, info.duration)
        return SegmentPlan(
            source=input_path,
            mode=mode,
            total_duration=info.duration,
            segments=tuple(segments),
            precise=precise,
        )

    def execute_segment(
        self,
        plan: SegmentPlan,
        segment: Segment,
        output_dir: Path,
        *,
        overwrite: bool = False,
        cancel_event: CancelEvent | None = None,
    ) -> Path:
        output_path = part_output_path(plan.source, output_dir, segment.index, plan.part_count)
        check_output(plan.source, output_path, overwrite=overwrite)
        with atomic_output(output_path) as tmp_path:
            argv = build_split_command(plan.source, tmp_path, segment, precise=plan.precise)
            log.info(
                "split_segment_start",
                input=str(plan.source),
                part=segment.index + 1,
                of=plan.part_count,
                start=round(segment.start, 3),
                end=round(segment.end, 3),
                precise=plan.precise,
            )
            self._ffmpeg.run_ffmpeg(argv, cancel_event=cancel_event)
        log.info("split_segment_done", output=str(output_path))
        return output_path
