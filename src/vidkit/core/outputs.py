"""Safe output-path handling: never overwrite inputs, atomic finalize."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from typing import TYPE_CHECKING

from vidkit.exceptions import OutputExistsError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def clean_output_path(input_path: Path, output_dir: Path) -> Path:
    return output_dir / f"{input_path.stem}_clean{input_path.suffix}"


def part_output_path(input_path: Path, output_dir: Path, index: int, total: int) -> Path:
    width = max(2, len(str(total)))
    return output_dir / f"{input_path.stem}_part{index + 1:0{width}d}{input_path.suffix}"


def check_output(input_path: Path, output_path: Path, *, overwrite: bool) -> None:
    """Refuse to target the input file, or an existing file without --overwrite."""
    if output_path.resolve() == input_path.resolve():
        raise OutputExistsError(f"output would overwrite the input file: {input_path}")
    if output_path.exists() and not overwrite:
        raise OutputExistsError(f"output already exists (use --overwrite): {output_path}")


@contextmanager
def atomic_output(final_path: Path) -> Iterator[Path]:
    """Yield a temp path (same dir, same extension so ffmpeg picks the right
    muxer); atomically rename to ``final_path`` on success, delete on failure.
    """
    final_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = final_path.with_name(
        f".{final_path.stem}.{uuid.uuid4().hex[:8]}.tmp{final_path.suffix}"
    )
    try:
        yield tmp_path
        os.replace(tmp_path, final_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
