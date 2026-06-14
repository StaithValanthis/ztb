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
    slippage REAL NOT NULL DEFAULT 0.0
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

CREATE TABLE IF NOT EXISTS validation_runs (
    val_run_id TEXT PRIMARY KEY,
    strategy_name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    val_type TEXT NOT NULL DEFAULT 'walkforward',
    n_windows INTEGER NOT NULL DEFAULT 0,
    avg_oos_sharpe REAL,
    avg_oos_return REAL,
    avg_oos_maxdd REAL,
    avg_oos_trades REAL NOT NULL DEFAULT 0.0,
    sharpe_consistency REAL,
    return_consistency REAL,
    maxdd_consistency REAL,
    all_windows_valid INTEGER NOT NULL DEFAULT 0,
    overall_score REAL,
    sharpe_score REAL,
    dsr_score REAL,
    walkforward_score REAL,
    consistency_score REAL,
    drawdown_score REAL,
    parameters TEXT NOT NULL DEFAULT '{}',
    details TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS validation_windows (
    window_id INTEGER PRIMARY KEY AUTOINCREMENT,
    val_run_id TEXT NOT NULL REFERENCES validation_runs(val_run_id),
    window_idx INTEGER NOT NULL,
    train_start INTEGER NOT NULL,
    train_end INTEGER NOT NULL,
    test_start INTEGER NOT NULL,
    test_end INTEGER NOT NULL,
    train_duration_bars INTEGER NOT NULL DEFAULT 0,
    test_duration_bars INTEGER NOT NULL DEFAULT 0,
    train_sharpe REAL,
    train_return REAL,
    train_maxdd REAL,
    train_trades INTEGER NOT NULL DEFAULT 0,
    test_sharpe REAL,
    test_return REAL,
    test_maxdd REAL,
    test_trades INTEGER NOT NULL DEFAULT 0,
    UNIQUE(val_run_id, window_idx)
);

CREATE INDEX IF NOT EXISTS idx_val_windows_run ON validation_windows(val_run_id);
CREATE INDEX IF NOT EXISTS idx_val_runs_score ON validation_runs(overall_score);

INSERT OR IGNORE INTO schema_meta (version) VALUES (1);
INSERT OR IGNORE INTO schema_meta (version) VALUES (2);
INSERT OR IGNORE INTO schema_meta (version) VALUES (3);
INSERT OR IGNORE INTO schema_meta (version) VALUES (5);
