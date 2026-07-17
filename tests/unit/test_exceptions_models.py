"""Unit tests for the exception hierarchy and report/model behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from vidkit.exceptions import (
    EXIT_FFMPEG_MISSING,
    EXIT_INVALID_MEDIA,
    EXIT_OUTPUT_EXISTS,
    EXIT_SPLIT_PLAN,
    EXIT_UNEXPECTED,
    EXIT_VERIFICATION,
    FFmpegExecutionError,
    FFmpegNotFoundError,
    InvalidMediaError,
    OutputExistsError,
    SplitPlanError,
    VerificationError,
    VidKitError,
    exit_code_for_error_name,
)
from vidkit.models import (
    JobReport,
    JobResult,
    JobStatus,
    MediaInfo,
    Segment,
    SegmentPlan,
    SplitMode,
    StreamInfo,
)


class TestExceptionMapping:
    @pytest.mark.parametrize(
        ("exc", "code"),
        [
            (FFmpegNotFoundError, EXIT_FFMPEG_MISSING),
            (InvalidMediaError, EXIT_INVALID_MEDIA),
            (SplitPlanError, EXIT_SPLIT_PLAN),
            (OutputExistsError, EXIT_OUTPUT_EXISTS),
            (VerificationError, EXIT_VERIFICATION),
        ],
    )
    def test_exit_codes(self, exc: type[VidKitError], code: int) -> None:
        assert exc.exit_code == code
        assert exit_code_for_error_name(exc.__name__) == code

    def test_unknown_name_maps_to_unexpected(self) -> None:
        assert exit_code_for_error_name("SomethingElse") == EXIT_UNEXPECTED
        assert exit_code_for_error_name(None) == EXIT_UNEXPECTED

    def test_execution_error_carries_stderr(self) -> None:
        exc = FFmpegExecutionError("bad", argv=["ffmpeg", "-i", "x"], stderr="line1\nfatal")
        text = str(exc)
        assert "fatal" in text
        assert "ffmpeg -i x" in text


class TestSegmentModel:
    def test_rejects_reversed_range(self) -> None:
        with pytest.raises(ValidationError):
            Segment(index=0, start=10.0, end=5.0)

    def test_duration(self) -> None:
        assert Segment(index=0, start=1.5, end=4.0).duration == 2.5

    def test_plan_requires_segments(self) -> None:
        with pytest.raises(ValidationError):
            SegmentPlan(
                source=Path("x.mp4"),
                mode=SplitMode.COUNT,
                total_duration=30.0,
                segments=(),
            )


class TestMediaInfo:
    def test_tag_inventory_and_has_video(self) -> None:
        info = MediaInfo(
            path=Path("x.mp4"),
            format_name="mp4",
            duration=10.0,
            size_bytes=1,
            streams=(
                StreamInfo(index=0, codec_type="video", codec_name="h264", tags={"a": "1"}),
                StreamInfo(index=1, codec_type="audio", codec_name="aac"),
            ),
            format_tags={"title": "t"},
        )
        assert info.has_video
        assert info.tag_inventory == {"format": {"title": "t"}, "stream:0:video": {"a": "1"}}

    def test_no_video(self) -> None:
        info = MediaInfo(
            path=Path("x.mp3"),
            format_name="mp3",
            duration=10.0,
            size_bytes=1,
            streams=(StreamInfo(index=0, codec_type="audio", codec_name="mp3"),),
        )
        assert not info.has_video


class TestJobReport:
    def test_aggregation_and_json(self, tmp_path: Path) -> None:
        report = JobReport(command="clean")
        report.add(
            JobResult(
                input_path=Path("a.mp4"),
                status=JobStatus.SUCCEEDED,
                outputs=[Path("out/a_clean.mp4")],
                elapsed_seconds=1.25,
            )
        )
        report.add(JobResult.skipped(Path("b.txt"), "not a video"))
        report.add(JobResult.failed(Path("c.mp4"), VerificationError("tags remain")))
        report.finish()

        assert (report.succeeded, report.failed, report.skipped) == (1, 1, 1)
        assert report.total_elapsed == pytest.approx(1.25)
        assert report.finished_at is not None

        out = tmp_path / "report.json"
        report.write_json(out)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert len(data["results"]) == 3
        assert data["results"][2]["error_type"] == "VerificationError"
