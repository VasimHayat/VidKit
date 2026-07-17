"""Integration: splitting real files with real ffmpeg."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.conftest import FIXTURE_DURATION
from vidkit.core.splitter import SplitterService
from vidkit.models import SplitMode

if TYPE_CHECKING:
    from pathlib import Path

    from vidkit.core.ffmpeg import FFmpeg
    from vidkit.core.probe import ProbeService

pytestmark = pytest.mark.integration

# Copy-mode cuts snap to keyframes; the fixture has a keyframe every second.
COPY_TOLERANCE = 1.1


@pytest.fixture
def splitter(ffmpeg_wrapper: FFmpeg, probe_service: ProbeService) -> SplitterService:
    return SplitterService(ffmpeg_wrapper, probe_service)


def run_plan(
    splitter: SplitterService,
    plan_args: dict,
    fixture: Path,
    out_dir: Path,  # type: ignore[type-arg]
) -> list[Path]:
    plan = splitter.plan(fixture, **plan_args)
    return [splitter.execute_segment(plan, segment, out_dir) for segment in plan.segments]


class TestSplitByCount:
    def test_three_parts_with_correct_durations(
        self,
        splitter: SplitterService,
        probe_service: ProbeService,
        fixture_video: Path,
        tmp_path: Path,
    ) -> None:
        outputs = run_plan(splitter, {"mode": SplitMode.COUNT, "count": 3}, fixture_video, tmp_path)
        assert [p.name for p in outputs] == [
            "sample_part01.mp4",
            "sample_part02.mp4",
            "sample_part03.mp4",
        ]
        expected = FIXTURE_DURATION / 3
        durations = [probe_service.probe(p).duration for p in outputs]
        for duration in durations:
            assert duration == pytest.approx(expected, abs=COPY_TOLERANCE)
        assert sum(durations) == pytest.approx(FIXTURE_DURATION, abs=2 * COPY_TOLERANCE)


class TestSplitByDuration:
    def test_uneven_final_part(
        self,
        splitter: SplitterService,
        probe_service: ProbeService,
        fixture_video: Path,
        tmp_path: Path,
    ) -> None:
        outputs = run_plan(
            splitter,
            {"mode": SplitMode.DURATION, "segment_duration": 12.0},
            fixture_video,
            tmp_path,
        )
        assert len(outputs) == 3
        durations = [probe_service.probe(p).duration for p in outputs]
        assert durations[0] == pytest.approx(12.0, abs=COPY_TOLERANCE)
        assert durations[1] == pytest.approx(12.0, abs=COPY_TOLERANCE)
        assert durations[2] == pytest.approx(FIXTURE_DURATION - 24.0, abs=COPY_TOLERANCE)


class TestSplitByTimestamps:
    def test_explicit_ranges(
        self,
        splitter: SplitterService,
        probe_service: ProbeService,
        fixture_video: Path,
        tmp_path: Path,
    ) -> None:
        outputs = run_plan(
            splitter,
            {"mode": SplitMode.TIMESTAMPS, "ranges": [(0.0, 10.0), (15.0, 25.0)]},
            fixture_video,
            tmp_path,
        )
        assert len(outputs) == 2
        for path in outputs:
            assert probe_service.probe(path).duration == pytest.approx(10.0, abs=COPY_TOLERANCE)


class TestPreciseMode:
    def test_precise_split_is_frame_accurate(
        self,
        splitter: SplitterService,
        probe_service: ProbeService,
        fixture_video: Path,
        tmp_path: Path,
    ) -> None:
        plan = splitter.plan(fixture_video, SplitMode.TIMESTAMPS, ranges=[(3.5, 8.5)], precise=True)
        output = splitter.execute_segment(plan, plan.segments[0], tmp_path)
        info = probe_service.probe(output)
        # Re-encode cuts are not keyframe-bound: much tighter tolerance.
        assert info.duration == pytest.approx(5.0, abs=0.25)
        video = next(s for s in info.streams if s.codec_type == "video")
        assert video.codec_name == "h264"

    def test_copy_mode_streams_not_reencoded(
        self,
        splitter: SplitterService,
        probe_service: ProbeService,
        fixture_video: Path,
        tmp_path: Path,
    ) -> None:
        original = probe_service.probe(fixture_video)
        plan = splitter.plan(fixture_video, SplitMode.COUNT, count=2)
        output = splitter.execute_segment(plan, plan.segments[0], tmp_path)
        part = probe_service.probe(output)
        assert [s.codec_name for s in part.streams] == [s.codec_name for s in original.streams]
