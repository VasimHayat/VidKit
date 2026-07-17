"""Unit tests for safe output-path handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from vidkit.core.outputs import (
    atomic_output,
    check_output,
    clean_output_path,
    part_output_path,
)
from vidkit.exceptions import OutputExistsError


class TestNaming:
    def test_clean_name(self) -> None:
        out = clean_output_path(Path("a/movie.mp4"), Path("out"))
        assert out == Path("out/movie_clean.mp4")

    def test_part_names_zero_padded(self) -> None:
        src = Path("movie.mkv")
        assert part_output_path(src, Path("out"), 0, 3).name == "movie_part01.mkv"
        assert part_output_path(src, Path("out"), 2, 3).name == "movie_part03.mkv"

    def test_part_padding_grows_with_total(self) -> None:
        src = Path("movie.mp4")
        assert part_output_path(src, Path("out"), 0, 120).name == "movie_part001.mp4"
        assert part_output_path(src, Path("out"), 99, 120).name == "movie_part100.mp4"


class TestCheckOutput:
    def test_refuses_overwriting_input(self, tmp_path: Path) -> None:
        target = tmp_path / "a.mp4"
        target.write_bytes(b"x")
        with pytest.raises(OutputExistsError, match="input"):
            check_output(target, target, overwrite=True)

    def test_refuses_existing_without_flag(self, tmp_path: Path) -> None:
        src = tmp_path / "a.mp4"
        out = tmp_path / "a_clean.mp4"
        src.write_bytes(b"x")
        out.write_bytes(b"y")
        with pytest.raises(OutputExistsError, match="--overwrite"):
            check_output(src, out, overwrite=False)

    def test_allows_existing_with_flag(self, tmp_path: Path) -> None:
        src = tmp_path / "a.mp4"
        out = tmp_path / "a_clean.mp4"
        src.write_bytes(b"x")
        out.write_bytes(b"y")
        check_output(src, out, overwrite=True)

    def test_allows_fresh_output(self, tmp_path: Path) -> None:
        src = tmp_path / "a.mp4"
        src.write_bytes(b"x")
        check_output(src, tmp_path / "new.mp4", overwrite=False)


class TestAtomicOutput:
    def test_success_renames_and_removes_temp(self, tmp_path: Path) -> None:
        final = tmp_path / "out" / "result.mp4"
        with atomic_output(final) as tmp:
            assert tmp.parent == final.parent
            assert tmp.suffix == final.suffix  # ffmpeg muxer detection needs it
            tmp.write_bytes(b"video-data")
            assert not final.exists()
        assert final.read_bytes() == b"video-data"
        assert not tmp.exists()

    def test_failure_cleans_temp_and_leaves_no_final(self, tmp_path: Path) -> None:
        final = tmp_path / "result.mp4"
        with pytest.raises(RuntimeError), atomic_output(final) as tmp:
            tmp.write_bytes(b"partial")
            raise RuntimeError("ffmpeg blew up")
        assert not final.exists()
        assert not tmp.exists()

    def test_overwrites_existing_final_atomically(self, tmp_path: Path) -> None:
        final = tmp_path / "result.mp4"
        final.write_bytes(b"old")
        with atomic_output(final) as tmp:
            tmp.write_bytes(b"new")
        assert final.read_bytes() == b"new"
