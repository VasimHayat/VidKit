"""Pure parsing of timecodes, duration expressions, and timestamp ranges.

Accepted forms:
- timecodes: ``HH:MM:SS``, ``MM:SS``, ``SS`` (each part may carry ``.frac``)
- durations: ``90``, ``90s``, ``10m``, ``1h``, ``1h30m``, ``1h30m15s``, ``2m30s``
- range lists: ``"00:00-05:30,05:30-12:00"`` (either side may be a timecode
  or a duration expression)
"""

from __future__ import annotations

import re

from vidkit.exceptions import SplitPlanError

_DURATION_RE = re.compile(
    r"^(?:(?P<h>\d+(?:\.\d+)?)h)?(?:(?P<m>\d+(?:\.\d+)?)m)?(?:(?P<s>\d+(?:\.\d+)?)s?)?$"
)
_TIMECODE_RE = re.compile(r"^\d+(?:\.\d+)?(?::\d+(?:\.\d+)?){0,2}$")


def parse_timecode(text: str) -> float:
    """``HH:MM:SS`` / ``MM:SS`` / ``SS`` -> seconds."""
    text = text.strip()
    if not text or not _TIMECODE_RE.match(text):
        raise SplitPlanError(f"invalid timecode: {text!r} (expected HH:MM:SS, MM:SS, or SS)")
    parts = [float(p) for p in text.split(":")]
    for sub in parts[1:]:
        if sub >= 60:
            raise SplitPlanError(f"invalid timecode: {text!r} (minutes/seconds must be < 60)")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def _duration_seconds(text: str) -> float:
    raw = text.strip().lower()
    if not raw:
        raise SplitPlanError("duration is empty")
    match = _DURATION_RE.match(raw)
    if match is None or not any(match.groupdict().values()):
        raise SplitPlanError(
            f"invalid duration: {text!r} (expected forms like 90s, 10m, 1h30m, 1h30m15s)"
        )
    hours = float(match.group("h") or 0)
    minutes = float(match.group("m") or 0)
    seconds = float(match.group("s") or 0)
    return hours * 3600 + minutes * 60 + seconds


def parse_duration(text: str) -> float:
    """Duration expression (``1h30m``, ``90s``, ``45``) -> seconds (> 0)."""
    total = _duration_seconds(text)
    if total <= 0:
        raise SplitPlanError(f"duration must be positive: {text!r}")
    return total


def parse_point(text: str) -> float:
    """A range endpoint: timecode if it contains ':', else duration expression.

    Unlike a duration, a point may be zero (a range starting at 0).
    """
    stripped = text.strip()
    if ":" in stripped:
        return parse_timecode(stripped)
    return _duration_seconds(stripped)


def parse_timestamp_ranges(spec: str) -> list[tuple[float, float]]:
    """``"00:00-05:30,05:30-12:00"`` -> [(0.0, 330.0), (330.0, 720.0)]."""
    ranges: list[tuple[float, float]] = []
    if not spec.strip():
        raise SplitPlanError("timestamp range list is empty")
    for chunk in spec.split(","):
        piece = chunk.strip()
        if not piece:
            raise SplitPlanError(f"empty range in timestamp list: {spec!r}")
        left, sep, right = piece.partition("-")
        if not sep or not left.strip() or not right.strip():
            raise SplitPlanError(f"invalid range {piece!r} (expected START-END)")
        start = parse_point(left)
        end = parse_point(right)
        if end <= start:
            raise SplitPlanError(f"range {piece!r}: end must be after start")
        ranges.append((start, end))
    return ranges
