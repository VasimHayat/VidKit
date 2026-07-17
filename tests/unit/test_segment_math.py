"""Unit tests for the pure segment-planning functions."""

from __future__ import annotations

import pytest

from vidkit.core.splitter import plan_by_count, plan_by_duration, plan_by_timestamps
from vidkit.exceptions import SplitPlanError


def contiguous(segments: list) -> bool:  # type: ignore[type-arg]
    return all(
        segments[i].end == pytest.approx(segments[i + 1].start) for i in range(len(segments) - 1)
    )


class TestPlanByDuration:
    def test_exact_division(self) -> None:
        segments = plan_by_duration(30.0, 10.0)
        assert [(s.start, s.end) for s in segments] == [(0.0, 10.0), (10.0, 20.0), (20.0, 30.0)]

    def test_final_short_segment(self) -> None:
        segments = plan_by_duration(25.0, 10.0)
        assert len(segments) == 3
        assert segments[-1].start == 20.0
        assert segments[-1].end == 25.0
        assert segments[-1].duration == pytest.approx(5.0)

    def test_single_segment_when_longer_than_total(self) -> None:
        segments = plan_by_duration(30.0, 45.0)
        assert len(segments) == 1
        assert (segments[0].start, segments[0].end) == (0.0, 30.0)

    def test_segment_equal_to_total(self) -> None:
        segments = plan_by_duration(30.0, 30.0)
        assert len(segments) == 1

    def test_dust_tail_absorbed(self) -> None:
        # 30.02 / 10 would leave a 0.02s tail; it must merge into part 3.
        segments = plan_by_duration(30.02, 10.0)
        assert len(segments) == 3
        assert segments[-1].end == pytest.approx(30.02)

    def test_indices_are_sequential(self) -> None:
        segments = plan_by_duration(100.0, 7.0)
        assert [s.index for s in segments] == list(range(len(segments)))
        assert contiguous(segments)

    @pytest.mark.parametrize(
        ("total", "seg"), [(0.0, 10.0), (-5.0, 10.0), (30.0, 0.0), (30.0, -1.0)]
    )
    def test_rejects_non_positive(self, total: float, seg: float) -> None:
        with pytest.raises(SplitPlanError):
            plan_by_duration(total, seg)


class TestPlanByCount:
    def test_equal_parts(self) -> None:
        segments = plan_by_count(30.0, 3)
        assert len(segments) == 3
        assert all(s.duration == pytest.approx(10.0) for s in segments)
        assert contiguous(segments)

    def test_uneven_total_still_covers_everything(self) -> None:
        segments = plan_by_count(10.0, 3)
        assert len(segments) == 3
        assert segments[0].start == 0.0
        assert segments[-1].end == 10.0
        assert contiguous(segments)
        assert sum(s.duration for s in segments) == pytest.approx(10.0)

    def test_count_of_one(self) -> None:
        segments = plan_by_count(30.0, 1)
        assert len(segments) == 1
        assert (segments[0].start, segments[0].end) == (0.0, 30.0)

    def test_no_float_drift_on_many_parts(self) -> None:
        segments = plan_by_count(3600.123, 97)
        assert segments[-1].end == 3600.123
        assert contiguous(segments)

    @pytest.mark.parametrize("count", [0, -3])
    def test_rejects_bad_count(self, count: int) -> None:
        with pytest.raises(SplitPlanError):
            plan_by_count(30.0, count)

    def test_rejects_absurd_count_for_duration(self) -> None:
        with pytest.raises(SplitPlanError, match="shorter than"):
            plan_by_count(1.0, 1000)

    def test_rejects_non_positive_total(self) -> None:
        with pytest.raises(SplitPlanError):
            plan_by_count(0.0, 2)


class TestPlanByTimestamps:
    def test_valid_ranges(self) -> None:
        segments = plan_by_timestamps([(0.0, 330.0), (330.0, 720.0)], 800.0)
        assert len(segments) == 2
        assert segments[0].end == 330.0
        assert segments[1].start == 330.0

    def test_gaps_are_allowed(self) -> None:
        segments = plan_by_timestamps([(0.0, 10.0), (20.0, 30.0)], 30.0)
        assert len(segments) == 2

    def test_unsorted_input_is_ordered(self) -> None:
        segments = plan_by_timestamps([(20.0, 30.0), (0.0, 10.0)], 30.0)
        assert segments[0].start == 0.0
        assert [s.index for s in segments] == [0, 1]

    def test_overlap_rejected(self) -> None:
        with pytest.raises(SplitPlanError, match="overlap"):
            plan_by_timestamps([(0.0, 15.0), (10.0, 20.0)], 30.0)

    def test_out_of_range_rejected(self) -> None:
        with pytest.raises(SplitPlanError, match="exceeds"):
            plan_by_timestamps([(0.0, 60.0)], 30.0)

    def test_small_container_rounding_grace(self) -> None:
        # End may exceed duration by <1s (container rounding); clamped to total.
        segments = plan_by_timestamps([(0.0, 30.5)], 30.0)
        assert segments[0].end == 30.0

    def test_empty_rejected(self) -> None:
        with pytest.raises(SplitPlanError):
            plan_by_timestamps([], 30.0)

    def test_negative_start_rejected(self) -> None:
        with pytest.raises(SplitPlanError):
            plan_by_timestamps([(-1.0, 10.0)], 30.0)
