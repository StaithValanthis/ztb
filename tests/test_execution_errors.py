from __future__ import annotations

from ztb.execution.errors import (
    ClientAuthError,
    ClientError,
    ExecutionError,
    LiveModeBlockedError,
    RiskRejectedError,
)


def test_execution_error_base() -> None:
    err = ExecutionError("base")
    assert str(err) == "base"


def test_live_mode_blocked_error() -> None:
    err = LiveModeBlockedError()
    assert "Live mode is blocked" in str(err)


def test_risk_rejected_error_default() -> None:
    err = RiskRejectedError()
    assert "Risk manager rejected order" in str(err)


def test_risk_rejected_error_with_reason() -> None:
    err = RiskRejectedError("max leverage exceeded")
    assert "max leverage exceeded" in str(err)


def test_client_error_with_body() -> None:
    err = ClientError(400, "bad request")
    assert err.status_code == 400
    assert "bad request" in str(err)


def test_client_error_no_body() -> None:
    err = ClientError(500)
    assert err.status_code == 500


def test_client_auth_error() -> None:
    err = ClientAuthError(401, "invalid api key")
    assert err.status_code == 401
    assert "invalid api key" in str(err)
