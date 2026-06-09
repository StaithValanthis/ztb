from __future__ import annotations

import pytest

from ztb.data.timeframes import INTERVAL_TO_MS, MS_TO_INTERVAL, interval_to_ms, ms_to_interval


class TestIntervalToMs:
    def test_known_intervals(self) -> None:
        assert interval_to_ms("1") == 60_000
        assert interval_to_ms("60") == 3_600_000
        assert interval_to_ms("D") == 86_400_000
        assert interval_to_ms("W") == 604_800_000
        assert interval_to_ms("M") == 2_592_000_000

    def test_unknown_interval_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown interval"):
            interval_to_ms("999")


class TestMsToInterval:
    def test_known_values(self) -> None:
        assert ms_to_interval(60_000) == "1"
        assert ms_to_interval(3_600_000) == "60"
        assert ms_to_interval(86_400_000) == "D"

    def test_unknown_value_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown interval"):
            ms_to_interval(12345)


class TestMappingConsistency:
    def test_round_trip(self) -> None:
        for interval, ms in INTERVAL_TO_MS.items():
            assert ms_to_interval(ms) == interval
            assert interval_to_ms(interval) == ms

    def test_inverse_mapping_complete(self) -> None:
        assert set(MS_TO_INTERVAL.keys()) == set(INTERVAL_TO_MS.values())
        assert set(MS_TO_INTERVAL.values()) == set(INTERVAL_TO_MS.keys())
