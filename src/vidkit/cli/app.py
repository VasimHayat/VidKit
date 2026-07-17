"""Typer application: thin adapter over the core services."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

import vidkit
from vidkit.cli.output import render_plan, render_probe, render_report
from vidkit.config import Settings, load_settings
from vidkit.core.cleaner import CleanerService, build_clean_command
from vidkit.core.ffmpeg import FFmpeg
from vidkit.core.outputs import clean_output_path, part_output_path
from vidkit.core.probe import ProbeService
from vidkit.core.runner import BatchRunner, expand_inputs, run_job
from vidkit.core.splitter import SplitterService, build_split_command
from vidkit.core.timeparse import parse_duration, parse_timestamp_ranges
from vidkit.exceptions import (
    EXIT_INTERRUPTED,
    EXIT_PARTIAL_FAILURE,
    EXIT_UNEXPECTED,
    EXIT_USAGE,
    JobCancelledError,
    VidKitError,
    exit_code_for_error_name,
)
from vidkit.logging import configure_logging, get_logger
from vidkit.models import JobReport, JobResult, JobStatus, SplitMode

log = get_logger(__name__)

app = typer.Typer(
    name="vidkit",
    help="Strip video metadata and split videos without re-encoding.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)

err_console = Console(stderr=True)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"vidkit {vidkit.__version__}")
        raise typer.Exit(0)


@app.callback()
def app_main(
    _version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
        ),
    ] = False,
) -> None:
    """VidKit — production-grade video metadata removal and splitting."""


# ---------------------------------------------------------------- shared opts

QuietOpt = Annotated[bool, typer.Option("--quiet", "-q", help="Suppress progress output (CI).")]
JsonOpt = Annotated[bool, typer.Option("--json", help="Machine-readable JSON on stdout.")]
LogFileOpt = Annotated[Path | None, typer.Option("--log-file", help="Also write JSON logs here.")]
LogLevelOpt = Annotated[str, typer.Option("--log-level", help="DEBUG, INFO, WARNING, ERROR.")]
OutputDirOpt = Annotated[
    Path | None, typer.Option("--output-dir", "-o", help="Output directory (default ./vidkit_out).")
]
OverwriteOpt = Annotated[
    bool, typer.Option("--overwrite", help="Replace existing outputs instead of failing.")
]
DryRunOpt = Annotated[
    bool, typer.Option("--dry-run", help="Show the plan and exact ffmpeg commands; run nothing.")
]


def _bootstrap(
    quiet: bool, log_file: Path | None, log_level: str
) -> tuple[Settings, FFmpeg, ProbeService]:
    """Load settings, configure logging, run the ffmpeg preflight."""
    settings = load_settings()
    configure_logging(
        level=log_level or settings.log_level,
        log_format=settings.log_format,
        log_file=log_file,
        quiet=quiet,
    )
    ffmpeg = FFmpeg(settings)
    banner = ffmpeg.preflight()
    log.debug("preflight_ok", banner=banner)
    return settings, ffmpeg, ProbeService(ffmpeg)


def _die(exc: VidKitError) -> NoReturn:
    log.error("fatal", error=str(exc), kind=type(exc).__name__, exit_code=exc.exit_code)
    err_console.print(f"[red bold]error:[/] {exc}")
    raise typer.Exit(exc.exit_code)


def _die_unexpected(exc: Exception) -> NoReturn:
    log.exception("unexpected_error")
    err_console.print(f"[red bold]unexpected error:[/] {type(exc).__name__}: {exc}")
    raise typer.Exit(EXIT_UNEXPECTED)


def _make_progress(quiet: bool) -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=Console(stderr=True),
        disable=quiet,
    )


def _finalize_report(
    report: JobReport,
    *,
    json_output: bool,
    quiet: bool,
    report_path: Path | None,
) -> None:
    report.finish()
    if report_path is not None:
        report.write_json(report_path)
        log.info("report_written", path=str(report_path))
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
    elif not quiet:
        render_report(report, Console())


def _report_exit_code(report: JobReport) -> int:
    if report.interrupted:
        return EXIT_INTERRUPTED
    return 0 if report.failed == 0 else EXIT_PARTIAL_FAILURE


# --------------------------------------------------------------------- probe


@app.command()
def probe(
    input_file: Annotated[Path, typer.Argument(help="Video file to inspect.", metavar="INPUT")],
    json_output: JsonOpt = False,
    quiet: QuietOpt = False,
    log_file: LogFileOpt = None,
    log_level: LogLevelOpt = "INFO",
) -> None:
    """Show duration, streams, and the full metadata inventory of a file."""
    try:
        _, _, probe_service = _bootstrap(quiet, log_file, log_level)
        info = probe_service.probe(input_file)
    except VidKitError as exc:
        _die(exc)
    except Exception as exc:
        _die_unexpected(exc)
    if json_output:
        typer.echo(info.model_dump_json(indent=2))
    else:
        render_probe(info, Console())


# --------------------------------------------------------------------- clean


@app.command()
def clean(
    inputs: Annotated[
        str, typer.Argument(help="Video file, directory, or glob pattern.", metavar="INPUT")
    ],
    output_dir: OutputDirOpt = None,
    workers: Annotated[
        int | None, typer.Option("--workers", "-w", min=1, help="Parallel workers (max 8).")
    ] = None,
    report_path: Annotated[
        Path | None, typer.Option("--report", help="Write the JSON job report here.")
    ] = None,
    dry_run: DryRunOpt = False,
    overwrite: OverwriteOpt = False,
    json_output: JsonOpt = False,
    quiet: QuietOpt = False,
    log_file: LogFileOpt = None,
    log_level: LogLevelOpt = "INFO",
) -> None:
    """Strip all metadata (tags, chapters, encoder info) without re-encoding."""
    try:
        settings, ffmpeg, probe_service = _bootstrap(quiet, log_file, log_level)
        out_dir = output_dir or settings.output_dir
        files = expand_inputs(inputs)
    except VidKitError as exc:
        _die(exc)
    except Exception as exc:
        _die_unexpected(exc)

    if dry_run:
        console = Console()
        for path in files:
            argv = build_clean_command(path, clean_output_path(path, out_dir))
            console.print(f"[bold]{path}[/bold]")
            console.print("  ffmpeg " + " ".join(argv), highlight=False, soft_wrap=True)
        console.print(f"[dim]{len(files)} file(s); nothing executed (--dry-run).[/dim]")
        return

    report = JobReport(command="clean")
    try:
        if len(files) == 1:
            _clean_single(files[0], out_dir, overwrite, ffmpeg, probe_service, report, quiet)
        else:
            _clean_batch(files, out_dir, overwrite, settings, workers, report, quiet)
    except KeyboardInterrupt:
        report.interrupted = True
    except VidKitError as exc:
        _die(exc)
    except Exception as exc:
        _die_unexpected(exc)

    _finalize_report(report, json_output=json_output, quiet=quiet, report_path=report_path)
    code = _single_exit_code(report) if len(files) == 1 else _report_exit_code(report)
    raise typer.Exit(code)


def _single_exit_code(report: JobReport) -> int:
    """For one input, surface the typed exit code instead of the batch code."""
    if report.interrupted:
        return EXIT_INTERRUPTED
    result = report.results[0] if report.results else None
    if result is None:
        return EXIT_INTERRUPTED
    if result.status is JobStatus.SUCCEEDED:
        return 0
    # A lone skipped/failed input surfaces its typed exit code; in batch mode
    # skips are tolerated, but for one file the user deserves a real signal.
    return exit_code_for_error_name(result.error_type)


def _clean_single(
    path: Path,
    out_dir: Path,
    overwrite: bool,
    ffmpeg: FFmpeg,
    probe_service: ProbeService,
    report: JobReport,
    quiet: bool,
) -> None:
    cleaner = CleanerService(ffmpeg, probe_service)
    with _make_progress(quiet) as progress:
        task = progress.add_task(f"cleaning {path.name}", total=1)
        result = run_job(
            lambda event: [cleaner.clean(path, out_dir, overwrite=overwrite, cancel_event=event)],
            path,
            None,
        )
        progress.advance(task)
    report.add(result)
    if result.error_type == JobCancelledError.__name__:
        report.interrupted = True


def _clean_batch(
    files: list[Path],
    out_dir: Path,
    overwrite: bool,
    settings: Settings,
    workers: int | None,
    report: JobReport,
    quiet: bool,
) -> None:
    runner = BatchRunner(settings, workers or settings.workers)
    with _make_progress(quiet) as progress:
        task = progress.add_task("cleaning batch", total=len(files))

        def on_result(result: JobResult) -> None:
            report.add(result)
            progress.advance(task)
            style = {"succeeded": "green", "failed": "red", "skipped": "yellow"}[
                result.status.value
            ]
            progress.console.print(f"[{style}]{result.status.value:>9}[/] {result.input_path.name}")

        report.interrupted = runner.run_clean(
            files, out_dir, overwrite=overwrite, on_result=on_result
        )


# --------------------------------------------------------------------- split


@app.command()
def split(
    input_file: Annotated[Path, typer.Argument(help="Video file to split.", metavar="INPUT")],
    by_duration: Annotated[
        str | None,
        typer.Option("--by-duration", help="Segment length, e.g. 90s, 10m, 1h30m."),
    ] = None,
    by_count: Annotated[
        int | None, typer.Option("--by-count", min=1, help="Split into N equal parts.")
    ] = None,
    by_timestamps: Annotated[
        str | None,
        typer.Option("--by-timestamps", help='Explicit ranges: "00:00-05:30,05:30-12:00".'),
    ] = None,
    precise: Annotated[
        bool,
        typer.Option(
            "--precise",
            help="Frame-accurate cuts by re-encoding (libx264 CRF 18). Much slower.",
        ),
    ] = False,
    output_dir: OutputDirOpt = None,
    report_path: Annotated[
        Path | None, typer.Option("--report", help="Write the JSON job report here.")
    ] = None,
    dry_run: DryRunOpt = False,
    overwrite: OverwriteOpt = False,
    json_output: JsonOpt = False,
    quiet: QuietOpt = False,
    log_file: LogFileOpt = None,
    log_level: LogLevelOpt = "INFO",
) -> None:
    """Split a video into parts by duration, count, or explicit timestamps."""
    modes = [m for m in (by_duration, by_count, by_timestamps) if m is not None]
    if len(modes) != 1:
        err_console.print(
            "[red bold]error:[/] provide exactly one of --by-duration, --by-count, --by-timestamps"
        )
        raise typer.Exit(EXIT_USAGE)

    try:
        settings, ffmpeg, probe_service = _bootstrap(quiet, log_file, log_level)
        out_dir = output_dir or settings.output_dir
        splitter = SplitterService(ffmpeg, probe_service)

        if by_duration is not None:
            plan = splitter.plan(
                input_file,
                SplitMode.DURATION,
                segment_duration=parse_duration(by_duration),
                precise=precise,
            )
        elif by_count is not None:
            plan = splitter.plan(input_file, SplitMode.COUNT, count=by_count, precise=precise)
        else:
            assert by_timestamps is not None
            plan = splitter.plan(
                input_file,
                SplitMode.TIMESTAMPS,
                ranges=parse_timestamp_ranges(by_timestamps),
                precise=precise,
            )
    except VidKitError as exc:
        _die(exc)
    except Exception as exc:
        _die_unexpected(exc)

    if precise and not quiet and not dry_run:
        err_console.print(
            "[yellow]--precise re-encodes every segment (libx264 CRF 18): expect it to be "
            "many times slower than stream copy.[/yellow]"
        )

    if dry_run:
        commands = [
            [
                "ffmpeg",
                *build_split_command(
                    input_file,
                    part_output_path(input_file, out_dir, seg.index, plan.part_count),
                    seg,
                    precise=precise,
                ),
            ]
            for seg in plan.segments
        ]
        render_plan(plan, commands, Console())
        return

    report = JobReport(command="split")
    try:
        with _make_progress(quiet) as progress:
            task = progress.add_task(f"splitting {input_file.name}", total=plan.part_count)
            for segment in plan.segments:
                result = run_job(
                    lambda event, seg=segment: [  # type: ignore[misc]
                        splitter.execute_segment(
                            plan, seg, out_dir, overwrite=overwrite, cancel_event=event
                        )
                    ],
                    input_file,
                    None,
                )
                report.add(result)
                progress.advance(task)
                if result.status is JobStatus.FAILED:
                    break
    except KeyboardInterrupt:
        report.interrupted = True
        log.warning("interrupt_received", completed=len(report.results))
    except Exception as exc:
        _die_unexpected(exc)

    _finalize_report(report, json_output=json_output, quiet=quiet, report_path=report_path)
    raise typer.Exit(_split_exit_code(report))


def _split_exit_code(report: JobReport) -> int:
    if report.interrupted:
        return EXIT_INTERRUPTED
    if report.failed == 0:
        return 0
    first_failure = next(r for r in report.results if r.status is JobStatus.FAILED)
    return exit_code_for_error_name(first_failure.error_type)


def main() -> None:
    """Entry point for the ``vidkit`` console script."""
    try:
        app(standalone_mode=True)
    except KeyboardInterrupt:  # pragma: no cover - terminal-level safety net
        err_console.print("[red]interrupted[/red]")
        sys.exit(EXIT_INTERRUPTED)


if __name__ == "__main__":
    main()
