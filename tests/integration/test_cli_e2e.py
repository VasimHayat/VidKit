"""Integration: the full CLI driven through Typer's CliRunner."""

from __future__ import annotations

import json
import signal
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from tests.conftest import generate_video
from vidkit.cli.app import app
from vidkit.config import Settings
from vidkit.core.runner import _pool_initializer, clean_worker
from vidkit.exceptions import EXIT_INVALID_MEDIA, EXIT_OUTPUT_EXISTS
from vidkit.models import JobStatus

if TYPE_CHECKING:
    from pathlib import Path

    from vidkit.core.ffmpeg import FFmpeg

pytestmark = pytest.mark.integration

runner = CliRunner()


@pytest.fixture
def settings(ffmpeg_env: None) -> Settings:
    return Settings()


class TestProbeCommand:
    def test_human_output(self, ffmpeg_env: None, fixture_video: Path) -> None:
        result = runner.invoke(app, ["probe", str(fixture_video)])
        assert result.exit_code == 0
        assert "VidKit Test Video" in result.output
        assert "h264" in result.output

    def test_json_output(self, ffmpeg_env: None, fixture_video: Path) -> None:
        result = runner.invoke(app, ["probe", str(fixture_video), "--json", "--quiet"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["format_tags"]["title"] == "VidKit Test Video"

    def test_missing_file_exit_code(self, ffmpeg_env: None, tmp_path: Path) -> None:
        result = runner.invoke(app, ["probe", str(tmp_path / "ghost.mp4")])
        assert result.exit_code == EXIT_INVALID_MEDIA


class TestCleanCommand:
    def test_single_file(self, ffmpeg_env: None, fixture_video: Path, tmp_path: Path) -> None:
        out_dir = tmp_path / "out"
        result = runner.invoke(
            app,
            ["clean", str(fixture_video), "--output-dir", str(out_dir), "--quiet", "--json"],
        )
        assert result.exit_code == 0, result.output
        report = json.loads(result.output)
        assert report["results"][0]["status"] == "succeeded"
        assert (out_dir / "sample_clean.mp4").exists()

    def test_existing_output_exit_code(
        self, ffmpeg_env: None, fixture_video: Path, tmp_path: Path
    ) -> None:
        out_dir = tmp_path / "out"
        first = runner.invoke(
            app, ["clean", str(fixture_video), "--output-dir", str(out_dir), "--quiet"]
        )
        assert first.exit_code == 0
        second = runner.invoke(
            app, ["clean", str(fixture_video), "--output-dir", str(out_dir), "--quiet"]
        )
        assert second.exit_code == EXIT_OUTPUT_EXISTS

    def test_dry_run_executes_nothing(
        self, ffmpeg_env: None, fixture_video: Path, tmp_path: Path
    ) -> None:
        out_dir = tmp_path / "out"
        result = runner.invoke(
            app, ["clean", str(fixture_video), "--output-dir", str(out_dir), "--dry-run"]
        )
        assert result.exit_code == 0
        assert "-map_metadata -1" in result.output
        assert not out_dir.exists()

    def test_batch_skips_corrupt_and_reports(
        self,
        ffmpeg_env: None,
        ffmpeg_wrapper: FFmpeg,
        fixture_video: Path,
        tmp_path: Path,
    ) -> None:
        """A corrupt file inside a batch is skipped; good files still succeed."""
        batch_dir = tmp_path / "batch"
        batch_dir.mkdir()
        generate_video(ffmpeg_wrapper, batch_dir / "one.mp4", duration=3.0)
        generate_video(ffmpeg_wrapper, batch_dir / "two.mp4", duration=3.0)
        (batch_dir / "broken.mp4").write_bytes(b"garbage" * 100)

        out_dir = tmp_path / "out"
        report_file = tmp_path / "report.json"
        result = runner.invoke(
            app,
            [
                "clean",
                str(batch_dir),
                "--output-dir",
                str(out_dir),
                "--workers",
                "2",
                "--report",
                str(report_file),
                "--quiet",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output

        report = json.loads(report_file.read_text(encoding="utf-8"))
        by_status = {r["status"] for r in report["results"]}
        assert by_status == {"succeeded", "skipped"}
        assert sum(r["status"] == "succeeded" for r in report["results"]) == 2
        assert sum(r["status"] == "skipped" for r in report["results"]) == 1
        assert (out_dir / "one_clean.mp4").exists()
        assert (out_dir / "two_clean.mp4").exists()
        assert not (out_dir / "broken_clean.mp4").exists()


class TestSplitCommand:
    def test_by_count(self, ffmpeg_env: None, fixture_video: Path, tmp_path: Path) -> None:
        out_dir = tmp_path / "parts"
        result = runner.invoke(
            app,
            [
                "split",
                str(fixture_video),
                "--by-count",
                "3",
                "--output-dir",
                str(out_dir),
                "--quiet",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        report = json.loads(result.output)
        assert len(report["results"]) == 3
        assert sorted(p.name for p in out_dir.iterdir()) == [
            "sample_part01.mp4",
            "sample_part02.mp4",
            "sample_part03.mp4",
        ]

    def test_by_timestamps_cli_parsing(
        self, ffmpeg_env: None, fixture_video: Path, tmp_path: Path
    ) -> None:
        out_dir = tmp_path / "parts"
        result = runner.invoke(
            app,
            [
                "split",
                str(fixture_video),
                "--by-timestamps",
                "00:00-00:10,00:10-00:25",
                "--output-dir",
                str(out_dir),
                "--quiet",
            ],
        )
        assert result.exit_code == 0
        assert len(list(out_dir.iterdir())) == 2

    def test_dry_run_prints_plan_only(
        self, ffmpeg_env: None, fixture_video: Path, tmp_path: Path
    ) -> None:
        out_dir = tmp_path / "parts"
        result = runner.invoke(
            app,
            [
                "split",
                str(fixture_video),
                "--by-duration",
                "10s",
                "--output-dir",
                str(out_dir),
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "Split plan" in result.output
        assert "Commands that would run" in result.output
        assert not out_dir.exists()

    def test_overlapping_timestamps_rejected(self, ffmpeg_env: None, fixture_video: Path) -> None:
        result = runner.invoke(
            app,
            ["split", str(fixture_video), "--by-timestamps", "00:00-00:15,00:10-00:20"],
        )
        assert result.exit_code == 5  # EXIT_SPLIT_PLAN


class TestWorkerFunctions:
    """Exercise the pool worker path in-process for deterministic coverage."""

    def test_clean_worker_success(
        self, settings: Settings, fixture_video: Path, tmp_path: Path
    ) -> None:
        result = clean_worker(
            settings.model_dump(mode="json"), fixture_video, tmp_path, False, None
        )
        assert result.status is JobStatus.SUCCEEDED
        assert result.outputs[0].exists()

    def test_clean_worker_skips_corrupt(
        self, settings: Settings, corrupt_video: Path, tmp_path: Path
    ) -> None:
        result = clean_worker(
            settings.model_dump(mode="json"), corrupt_video, tmp_path, False, None
        )
        assert result.status is JobStatus.SKIPPED

    def test_pool_initializer_configures_quiet_logging(self, settings: Settings) -> None:
        previous = signal.getsignal(signal.SIGINT)
        try:
            _pool_initializer(settings.model_dump(mode="json"))
            assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN
        finally:
            signal.signal(signal.SIGINT, previous)
