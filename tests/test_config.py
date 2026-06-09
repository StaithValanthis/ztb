import os
from typing import Any

from ztb.config import Config


def test_default_mode_is_demo() -> None:
    cfg = Config()
    assert cfg.mode == "demo"


def test_config_is_frozen() -> None:
    cfg = Config()
    try:
        object.__setattr__(cfg, "mode", "live")
        raise AssertionError("should be frozen")
    except Exception:
        pass


def test_secrets_excluded_from_repr() -> None:
    cfg = Config(secrets={"ZTB_BYBIT_API_KEY": "sekret"})
    r = repr(cfg)
    assert "sekret" not in r
    assert "secrets" not in r


def test_from_env_no_vars() -> None:
    for key in ["ZTB_BYBIT_API_KEY", "ZTB_BYBIT_API_SECRET", "ZTB_BYBIT_PASSPHRASE"]:
        os.environ.pop(key, None)
    cfg = Config.from_env()
    assert cfg.mode == "demo"
    assert cfg.secrets == {}


def test_from_env_with_vars(monkeypatch: Any) -> None:
    monkeypatch.setenv("ZTB_BYBIT_API_KEY", "test-key")
    monkeypatch.setenv("ZTB_BYBIT_API_SECRET", "test-secret")
    cfg = Config.from_env()
    assert cfg.secrets["ZTB_BYBIT_API_KEY"] == "test-key"
    assert cfg.secrets["ZTB_BYBIT_API_SECRET"] == "test-secret"
