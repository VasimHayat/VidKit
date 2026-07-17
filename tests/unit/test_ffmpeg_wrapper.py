"""Unit tests for the FFmpeg wrapper: discovery, version gate, process control.

Uses sys.executable as a stand-in binary so no ffmpeg install is needed.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

from vidkit.config import Settings
from vidkit.core.ffmpeg import MIN_VERSION, FFmpeg, parse_version
from vidkit.exceptions import (
    FFmpegExecutionError,
    FFmpegNotFoundError,
    FFmpegVersionError,
    JobCancelledError,
)


@pytest.fixture
def fake_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> FFmpeg:
    """FFmpeg wrapper whose 'binaries' are the Python interpreter."""
    monkeypatch.delenv("VIDKIT_FFMPEG_PATH", raising=False)
    monkeypatch.delenv("VIDKIT_FFPROBE_PATH", raising=False)
    python = Path(sys.executable)
    return FFmpeg(Settings(ffmpeg_path=python, ffprobe_path=python))


class TestParseVersion:
    def test_release_banner(self) -> None:
        assert parse_version("ffmpeg version 6.1.1-full_build") == (6, 1)

    def test_git_n_banner(self) -> None:
        assert parse_version("ffmpeg version n5.0.3 Copyright") == (5, 0)

    def test_unparseable_raises(self) -> None:
        with pytest.raises(FFmpegVersionError):
            parse_version("ffmpeg version git-2023-nonsense")

    def test_minimum_is_five(self) -> None:
        assert MIN_VERSION == (5, 0)


class TestDiscovery:
    def test_missing_binary_raises_with_install_hint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("VIDKIT_FFMPEG_PATH", raising=False)
        monkeypatch.delenv("VIDKIT_FFPROBE_PATH", raising=False)
        monkeypatch.setattr("shutil.which", lambda _name: None)
        with pytest.raises(FFmpegNotFoundError, match=r"[Ii]nstall"):
            FFmpeg(Settings(ffmpeg_path=None, ffprobe_path=None))

    def test_bad_override_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FFmpegNotFoundError, match="override"):
            FFmpeg(Settings(ffmpeg_path=tmp_path / "nope", ffprobe_path=tmp_path / "nope"))

    def test_directory_override_resolves_binary(self, tmp_path: Path) -> None:
        # A directory containing ffmpeg/ffprobe executables is accepted.
        suffix = ".exe" if sys.platform == "win32" else ""
        for name in ("ffmpeg", "ffprobe"):
            (tmp_path / f"{name}{suffix}").write_bytes(b"#!fake")
        wrapper = FFmpeg(Settings(ffmpeg_path=tmp_path, ffprobe_path=tmp_path))
        assert wrapper.ffmpeg_path.name.startswith("ffmpeg")


class TestRun:
    def test_captures_stdout(self, fake_ffmpeg: FFmpeg) -> None:
        out = fake_ffmpeg._run([sys.executable, "-c", "print('hello')"], timeout=30.0)
        assert out.strip() == "hello"

    def test_nonzero_exit_raises_with_stderr(self, fake_ffmpeg: FFmpeg) -> None:
        with pytest.raises(FFmpegExecutionError) as excinfo:
            fake_ffmpeg._run(
                [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"],
                timeout=30.0,
            )
        assert excinfo.value.stderr == "boom"
        assert "code 3" in str(excinfo.value)
        assert excinfo.value.exit_code == 6

    def test_timeout_kills_process(self, fake_ffmpeg: FFmpeg) -> None:
        with pytest.raises(FFmpegExecutionError, match="timed out"):
            fake_ffmpeg._run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1.0)

    def test_cancel_event_kills_process(self, fake_ffmpeg: FFmpeg) -> None:
        event = threading.Event()
        timer = threading.Timer(0.5, event.set)
        timer.start()
        try:
            with pytest.raises(JobCancelledError):
                fake_ffmpeg._run(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    timeout=60.0,
                    cancel_event=event,
                )
        finally:
            timer.cancel()


class TestPreflight:
    def test_old_version_rejected(
        self, fake_ffmpeg: FFmpeg, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            FFmpeg, "_run", lambda self, argv, timeout, cancel_event=None: "ffmpeg version 4.4.2"
        )
        with pytest.raises(FFmpegVersionError, match="too old"):
            fake_ffmpeg.preflight()

    def test_new_version_accepted(
        self, fake_ffmpeg: FFmpeg, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            FFmpeg, "_run", lambda self, argv, timeout, cancel_event=None: "ffmpeg version 7.1"
        )
        assert "7.1" in fake_ffmpeg.preflight()
