"""Unit tests for input expansion and job-result mapping (no ffmpeg)."""

from __future__ import annotations

from pathlib import Path

import pytest

from vidkit.core.runner import expand_inputs, run_job
from vidkit.core.splitter import build_split_command
from vidkit.exceptions import (
    FFmpegExecutionError,
    InvalidMediaError,
    JobCancelledError,
    VerificationError,
)
from vidkit.models import JobStatus, Segment


class TestExpandInputs:
    def test_single_file(self, tmp_path: Path) -> None:
        f = tmp_path / "a.mp4"
        f.write_bytes(b"x")
        assert expand_inputs(str(f)) == [f]

    def test_directory_filters_video_extensions(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp4").write_bytes(b"x")
        (tmp_path / "b.MKV").write_bytes(b"x")
        (tmp_path / "notes.txt").write_bytes(b"x")
        (tmp_path / "sub").mkdir()
        result = expand_inputs(str(tmp_path))
        assert [p.name for p in result] == ["a.mp4", "b.MKV"]

    def test_glob_pattern(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp4").write_bytes(b"x")
        (tmp_path / "b.mp4").write_bytes(b"x")
        (tmp_path / "c.mkv").write_bytes(b"x")
        result = expand_inputs(str(tmp_path / "*.mp4"))
        assert [p.name for p in result] == ["a.mp4", "b.mp4"]

    def test_no_match_raises(self, tmp_path: Path) -> None:
        with pytest.raises(InvalidMediaError, match="no input files match"):
            expand_inputs(str(tmp_path / "*.mp4"))


class TestRunJob:
    def test_success(self, tmp_path: Path) -> None:
        out = tmp_path / "out.mp4"
        result = run_job(lambda _e: [out], tmp_path / "in.mp4", None)
        assert result.status is JobStatus.SUCCEEDED
        assert result.outputs == [out]
        assert result.error_type is None

    def test_invalid_media_becomes_skipped(self, tmp_path: Path) -> None:
        def job(_e: object) -> list[Path]:
            raise InvalidMediaError("not a video")

        result = run_job(job, tmp_path / "in.mp4", None)
        assert result.status is JobStatus.SKIPPED
        assert result.error_message == "not a video"

    @pytest.mark.parametrize(
        "exc",
        [
            VerificationError("tags remain"),
            FFmpegExecutionError("died", argv=["ffmpeg"], stderr="err"),
            JobCancelledError("stop"),
        ],
    )
    def test_typed_failures_become_failed(self, tmp_path: Path, exc: Exception) -> None:
        def job(_e: object) -> list[Path]:
            raise exc

        result = run_job(job, tmp_path / "in.mp4", None)
        assert result.status is JobStatus.FAILED
        assert result.error_type == type(exc).__name__


class TestBuildSplitCommand:
    SEG = Segment(index=0, start=10.0, end=25.0)

    def test_copy_mode(self) -> None:
        argv = build_split_command(Path("in.mp4"), Path("out.mp4"), self.SEG, precise=False)
        joined = " ".join(argv)
        assert "-c copy" in joined
        assert "-avoid_negative_ts make_zero" in joined
        assert "libx264" not in joined
        # fast seek: -ss must precede -i
        assert argv.index("-ss") < argv.index("-i")
        assert argv[argv.index("-ss") + 1] == "10.000000"
        assert argv[argv.index("-t") + 1] == "15.000000"

    def test_precise_mode(self) -> None:
        argv = build_split_command(Path("in.mp4"), Path("out.mp4"), self.SEG, precise=True)
        joined = " ".join(argv)
        assert "-c:v libx264" in joined
        assert "-crf 18" in joined
        assert "-preset medium" in joined
        assert "-c copy" not in joined
