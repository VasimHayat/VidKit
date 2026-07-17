"""Unit tests for timecode/duration/range parsing (no ffmpeg required)."""

from __future__ import annotations

import pytest

from vidkit.core.timeparse import (
    parse_duration,
    parse_point,
    parse_timecode,
    parse_timestamp_ranges,
)
from vidkit.exceptions import SplitPlanError


class TestParseTimecode:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("00:00:00", 0.0),
            ("01:02:03", 3723.0),
            ("05:30", 330.0),
            ("90", 90.0),
            ("00:00:01.5", 1.5),
            ("1:00:00", 3600.0),
            ("0:59", 59.0),
        ],
    )
    def test_valid(self, text: str, expected: float) -> None:
        assert parse_timecode(text) == pytest.approx(expected)

    @pytest.mark.parametrize("text", ["", "abc", "1:2:3:4", "00:61", "00:60:00", "-5", "1h"])
    def test_invalid(self, text: str) -> None:
        with pytest.raises(SplitPlanError):
            parse_timecode(text)


class TestParseDuration:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("90s", 90.0),
            ("10m", 600.0),
            ("1h", 3600.0),
            ("1h30m", 5400.0),
            ("1h30m15s", 5415.0),
            ("2m30s", 150.0),
            ("45", 45.0),
            ("0.5s", 0.5),
            ("1.5h", 5400.0),
            ("90S", 90.0),
        ],
    )
    def test_valid(self, text: str, expected: float) -> None:
        assert parse_duration(text) == pytest.approx(expected)

    @pytest.mark.parametrize("text", ["", "0", "0s", "abc", "-90s", "m30", "10x", "h", "1d"])
    def test_invalid(self, text: str) -> None:
        with pytest.raises(SplitPlanError):
            parse_duration(text)


class TestParsePoint:
    def test_zero_is_a_valid_point(self) -> None:
        assert parse_point("0") == 0.0
        assert parse_point("0s") == 0.0
        assert parse_point("00:00") == 0.0

    def test_timecode_and_duration_forms(self) -> None:
        assert parse_point("05:30") == 330.0
        assert parse_point("5m30s") == 330.0


class TestParseTimestampRanges:
    def test_basic(self) -> None:
        assert parse_timestamp_ranges("00:00-05:30,05:30-12:00") == [
            (0.0, 330.0),
            (330.0, 720.0),
        ]

    def test_mixed_forms(self) -> None:
        assert parse_timestamp_ranges("0-90s,2m-03:00") == [(0.0, 90.0), (120.0, 180.0)]

    def test_whitespace_tolerated(self) -> None:
        assert parse_timestamp_ranges(" 00:00 - 00:10 , 00:10 - 00:20 ") == [
            (0.0, 10.0),
            (10.0, 20.0),
        ]

    @pytest.mark.parametrize(
        "spec",
        ["", "00:00", "00:10-00:05", "00:00-", "-00:10", "00:00-00:10,,00:20-00:30", "a-b"],
    )
    def test_invalid(self, spec: str) -> None:
        with pytest.raises(SplitPlanError):
            parse_timestamp_ranges(spec)
