from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from ztb.data.errors import DataError, FetchError, IntegrityError
from ztb.data.integrity import IntegrityReport
from ztb.data.loader import _raw_to_dataframe, load, load_with_funding
from ztb.data.schema import OHLCV_COLUMNS


class _MockClient:
    def __init__(self, pages: list[list[dict[str, Any]]] | None = None) -> None:
        self.pages = pages or []
        self.call_count = 0

    def get_kline(
        self,
        category: str,
        symbol: str,
        interval: str,
        start: int | None = None,
        end: int | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        self.call_count += 1
        if self.call_count > len(self.pages):
            return []
        return self.pages[self.call_count - 1]

    def get_funding_rate_history(
        self,
        symbol: str,
        category: str = "linear",
        start: int | None = None,
        end: int | None = None,
        limit: int = 200,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        return ([], None)

    def get_instruments_info(
        self,
        category: str,
        symbol: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        return []

    def get_server_time(self) -> dict[str, Any]:
        return {"timeSecond": 1700000000, "timeNano": "1700000000000000000"}


def _raw_bar(
    ts: int,
    o: float = 50000,
    h: float = 50100,
    low_val: float = 49900,
    c: float = 50050,
    v: float = 100,
    t: float = 5000000,
) -> dict[str, str]:
    return {
        "start": str(ts),
        "open": str(o),
        "high": str(h),
        "low": str(low_val),
        "close": str(c),
        "volume": str(v),
        "turnover": str(t),
    }


def _make_raw_pages(start_ts: int, n_bars: int = 10, n_pages: int = 1) -> list[list[dict[str, str]]]:
    pages = []
    for p in range(n_pages):
        page = []
        for i in range(n_bars):
            ts = start_ts + (p * n_bars + i) * 3600000
            page.append(_raw_bar(ts))
        pages.append(page)
    return pages


class TestRawToDataFrame:
    def test_dict_input(self) -> None:
        raw: list[dict[str, Any]] = [
            {
                "start": "1700000000000",
                "open": "50000",
                "high": "50100",
                "low": "49900",
                "close": "50050",
                "volume": "100",
                "turnover": "5000000",
            }
        ]
        df = _raw_to_dataframe(raw)
        assert len(df) == 1
        assert list(df.columns) == OHLCV_COLUMNS
        assert df.index.name == "open_time"

    def test_list_input(self) -> None:
        raw: list[Any] = [["1700000000000", "50000", "50100", "49900", "50050", "100", "5000000"]]
        df = _raw_to_dataframe(raw)
        assert len(df) == 1
        for col in OHLCV_COLUMNS:
            assert col in df.columns

    def test_empty_input(self) -> None:
        df = _raw_to_dataframe([])
        assert len(df) == 0
        for col in OHLCV_COLUMNS:
            assert col in df.columns

    def test_schema_valid(self) -> None:
        raw = [_raw_bar(1700000000000)]
        df = _raw_to_dataframe(raw)
        assert isinstance(df.index.dtype, pd.DatetimeTZDtype)
        assert str(df.index.dtype.tz) == "UTC"
        for col in OHLCV_COLUMNS:
            assert df[col].dtype == "float64"


class TestLoad:
    def test_fetch_returns_data(self) -> None:
        pages = _make_raw_pages(start_ts=1700000000000, n_bars=5)
        client: Any = _MockClient(pages)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            df = load(
                "BTCUSDT",
                "60",
                category="linear",
                start="2023-11-15",
                end="2023-11-15T05:00:00",
                client=client,
                cache_base=base,
            )
            assert len(df) > 0
            assert list(df.columns) == OHLCV_COLUMNS
            assert df.index.name == "open_time"
            assert df.index.is_monotonic_increasing

    def test_no_data_raises_fetch_error(self) -> None:
        client: Any = _MockClient(pages=[])
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with pytest.raises(FetchError):
                load(
                    "NONEXISTENT",
                    "60",
                    category="linear",
                    start="2023-11-15",
                    end="2023-11-15T05:00:00",
                    client=client,
                    cache_base=base,
                )

    def test_invalid_timeframe_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with pytest.raises((ValueError, DataError)):
                load(
                    "BTCUSDT",
                    "999",
                    category="linear",
                    start="2023-11-15",
                    end="2023-11-15T05:00:00",
                    cache_base=base,
                )


class TestColdWarmDeterminism:
    def _get_timestamps(self) -> tuple[str, str]:
        first_ts = pd.Timestamp(1700000000000, unit="ms", tz="UTC")
        last_ts = pd.Timestamp(1700000000000 + 4 * 3600000, unit="ms", tz="UTC")
        return first_ts.strftime("%Y-%m-%dT%H:%M:%S"), last_ts.strftime("%Y-%m-%dT%H:%M:%S")

    def test_cold_equals_warm(self) -> None:
        start, end = self._get_timestamps()
        pages = _make_raw_pages(start_ts=1700000000000, n_bars=5)
        client: Any = _MockClient(pages)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            df_cold = load(
                "BTCUSDT",
                "60",
                category="linear",
                start=start,
                end=end,
                client=client,
                cache_base=base,
            )
            df_warm = load(
                "BTCUSDT",
                "60",
                category="linear",
                start=start,
                end=end,
                client=client,
                cache_base=base,
            )
            pd.testing.assert_frame_equal(df_cold, df_warm)

    def test_delta_fetch_spy_zero_http(self) -> None:
        start, end = self._get_timestamps()
        pages = _make_raw_pages(start_ts=1700000000000, n_bars=5)
        client: Any = _MockClient(pages)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            load(
                "BTCUSDT",
                "60",
                category="linear",
                start=start,
                end=end,
                client=client,
                cache_base=base,
            )
            client2 = _MockClient()
            load(
                "BTCUSDT",
                "60",
                category="linear",
                start=start,
                end=end,
                client=client2,
                cache_base=base,
            )
            assert client2.call_count == 0


class TestLoadWithFunding:
    def test_perp_returns_funding_column(self) -> None:
        pages = _make_raw_pages(start_ts=1700000000000, n_bars=5)
        client: Any = _MockClient(pages)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            df = load_with_funding(
                "BTCUSDT",
                "60",
                category="linear",
                start="2023-11-15",
                end="2023-11-15T05:00:00",
                client=client,
                cache_base=base,
            )
            assert "funding_rate" in df.columns
            assert (df["funding_rate"] == 0.0).all()

    def test_spot_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with pytest.raises(ValueError, match="not supported for spot"):
                load_with_funding(
                    "BTCUSDT",
                    "60",
                    category="spot",
                    start="2023-11-15",
                    end="2023-11-15T05:00:00",
                    cache_base=base,
                )


class TestRangeBounds:
    def test_start_end_inclusive(self) -> None:
        pages = _make_raw_pages(start_ts=1700000000000, n_bars=10)
        client: Any = _MockClient(pages)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            start = "2023-11-15"
            end = "2023-11-15T05:00:00"
            df = load(
                "BTCUSDT",
                "60",
                category="linear",
                start=start,
                end=end,
                client=client,
                cache_base=base,
            )
            assert len(df) > 0
            start_ts = pd.Timestamp(start, tz="UTC")
            end_ts = pd.Timestamp(end, tz="UTC")
            assert df.index[0] >= start_ts
            assert df.index[-1] <= end_ts


class TestLoadEdgeCases:
    def test_load_without_end(self) -> None:
        pages = _make_raw_pages(start_ts=1700000000000, n_bars=5)
        client: Any = _MockClient(pages)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            df = load(
                "BTCUSDT",
                "60",
                category="linear",
                start="2023-11-14T23:00:00",
                client=client,
                cache_base=base,
            )
            assert len(df) > 0
            assert df.index[0] >= pd.Timestamp("2023-11-14T23:00:00", tz="UTC")

    def test_load_without_start(self) -> None:
        pages = _make_raw_pages(start_ts=1700000000000, n_bars=5)
        client: Any = _MockClient(pages)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            df = load(
                "BTCUSDT",
                "60",
                category="linear",
                end="2023-11-15T05:00:00",
                client=client,
                cache_base=base,
            )
            assert len(df) > 0

    def test_load_without_start_or_end(self) -> None:
        """Cover lines 91-92: neither start nor end specified."""
        pages = _make_raw_pages(start_ts=1700000000000, n_bars=5)
        client: Any = _MockClient(pages)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            df = load(
                "BTCUSDT",
                "60",
                category="linear",
                client=client,
                cache_base=base,
            )
            assert len(df) > 0

    def test_load_default_client(self) -> None:
        pages = _make_raw_pages(start_ts=1700000000000, n_bars=5)
        client: Any = _MockClient(pages)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with patch("ztb.data.loader._default_client") as mock_default:
                mock_default.return_value = client
                df = load(
                    "BTCUSDT",
                    "60",
                    category="linear",
                    start="2023-11-14T23:00:00",
                    end="2023-11-15T03:00:00",
                    cache_base=base,
                )
                assert len(df) > 0

    def test_load_no_cache_base_defaults(self) -> None:
        """Cover line 50: cache_base defaults to DEFAULT_CACHE_DIR."""
        pages = _make_raw_pages(start_ts=1700000000000, n_bars=5)
        client: Any = _MockClient(pages)
        with tempfile.TemporaryDirectory() as tmp:
            saved = Path(tmp)
            with patch("ztb.data.loader.DEFAULT_CACHE_DIR", saved):
                df = load(
                    "BTCUSDT",
                    "60",
                    category="linear",
                    start="2023-11-14T23:00:00",
                    end="2023-11-15T03:00:00",
                    client=client,
                )
                assert len(df) > 0

    def test_empty_raw_raises(self) -> None:
        """Cover line 95: empty raw data raises FetchError."""
        pages = _make_raw_pages(start_ts=1700000000000, n_bars=0)
        client: Any = _MockClient(pages)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with pytest.raises(FetchError):
                load(
                    "BTCUSDT",
                    "60",
                    category="linear",
                    start="2023-11-14T23:00:00",
                    end="2023-11-15T03:00:00",
                    client=client,
                    cache_base=base,
                )

    def test_cache_merge_path(self) -> None:
        """Cover line 101: merge with existing cache."""
        pages = _make_raw_pages(start_ts=1700000000000, n_bars=10)
        client: Any = _MockClient(pages)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            df_first = load(
                "BTCUSDT",
                "60",
                category="linear",
                start="2023-11-14T23:00:00",
                end="2023-11-15T02:00:00",
                client=client,
                cache_base=base,
            )
            assert len(df_first) > 0

    def test_integrity_failure_raises(self) -> None:
        """Cover line 110: integrity check failure raises IntegrityError."""
        pages = _make_raw_pages(start_ts=1700000000000, n_bars=5)
        client: Any = _MockClient(pages)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            bad_report = IntegrityReport(
                has_gaps=True,
                gap_count=1,
                gap_ranges=[
                    (pd.Timestamp("2023-11-15", tz="UTC"), pd.Timestamp("2023-11-16", tz="UTC"))
                ],
                has_dupes=False,
                dupe_count=0,
                is_monotonic=True,
                is_ascending=True,
                is_unique=True,
                is_fresh=True,
                freshness_seconds=0.0,
                n_bars=5,
                launch_time=None,
            )
            with (
                patch("ztb.data.loader.check_integrity", return_value=bad_report),
                pytest.raises(IntegrityError),
            ):
                load(
                    "BTCUSDT",
                    "60",
                    category="linear",
                    start="2023-11-14T23:00:00",
                    end="2023-11-15T03:00:00",
                    client=client,
                    cache_base=base,
                )

    def test_cache_with_start_only(self) -> None:
        """Cover lines 74-77: cache covers start, no end."""
        pages = _make_raw_pages(start_ts=1700000000000, n_bars=10)
        client: Any = _MockClient(pages)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            load(
                "BTCUSDT",
                "60",
                category="linear",
                start="2023-11-14T23:00:00",
                end="2023-11-15T06:00:00",
                client=client,
                cache_base=base,
            )
            first_bar_ts = pd.Timestamp(1700000000000, unit="ms", tz="UTC")
            # Use a start that's AFTER the cache first bar to hit lines 74-77
            later_start = (first_bar_ts + pd.Timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
            new_client: Any = _MockClient()
            df = load(
                "BTCUSDT",
                "60",
                category="linear",
                start=later_start,
                client=new_client,
                cache_base=base,
            )
            assert len(df) > 0

    def test_cache_with_end_only(self) -> None:
        """Cover lines 78-81: cache covers end, no start."""
        pages = _make_raw_pages(start_ts=1700000000000, n_bars=10)
        client: Any = _MockClient(pages)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            load(
                "BTCUSDT",
                "60",
                category="linear",
                start="2023-11-14T23:00:00",
                end="2023-11-15T06:00:00",
                client=client,
                cache_base=base,
            )
            end_within = "2023-11-15T03:00:00"
            new_client: Any = _MockClient()
            df = load(
                "BTCUSDT",
                "60",
                category="linear",
                end=end_within,
                client=new_client,
                cache_base=base,
            )
            assert len(df) > 0
