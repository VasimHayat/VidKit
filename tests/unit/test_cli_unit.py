"""CLI tests that need no ffmpeg: usage errors, version, output rendering."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

import vidkit
from vidkit.cli.app import app
from vidkit.cli.output import format_seconds, render_plan, render_report
from vidkit.exceptions import EXIT_USAGE
from vidkit.models import (
    JobReport,
    JobResult,
    JobStatus,
    Segment,
    SegmentPlan,
    SplitMode,
)

runner = CliRunner()


class TestUsage:
    def test_version(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert vidkit.__version__ in result.output

    def test_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for command in ("probe", "clean", "split"):
            assert command in result.output

    def test_split_requires_exactly_one_mode(self) -> None:
        result = runner.invoke(app, ["split", "x.mp4", "--by-count", "3", "--by-duration", "10m"])
        assert result.exit_code == EXIT_USAGE

    def test_split_requires_at_least_one_mode(self) -> None:
        result = runner.invoke(app, ["split", "x.mp4"])
        assert result.exit_code == EXIT_USAGE


class TestRendering:
    def test_format_seconds(self) -> None:
        assert format_seconds(0.0) == "00:00:00.000"
        assert format_seconds(3723.5) == "01:02:03.500"

    def test_render_report_lists_all_statuses(self) -> None:
        report = JobReport(command="clean")
        report.add(
            JobResult(
                input_path=Path("ok.mp4"),
                status=JobStatus.SUCCEEDED,
                outputs=[Path("ok_clean.mp4")],
            )
        )
        report.add(JobResult.skipped(Path("bad.txt"), "not a video"))
        report.interrupted = True
        console = Console(record=True, width=120)
        render_report(report, console)
        text = console.export_text()
        assert "succeeded" in text
        assert "skipped" in text
        assert "interrupted" in text

    def test_render_plan_shows_commands(self) -> None:
        plan = SegmentPlan(
            source=Path("movie.mp4"),
            mode=SplitMode.COUNT,
            total_duration=30.0,
            segments=(Segment(index=0, start=0.0, end=30.0),),
        )
        console = Console(record=True, width=200)
        render_plan(plan, [["ffmpeg", "-i", "movie.mp4", "out.mp4"]], console)
        text = console.export_text()
        assert "movie.mp4" in text
        assert "Commands that would run" in text
