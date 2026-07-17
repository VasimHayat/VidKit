"""Batch execution: input expansion, worker pool, cancellation, aggregation.

Worker functions live at module top level so they pickle under the Windows
``spawn`` start method. Workers ignore SIGINT; the parent catches it, sets a
shared cancel event (which makes workers kill their in-flight ffmpeg), and
returns a partial report.
"""

from __future__ import annotations

import glob as globmod
import multiprocessing
import signal
import time
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from pathlib import Path
from typing import TYPE_CHECKING

from vidkit.config import MAX_WORKERS_CAP, Settings
from vidkit.core.cleaner import CleanerService
from vidkit.core.ffmpeg import FFmpeg
from vidkit.core.probe import ProbeService
from vidkit.exceptions import InvalidMediaError, JobCancelledError, VidKitError
from vidkit.logging import configure_logging, get_logger
from vidkit.models import JobResult, JobStatus

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from vidkit.core.ffmpeg import CancelEvent

log = get_logger(__name__)

VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".m4v", ".mkv", ".mov", ".avi", ".webm", ".mpg", ".mpeg", ".ts", ".wmv", ".flv"}
)


def expand_inputs(spec: str) -> list[Path]:
    """Resolve a file path, directory, or glob pattern into candidate files."""
    path = Path(spec)
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(
            p for p in path.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
        )
    matches = sorted(Path(m) for m in globmod.glob(spec, recursive=True))
    files = [m for m in matches if m.is_file()]
    if not files:
        raise InvalidMediaError(f"no input files match: {spec}")
    return files


def run_job(
    job: Callable[[CancelEvent | None], list[Path]],
    input_path: Path,
    cancel_event: CancelEvent | None,
) -> JobResult:
    """Execute one job callable, mapping exceptions to a structured result."""
    started = time.monotonic()
    try:
        outputs = job(cancel_event)
    except InvalidMediaError as exc:
        log.warning("job_skipped", input=str(input_path), reason=str(exc))
        return JobResult.skipped(input_path, str(exc))
    except JobCancelledError as exc:
        log.info("job_cancelled", input=str(input_path))
        return JobResult.failed(input_path, exc, elapsed=time.monotonic() - started)
    except VidKitError as exc:
        log.error("job_failed", input=str(input_path), error=str(exc), kind=type(exc).__name__)
        return JobResult.failed(input_path, exc, elapsed=time.monotonic() - started)
    return JobResult(
        input_path=input_path,
        status=JobStatus.SUCCEEDED,
        outputs=outputs,
        elapsed_seconds=time.monotonic() - started,
    )


def _pool_initializer(settings_dump: dict[str, object]) -> None:
    """Runs in each worker process: quiet SIGINT (parent coordinates shutdown)
    and configure logging to match the parent."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    settings = Settings.model_validate(settings_dump)
    configure_logging(level=settings.log_level, log_format="json", quiet=True)


def clean_worker(
    settings_dump: dict[str, object],
    input_path: Path,
    output_dir: Path,
    overwrite: bool,
    cancel_event: CancelEvent | None,
) -> JobResult:
    """Top-level worker: clean one file inside a pool process."""
    settings = Settings.model_validate(settings_dump)
    ffmpeg = FFmpeg(settings)
    cleaner = CleanerService(ffmpeg, ProbeService(ffmpeg))

    def job(event: CancelEvent | None) -> list[Path]:
        return [cleaner.clean(input_path, output_dir, overwrite=overwrite, cancel_event=event)]

    return run_job(job, input_path, cancel_event)


class BatchRunner:
    """Fan a list of inputs across a process pool, reporting progress."""

    def __init__(self, settings: Settings, workers: int) -> None:
        self._settings = settings
        self._workers = max(1, min(workers, MAX_WORKERS_CAP))

    def run_clean(
        self,
        inputs: Iterable[Path],
        output_dir: Path,
        *,
        overwrite: bool,
        on_result: Callable[[JobResult], None],
    ) -> bool:
        """Run clean jobs; calls ``on_result`` as each finishes.

        Returns True if the run was interrupted (SIGINT).
        """
        input_list = list(inputs)
        settings_dump = self._settings.model_dump(mode="json")
        interrupted = False

        with multiprocessing.Manager() as manager:
            cancel_event = manager.Event()
            with ProcessPoolExecutor(
                max_workers=min(self._workers, max(1, len(input_list))),
                initializer=_pool_initializer,
                initargs=(settings_dump,),
            ) as executor:
                futures: dict[Future[JobResult], Path] = {
                    executor.submit(
                        clean_worker, settings_dump, path, output_dir, overwrite, cancel_event
                    ): path
                    for path in input_list
                }
                pending = set(futures)
                try:
                    while pending:
                        done, pending = wait(pending, return_when=FIRST_COMPLETED)
                        for future in done:
                            on_result(self._collect(future, futures[future]))
                except KeyboardInterrupt:
                    interrupted = True
                    log.warning("interrupt_received", pending=len(pending))
                    cancel_event.set()
                    for future in pending:
                        future.cancel()
                    done, still_running = wait(pending, timeout=15.0)
                    for future in done:
                        if not future.cancelled():
                            on_result(self._collect(future, futures[future]))
                    for future in still_running:  # pragma: no cover - defensive
                        on_result(
                            JobResult.failed(
                                futures[future], JobCancelledError("worker did not stop in time")
                            )
                        )
        return interrupted

    @staticmethod
    def _collect(future: Future[JobResult], input_path: Path) -> JobResult:
        try:
            return future.result()
        except Exception as exc:
            log.error("worker_crashed", input=str(input_path), error=str(exc))
            return JobResult.failed(input_path, exc)
