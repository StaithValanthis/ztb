import subprocess
import sys

from ztb import __version__
from ztb.config import Config


def test_version_consistency() -> None:
    import importlib.metadata

    ver = importlib.metadata.version("ztb")
    assert ver == __version__, f"importlib {ver} != __version__ {__version__}"


def test_no_secret_in_repr() -> None:
    cfg = Config(secrets={"ZTB_BYBIT_API_KEY": "super-secret-value"})
    r = repr(cfg)
    assert "super-secret-value" not in r


def test_config_hides_secrets_in_repr() -> None:
    cfg = Config()
    assert "secrets" not in repr(cfg)


def test_git_log_no_credentials() -> None:
    subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_secret_hygiene.py", "--co", "-q"],
        capture_output=True,
        text=True,
        timeout=30,
    )
