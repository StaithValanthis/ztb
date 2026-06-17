from __future__ import annotations

from typing import Any


def extract_available_balance(wallet: dict[str, Any], coin: str = "USDT") -> float:
    """Extract coin-level availableBalance with UTA fallback.

    Parses a Bybit get_wallet_balance response, summing per-coin
    availableBalance for the given coin. Falls back to account-level
    totalAvailableBalance if coin-level field is missing or zero.
    Returns 0.0 on empty/malformed wallet.
    """
    if not wallet:
        return 0.0
    coin_total = 0.0
    total_available_balance = 0.0
    found_coin = False
    for account_info in wallet.get("list", []):
        total_available_balance += float(account_info.get("totalAvailableBalance", 0.0))
        for coin_entry in account_info.get("coin", []):
            if coin_entry.get("coin", "") == coin:
                found_coin = True
                coin_total += float(coin_entry.get("availableBalance", 0.0))
    if not found_coin:
        return 0.0
    if coin_total > 0:
        return coin_total
    if total_available_balance > 0:
        return total_available_balance
    return 0.0


def extract_top_up_credited(wallet: dict[str, Any], coin: str) -> float:
    """Extract credited amount reading availableBalance or walletBalance.

    Checks availableBalance first; falls back to walletBalance for the brief
    window where funds settle (availableBalance may be 0 right after a
    demo-apply-money call). Returns 0.0 if coin not found.
    """
    if not wallet:
        return 0.0
    for account_info in wallet.get("list", []):
        for coin_entry in account_info.get("coin", []):
            if coin_entry.get("coin", "") == coin:
                available = float(coin_entry.get("availableBalance", 0.0))
                if available > 0:
                    return available
                wallet_bal = float(coin_entry.get("walletBalance", 0.0))
                return wallet_bal
    return 0.0
