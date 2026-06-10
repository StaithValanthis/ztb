from __future__ import annotations


class ExecutionError(Exception):
    pass


class LiveModeBlockedError(ExecutionError):
    def __init__(self) -> None:
        super().__init__("Live mode is blocked in M6 — use --mode demo")


class RiskRejectedError(ExecutionError):
    def __init__(self, reason: str = "") -> None:
        msg = f"Risk manager rejected order: {reason}" if reason else "Risk manager rejected order"
        super().__init__(msg)


class IdempotencyError(ExecutionError):
    pass


class ReconcileError(ExecutionError):
    pass


class ClientError(ExecutionError):
    def __init__(self, status_code: int, body: str = "") -> None:
        self.status_code = status_code
        msg = f"Client error {status_code}: {body}" if body else f"Client error {status_code}"
        super().__init__(msg)


class ClientAuthError(ClientError):
    pass
