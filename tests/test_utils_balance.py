from __future__ import annotations

from ztb.utils.balance import extract_available_balance, extract_top_up_credited


def test_extract_available_balance_normal() -> None:
    wallet = {
        "list": [
            {
                "totalAvailableBalance": "500.0",
                "coin": [
                    {
                        "coin": "USDT",
                        "availableBalance": "500.0",
                        "walletBalance": "1000.0",
                    }
                ],
            }
        ]
    }
    result = extract_available_balance(wallet, coin="USDT")
    assert result == 500.0, f"Expected 500.0, got {result}"


def test_extract_available_balance_uta_fallback() -> None:
    wallet = {
        "list": [
            {
                "totalAvailableBalance": "300.0",
                "coin": [
                    {
                        "coin": "USDT",
                        "availableBalance": "0.0",
                        "walletBalance": "1000.0",
                    }
                ],
            }
        ]
    }
    result = extract_available_balance(wallet, coin="USDT")
    assert result == 300.0, f"Expected 300.0, got {result}"


def test_extract_available_balance_uta_fallback_missing_field() -> None:
    wallet = {
        "list": [
            {
                "totalAvailableBalance": "300.0",
                "coin": [
                    {
                        "coin": "USDT",
                        "walletBalance": "1000.0",
                    }
                ],
            }
        ]
    }
    result = extract_available_balance(wallet, coin="USDT")
    assert result == 300.0, f"Expected 300.0, got {result}"


def test_extract_available_balance_prefers_available() -> None:
    wallet = {
        "list": [
            {
                "totalAvailableBalance": "300.0",
                "coin": [
                    {
                        "coin": "USDT",
                        "availableBalance": "500.0",
                        "walletBalance": "1000.0",
                    }
                ],
            }
        ]
    }
    result = extract_available_balance(wallet, coin="USDT")
    assert result == 500.0, f"Expected 500.0, got {result}"


def test_extract_available_balance_empty_wallet() -> None:
    assert extract_available_balance({}) == 0.0
    assert extract_available_balance({"list": []}) == 0.0
    assert extract_available_balance(None) == 0.0  # type: ignore[arg-type]


def test_extract_available_balance_coin_found_all_zero() -> None:
    wallet = {
        "list": [
            {
                "totalAvailableBalance": "0.0",
                "coin": [
                    {
                        "coin": "USDT",
                        "availableBalance": "0.0",
                        "walletBalance": "1000.0",
                    }
                ],
            }
        ]
    }
    result = extract_available_balance(wallet, coin="USDT")
    assert result == 0.0, f"Expected 0.0, got {result}"


def test_extract_available_balance_different_coin() -> None:
    wallet = {
        "list": [
            {
                "totalAvailableBalance": "1000.0",
                "coin": [
                    {
                        "coin": "BTC",
                        "availableBalance": "2.5",
                        "walletBalance": "5.0",
                    },
                    {
                        "coin": "USDT",
                        "availableBalance": "500.0",
                        "walletBalance": "1000.0",
                    },
                ],
            }
        ]
    }
    result_btc = extract_available_balance(wallet, coin="BTC")
    assert result_btc == 2.5, f"Expected 2.5, got {result_btc}"
    result_usdt = extract_available_balance(wallet, coin="USDT")
    assert result_usdt == 500.0, f"Expected 500.0, got {result_usdt}"
    result_eth = extract_available_balance(wallet, coin="ETH")
    assert result_eth == 0.0, f"Expected 0.0, got {result_eth}"


def test_extract_top_up_credited_normal() -> None:
    wallet = {
        "list": [
            {
                "coin": [
                    {
                        "coin": "USDT",
                        "availableBalance": "60000.0",
                        "walletBalance": "100000.0",
                    }
                ],
            }
        ]
    }
    result = extract_top_up_credited(wallet, coin="USDT")
    assert result == 60000.0, f"Expected 60000.0, got {result}"


def test_extract_top_up_credited_prefers_available_over_wallet() -> None:
    wallet = {
        "list": [
            {
                "coin": [
                    {
                        "coin": "USDT",
                        "availableBalance": "60000.0",
                        "walletBalance": "90000.0",
                    }
                ],
            }
        ]
    }
    result = extract_top_up_credited(wallet, coin="USDT")
    assert result == 60000.0, f"Expected 60000.0, got {result}"


def test_extract_top_up_credited_coin_not_found() -> None:
    wallet = {
        "list": [
            {
                "coin": [
                    {
                        "coin": "USDT",
                        "availableBalance": "60000.0",
                    }
                ],
            }
        ]
    }
    result = extract_top_up_credited(wallet, coin="ETH")
    assert result == 0.0, f"Expected 0.0, got {result}"


def test_extract_top_up_credited_coin_not_found_empty() -> None:
    assert extract_top_up_credited({}, coin="USDT") == 0.0
    assert extract_top_up_credited({"list": []}, coin="USDT") == 0.0
    assert extract_top_up_credited(None, coin="USDT") == 0.0  # type: ignore[arg-type]
