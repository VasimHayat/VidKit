"""Unit tests for settings precedence and worker capping."""

from __future__ import annotations

from pathlib import Path

import pytest

from vidkit.config import MAX_WORKERS_CAP, Settings, default_workers


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for var in (
        "VIDKIT_FFMPEG_PATH",
        "VIDKIT_FFPROBE_PATH",
        "VIDKIT_OUTPUT_DIR",
        "VIDKIT_WORKERS",
        "VIDKIT_FFMPEG_TIMEOUT",
        "VIDKIT_LOG_LEVEL",
        "VIDKIT_LOG_FORMAT",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)  # isolate from any real vidkit.toml


class TestDefaults:
    def test_defaults(self) -> None:
        settings = Settings()
        assert settings.output_dir == Path("./vidkit_out")
        assert 1 <= settings.workers <= MAX_WORKERS_CAP
        assert settings.log_level == "INFO"
        assert settings.ffmpeg_path is None

    def test_default_workers_capped(self) -> None:
        assert default_workers() <= MAX_WORKERS_CAP


class TestPrecedence:
    def test_env_overrides_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VIDKIT_OUTPUT_DIR", "elsewhere")
        assert Settings().output_dir == Path("elsewhere")

    def test_toml_used_when_no_env(self, tmp_path: Path) -> None:
        (tmp_path / "vidkit.toml").write_text(
            'output_dir = "from_toml"\nworkers = 2\n', encoding="utf-8"
        )
        settings = Settings()
        assert settings.output_dir == Path("from_toml")
        assert settings.workers == 2

    def test_env_beats_toml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "vidkit.toml").write_text('output_dir = "from_toml"\n', encoding="utf-8")
        monkeypatch.setenv("VIDKIT_OUTPUT_DIR", "from_env")
        assert Settings().output_dir == Path("from_env")

    def test_init_kwargs_beat_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VIDKIT_OUTPUT_DIR", "from_env")
        assert Settings(output_dir=Path("from_kwargs")).output_dir == Path("from_kwargs")


class TestValidation:
    def test_workers_env_capped_at_max(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VIDKIT_WORKERS", "32")
        assert Settings().workers == MAX_WORKERS_CAP

    def test_workers_below_one_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VIDKIT_WORKERS", "0")
        with pytest.raises(ValueError, match="workers"):
            Settings()

    def test_negative_timeout_rejected(self) -> None:
        with pytest.raises(ValueError, match="ffmpeg_timeout"):
            Settings(ffmpeg_timeout=-1.0)
