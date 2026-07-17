"""The only module allowed to spawn subprocesses.

Wraps ffmpeg/ffprobe with binary discovery, version preflight, timeouts,
cooperative cancellation, and typed errors carrying captured stderr.
"""

from __future__ import annotations

import contextlib
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from vidkit.exceptions import (
    FFmpegExecutionError,
    FFmpegNotFoundError,
    FFmpegVersionError,
    JobCancelledError,
)
from vidkit.logging import get_logger

if TYPE_CHECKING:
    from vidkit.config import Settings

log = get_logger(__name__)

MIN_VERSION = (5, 0)
_POLL_INTERVAL = 0.1

_INSTALL_HINTS = {
    "Windows": "winget install Gyan.FFmpeg   (or: choco install ffmpeg)",
    "Darwin": "brew install ffmpeg",
    "Linux": "sudo apt install ffmpeg   (or your distro's equivalent)",
}


class CancelEvent(Protocol):
    """Anything with is_set(); satisfied by threading/multiprocessing Events."""

    def is_set(self) -> bool: ...


def _install_hint() -> str:
    return _INSTALL_HINTS.get(platform.system(), "see https://ffmpeg.org/download.html")


def _locate(name: str, override: Path | None) -> Path:
    if override is not None:
        if override.is_file():
            return override
        # Allow VIDKIT_FFMPEG_PATH to point at the bin directory too.
        candidate = override / f"{name}.exe" if platform.system() == "Windows" else override / name
        if candidate.is_file():
            return candidate
        raise FFmpegNotFoundError(
            f"{name} override path does not exist: {override}. "
            f"Fix VIDKIT_{name.upper()}_PATH or install ffmpeg: {_install_hint()}"
        )
    found = shutil.which(name)
    if found is None:
        raise FFmpegNotFoundError(
            f"{name} was not found on PATH. Install it and retry: {_install_hint()}"
        )
    return Path(found)


def parse_version(banner: str) -> tuple[int, int]:
    """Extract (major, minor) from an ffmpeg/ffprobe version banner."""
    match = re.search(r"version\s+n?(\d+)\.(\d+)", banner)
    if match is None:
        raise FFmpegVersionError(
            f"could not parse ffmpeg version from banner: {banner.splitlines()[0]!r}"
        )
    return int(match.group(1)), int(match.group(2))


class FFmpeg:
    """Locates and executes ffmpeg/ffprobe. Never uses shell=True."""

    def __init__(self, settings: Settings) -> None:
        self.ffmpeg_path = _locate("ffmpeg", settings.ffmpeg_path)
        self.ffprobe_path = _locate("ffprobe", settings.ffprobe_path)
        self.timeout = settings.ffmpeg_timeout

    def preflight(self) -> str:
        """Verify both binaries run and meet MIN_VERSION. Returns the version banner."""
        banner = ""
        for binary in (self.ffmpeg_path, self.ffprobe_path):
            out = self._run([str(binary), "-version"], timeout=30.0)
            major, minor = parse_version(out)
            if (major, minor) < MIN_VERSION:
                raise FFmpegVersionError(
                    f"{binary.name} {major}.{minor} is too old; VidKit requires "
                    f">= {MIN_VERSION[0]}.{MIN_VERSION[1]}. Upgrade: {_install_hint()}"
                )
            banner = out.splitlines()[0]
        return banner

    def run_ffmpeg(
        self,
        args: list[str],
        *,
        timeout: float | None = None,
        cancel_event: CancelEvent | None = None,
    ) -> str:
        argv = [str(self.ffmpeg_path), "-hide_banner", "-nostdin", *args]
        return self._run(argv, timeout=timeout or self.timeout, cancel_event=cancel_event)

    def run_ffprobe(
        self,
        args: list[str],
        *,
        timeout: float | None = None,
        cancel_event: CancelEvent | None = None,
    ) -> str:
        argv = [str(self.ffprobe_path), *args]
        return self._run(argv, timeout=timeout or self.timeout, cancel_event=cancel_event)

    def _run(
        self,
        argv: list[str],
        *,
        timeout: float,
        cancel_event: CancelEvent | None = None,
    ) -> str:
        """Run a command, polling for timeout and cooperative cancellation."""
        log.debug("subprocess_start", argv=argv, timeout=timeout)
        started = time.monotonic()
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    self._kill(proc)
                    raise JobCancelledError(f"cancelled: {Path(argv[0]).name}")
                elapsed = time.monotonic() - started
                if elapsed > timeout:
                    self._kill(proc)
                    raise FFmpegExecutionError(
                        f"{Path(argv[0]).name} timed out after {timeout:.0f}s",
                        argv=argv,
                        stderr="",
                    )
                try:
                    stdout, stderr = proc.communicate(timeout=_POLL_INTERVAL)
                    break
                except subprocess.TimeoutExpired:
                    continue
        except BaseException:
            if proc.poll() is None:
                self._kill(proc)
            raise

        elapsed = time.monotonic() - started
        if proc.returncode != 0:
            log.debug(
                "subprocess_failed",
                argv=argv,
                returncode=proc.returncode,
                elapsed=round(elapsed, 3),
            )
            raise FFmpegExecutionError(
                f"{Path(argv[0]).name} exited with code {proc.returncode}",
                argv=argv,
                stderr=stderr or "",
            )
        log.debug("subprocess_ok", argv=argv, elapsed=round(elapsed, 3))
        return stdout or ""

    @staticmethod
    def _kill(proc: subprocess.Popen[str]) -> None:
        proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):  # pragma: no cover - defensive
            proc.communicate(timeout=5)
