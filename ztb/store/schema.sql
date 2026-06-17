CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    strategy_name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    run_type TEXT NOT NULL DEFAULT 'backtest',
    parameters TEXT NOT NULL DEFAULT '{}',
    splits TEXT NOT NULL DEFAULT '{}',
    code_version TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    sufficient_sample INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS metrics (
    metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    scope TEXT NOT NULL CHECK (scope IN ('full', 'is', 'oos')),
    total_return REAL,
    sharpe REAL,
    sortino REAL,
    max_drawdown REAL,
    max_drawdown_duration INTEGER,
    num_trades INTEGER NOT NULL DEFAULT 0,
    profit_factor REAL,
    win_rate REAL,
    turnover REAL NOT NULL DEFAULT 0.0,
    exposure_time REAL NOT NULL DEFAULT 0.0,
    sufficient_sample INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    UNIQUE(run_id, scope)
);

CREATE INDEX IF NOT EXISTS idx_metrics_run_scope ON metrics(run_id, scope);
CREATE INDEX IF NOT EXISTS idx_metrics_scope_sharpe ON metrics(scope, sharpe);

CREATE TABLE IF NOT EXISTS trades (
    trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    timestamp TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL,
    pnl REAL NOT NULL,
    commission REAL NOT NULL,
    slippage REAL NOT NULL DEFAULT 0.0,
    sl_price REAL,
    tp_price REAL,
    exit_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_trades_run ON trades(run_id);

CREATE TABLE IF NOT EXISTS equity_curve (
    point_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    timestamp TEXT NOT NULL,
    equity REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_equity_run ON equity_curve(run_id);

CREATE TABLE IF NOT EXISTS risk_decisions (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('proceed', 'reduce', 'halt')),
    reason TEXT NOT NULL DEFAULT '',
    max_pos_size REAL NOT NULL DEFAULT 0.0,
    max_leverage REAL NOT NULL DEFAULT 0.0,
    max_notional REAL NOT NULL DEFAULT 0.0,
    current_dd REAL,
    current_heat REAL,
    hwm REAL
);

CREATE INDEX IF NOT EXISTS idx_risk_decisions_run ON risk_decisions(run_id);



INSERT OR IGNORE INTO schema_meta (version) VALUES (1);
INSERT OR IGNORE INTO schema_meta (version) VALUES (2);
INSERT OR IGNORE INTO schema_meta (version) VALUES (3);
INSERT OR IGNORE INTO schema_meta (version) VALUES (5);
