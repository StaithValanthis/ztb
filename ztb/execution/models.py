from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Mode(StrEnum):
    DEMO = "demo"
    LIVE = "live"


class OrderSide(StrEnum):
    BUY = "Buy"
    SELL = "Sell"


class OrderType(StrEnum):
    MARKET = "Market"
    LIMIT = "Limit"


class OrderStatus(StrEnum):
    CREATED = "Created"
    NEW = "New"
    PARTIALLY_FILLED = "PartiallyFilled"
    FILLED = "Filled"
    CANCELLED = "Cancelled"
    REJECTED = "Rejected"


@dataclass
class Order:
    order_id: str
    order_link_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    price: float
    qty: float
    status: OrderStatus
    timestamp: str
    cum_exec_qty: float = 0.0
    cum_exec_value: float = 0.0
    cum_exec_fee: float = 0.0
    reduce_only: bool = False
    reject_reason: str = ""


@dataclass
class Fill:
    exec_id: str
    order_id: str
    symbol: str
    side: OrderSide
    price: float
    qty: float
    commission: float
    realized_pnl: float
    timestamp: str


@dataclass
class Position:
    symbol: str
    size: float
    avg_price: float
    unrealized_pnl: float
    realized_pnl: float
    timestamp: str


@dataclass
class AccountState:
    total_equity: float
    wallet_balance: float
    unrealized_pnl: float
    available_balance: float = 0.0
    total_available_balance: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    timestamp: str = ""


@dataclass
class ExecRunConfig:
    mode: Mode = Mode.DEMO
    dry_run: bool = False
    once: bool = False
    loop: bool | None = None
    poll_interval_seconds: float | None = None
    initial_cash: float = 100_000.0
    commission: float = 0.0005
    slippage: float = 0.0
    asset_precision: int = 8
    warmup_bars: int = 100
    lookback_bars: int | None = None
    risk_enabled: bool = True
    max_position_pct: float = 0.50
    max_leverage: float = 3.0
    order_sizing_buffer: float = 0.95

    def __post_init__(self) -> None:
        if self.loop is None:
            self.loop = self.mode == Mode.DEMO and not self.once and not self.dry_run
        if self.poll_interval_seconds is None:
            self.poll_interval_seconds = 60
        if self.lookback_bars is None:
            self.lookback_bars = 0


@dataclass
class ExecBar:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    confirmed: bool


@dataclass
class ExecRunState:
    strategy_name: str
    symbol: str
    timeframe: str
    mode: Mode
    run_id: str
    exec_run_id: str
    current_position: float = 0.0
    avg_entry_price: float = 0.0
    total_cost: float = 0.0
    realized_pnl: float = 0.0
    total_commission: float = 0.0
    total_slippage: float = 0.0
    bars_processed: int = 0
    last_bar_ts: str = ""
    status: str = "running"
    errors: list[str] = field(default_factory=list)
