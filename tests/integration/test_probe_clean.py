"""Integration: probing and cleaning real files with real ffmpeg."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.conftest import FIXTURE_DURATION
from vidkit.core.cleaner import CleanerService, find_residual_tags
from vidkit.exceptions import InvalidMediaError, OutputExistsError

if TYPE_CHECKING:
    from pathlib import Path

    from vidkit.core.ffmpeg import FFmpeg
    from vidkit.core.probe import ProbeService

pytestmark = pytest.mark.integration


class TestProbe:
    def test_reports_duration_streams_and_tags(
        self, probe_service: ProbeService, fixture_video: Path
    ) -> None:
        info = probe_service.probe(fixture_video)
        assert info.duration == pytest.approx(FIXTURE_DURATION, abs=0.5)
        assert info.has_video
        assert {s.codec_type for s in info.streams} == {"video", "audio"}
        assert info.format_tags.get("title") == "VidKit Test Video"
        assert "location" in {k.lower() for k in info.format_tags}
        assert info.size_bytes > 0

    def test_missing_file_raises(self, probe_service: ProbeService, tmp_path: Path) -> None:
        with pytest.raises(InvalidMediaError, match="does not exist"):
            probe_service.probe(tmp_path / "ghost.mp4")

    def test_corrupt_file_raises(self, probe_service: ProbeService, corrupt_video: Path) -> None:
        with pytest.raises(InvalidMediaError):
            probe_service.probe(corrupt_video)

    def test_non_video_rejected_by_probe_video(
        self, probe_service: ProbeService, ffmpeg_wrapper: FFmpeg, tmp_path: Path
    ) -> None:
        audio = tmp_path / "audio.m4a"
        ffmpeg_wrapper.run_ffmpeg(
            ["-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "aac", str(audio)],
            timeout=60.0,
        )
        with pytest.raises(InvalidMediaError, match="no video stream"):
            probe_service.probe_video(audio)


class TestClean:
    def test_clean_removes_all_metadata(
        self,
        ffmpeg_wrapper: FFmpeg,
        probe_service: ProbeService,
        fixture_video: Path,
        tmp_path: Path,
    ) -> None:
        cleaner = CleanerService(ffmpeg_wrapper, probe_service)
        out = cleaner.clean(fixture_video, tmp_path)

        assert out == tmp_path / "sample_clean.mp4"
        assert out.exists()

        # ffprobe-based verification: nothing but structural container fields
        # (mp4 ftyp brands) may remain; every user/device tag must be gone.
        info = probe_service.probe(out)
        assert find_residual_tags(info) == []
        leftover_keys = {k.lower() for k in info.format_tags}
        assert leftover_keys <= {"major_brand", "minor_version", "compatible_brands"}
        for key in ("title", "comment", "creation_time", "location", "encoder"):
            assert key not in leftover_keys
        assert info.chapter_count == 0
        # Streams survived the remux (no re-encode, both streams mapped).
        assert {s.codec_type for s in info.streams} == {"video", "audio"}
        assert info.duration == pytest.approx(FIXTURE_DURATION, abs=1.0)

        # Input untouched.
        original = probe_service.probe(fixture_video)
        assert original.format_tags.get("title") == "VidKit Test Video"

    def test_refuses_existing_output_then_allows_overwrite(
        self,
        ffmpeg_wrapper: FFmpeg,
        probe_service: ProbeService,
        fixture_video: Path,
        tmp_path: Path,
    ) -> None:
        cleaner = CleanerService(ffmpeg_wrapper, probe_service)
        cleaner.clean(fixture_video, tmp_path)
        with pytest.raises(OutputExistsError):
            cleaner.clean(fixture_video, tmp_path)
        out = cleaner.clean(fixture_video, tmp_path, overwrite=True)
        assert out.exists()

    def test_no_temp_files_left_behind(
        self,
        ffmpeg_wrapper: FFmpeg,
        probe_service: ProbeService,
        fixture_video: Path,
        tmp_path: Path,
    ) -> None:
        cleaner = CleanerService(ffmpeg_wrapper, probe_service)
        cleaner.clean(fixture_video, tmp_path)
        leftovers = [p for p in tmp_path.iterdir() if ".tmp" in p.name]
        assert leftovers == []

    def test_corrupt_input_raises_invalid_media(
        self,
        ffmpeg_wrapper: FFmpeg,
        probe_service: ProbeService,
        corrupt_video: Path,
        tmp_path: Path,
    ) -> None:
        cleaner = CleanerService(ffmpeg_wrapper, probe_service)
        with pytest.raises(InvalidMediaError):
            cleaner.clean(corrupt_video, tmp_path / "out")
