"""Rendering of probe results, split plans, and job reports."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table

if TYPE_CHECKING:
    from rich.console import Console

    from vidkit.models import JobReport, MediaInfo, SegmentPlan


def format_seconds(seconds: float) -> str:
    whole = int(seconds)
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    frac = seconds - whole
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{round(frac * 1000):03d}"


def render_probe(info: MediaInfo, console: Console) -> None:
    summary = Table(title=str(info.path), show_header=False, min_width=60)
    summary.add_row("Container", info.format_name)
    summary.add_row("Duration", format_seconds(info.duration))
    summary.add_row("Size", f"{info.size_bytes / 1_048_576:.2f} MiB")
    if info.bit_rate:
        summary.add_row("Bitrate", f"{info.bit_rate / 1000:.0f} kb/s")
    summary.add_row("Chapters", str(info.chapter_count))
    console.print(summary)

    streams = Table(title="Streams")
    streams.add_column("#")
    streams.add_column("Type")
    streams.add_column("Codec")
    streams.add_column("Tags")
    for stream in info.streams:
        tag_text = ", ".join(f"{k}={v}" for k, v in stream.tags.items()) or "-"
        streams.add_row(str(stream.index), stream.codec_type, stream.codec_name, tag_text)
    console.print(streams)

    inventory = info.tag_inventory
    tags = Table(title="Metadata inventory")
    tags.add_column("Location")
    tags.add_column("Key")
    tags.add_column("Value")
    if inventory:
        for location, entries in inventory.items():
            for key, value in entries.items():
                tags.add_row(location, key, value)
    else:
        tags.add_row("-", "-", "no metadata tags found")
    console.print(tags)


def render_plan(plan: SegmentPlan, commands: list[list[str]], console: Console) -> None:
    table = Table(
        title=f"Split plan: {plan.source.name} "
        f"({plan.mode.value}, {'precise re-encode' if plan.precise else 'stream copy'})"
    )
    table.add_column("Part")
    table.add_column("Start")
    table.add_column("End")
    table.add_column("Length")
    for segment in plan.segments:
        table.add_row(
            str(segment.index + 1),
            format_seconds(segment.start),
            format_seconds(segment.end),
            format_seconds(segment.duration),
        )
    console.print(table)
    if commands:
        console.print("[bold]Commands that would run:[/bold]")
        for argv in commands:
            console.print("  " + " ".join(argv), highlight=False, soft_wrap=True)


def render_report(report: JobReport, console: Console) -> None:
    table = Table(title=f"VidKit {report.command} report")
    table.add_column("Input")
    table.add_column("Status")
    table.add_column("Time (s)", justify="right")
    table.add_column("Outputs / Reason")
    styles = {"succeeded": "green", "failed": "red", "skipped": "yellow"}
    for result in report.results:
        if result.outputs:
            detail = "\n".join(str(p) for p in result.outputs)
        else:
            detail = result.error_message or "-"
        table.add_row(
            str(result.input_path),
            f"[{styles[result.status.value]}]{result.status.value}[/]",
            f"{result.elapsed_seconds:.1f}",
            detail,
        )
    console.print(table)
    summary = (
        f"[green]{report.succeeded} succeeded[/] · "
        f"[red]{report.failed} failed[/] · "
        f"[yellow]{report.skipped} skipped[/]"
    )
    if report.interrupted:
        summary += " · [red bold]interrupted[/]"
    console.print(summary)
