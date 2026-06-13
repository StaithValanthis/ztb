"""Tests for scripts/ztb-vr-pass-bridge.py."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

# Import the script as a module (non-standard name with hyphens)
SCRIPT = Path("scripts/ztb-vr-pass-bridge.py").resolve()
spec = importlib.util.spec_from_file_location("ztb_vr_pass_bridge", SCRIPT)
assert spec is not None
assert spec.loader is not None
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def test_get_vr_pass_status_none_on_empty() -> None:
    """get_vr_pass_status returns None when no statuses exist."""
    with patch.object(bridge, "gh", return_value=[]):
        result = bridge.get_vr_pass_status("o", "r", "abc123")
        assert result is None


def test_get_vr_pass_status_parses_failure() -> None:
    """get_vr_pass_status returns 'failure' when prior status is failure."""
    statuses = [
        {"context": "ztb/vr-pass", "state": "failure"},
    ]
    with patch.object(bridge, "gh", return_value=statuses):
        result = bridge.get_vr_pass_status("o", "r", "abc123")
        assert result == "failure"


def test_get_vr_pass_status_parses_success() -> None:
    """get_vr_pass_status returns 'success' when prior status is success."""
    statuses = [
        {"context": "CI / test (3.11)", "state": "success"},
        {"context": "ztb/vr-pass", "state": "success"},
    ]
    with patch.object(bridge, "gh", return_value=statuses):
        result = bridge.get_vr_pass_status("o", "r", "abc123")
        assert result == "success"


def test_get_vr_pass_status_filters_other_contexts() -> None:
    """get_vr_pass_status ignores non-VR contexts."""
    statuses = [
        {"context": "CI / test (3.11)", "state": "success"},
        {"context": "CI / lint", "state": "success"},
    ]
    with patch.object(bridge, "gh", return_value=statuses):
        result = bridge.get_vr_pass_status("o", "r", "abc123")
        assert result is None


def test_get_vr_pass_status_dict_response() -> None:
    """get_vr_pass_status handles dict response with 'statuses' key."""
    data = {"statuses": [{"context": "ztb/vr-pass", "state": "failure"}]}
    with patch.object(bridge, "gh", return_value=data):
        result = bridge.get_vr_pass_status("o", "r", "abc123")
        assert result == "failure"


def test_get_vr_pass_status_returns_latest() -> None:
    """get_vr_pass_status picks the last (latest) status entry."""
    statuses = [
        {"context": "ztb/vr-pass", "state": "success"},
        {"context": "ztb/vr-pass", "state": "failure"},
    ]
    with patch.object(bridge, "gh", return_value=statuses):
        result = bridge.get_vr_pass_status("o", "r", "abc123")
        assert result == "failure"


def test_prior_fail_main_logic() -> None:
    """Verify the prior-FAIL branch in main() posts failure."""
    posted: list[dict] = []

    def mock_post_status(owner: str, repo: str, sha: str, state: str, description: str) -> None:
        posted.append({"state": state, "description": description})

    with (
        patch.object(bridge, "get_vr_pass_status", return_value="failure"),
        patch.object(bridge, "post_commit_status", mock_post_status),
        patch.object(bridge, "get_ci_conclusion", return_value="success"),
        patch.object(bridge, "get_repo_owner_repo", return_value=("o", "r")),
    ):
        # Run main with mocked args
        import argparse

        old_parse = bridge.argparse.ArgumentParser.parse_args

        def mock_parse(*args: object, **kwargs: object) -> argparse.Namespace:
            return argparse.Namespace(sha="abc123", outcome="PASS", owner="o", repo="r")

        bridge.argparse.ArgumentParser.parse_args = mock_parse  # type: ignore[method-assign]
        try:
            bridge.main()
        finally:
            bridge.argparse.ArgumentParser.parse_args = old_parse

    assert len(posted) == 1
    assert posted[0]["state"] == "failure"
    assert "prior V&R FAIL" in posted[0]["description"]


def test_no_prior_status_main_logic() -> None:
    """No prior V&R status should proceed to CI check."""
    posted: list[dict] = []

    def mock_post_status(owner: str, repo: str, sha: str, state: str, description: str) -> None:
        posted.append({"state": state, "description": description})

    with (
        patch.object(bridge, "get_vr_pass_status", return_value=None),
        patch.object(bridge, "get_ci_conclusion", return_value="success"),
        patch.object(bridge, "post_commit_status", mock_post_status),
        patch.object(bridge, "get_repo_owner_repo", return_value=("o", "r")),
    ):
        import argparse

        old_parse = bridge.argparse.ArgumentParser.parse_args

        def mock_parse(*args: object, **kwargs: object) -> argparse.Namespace:
            return argparse.Namespace(sha="abc123", outcome="PASS", owner="o", repo="r")

        bridge.argparse.ArgumentParser.parse_args = mock_parse  # type: ignore[method-assign]
        try:
            bridge.main()
        finally:
            bridge.argparse.ArgumentParser.parse_args = old_parse

    # Should post success (CI green, no prior FAIL)
    assert len(posted) == 1
    assert posted[0]["state"] == "success"


def test_prior_success_main_logic() -> None:
    """Prior V&R success should not void a new PASS."""
    posted: list[dict] = []

    def mock_post_status(owner: str, repo: str, sha: str, state: str, description: str) -> None:
        posted.append({"state": state, "description": description})

    with (
        patch.object(bridge, "get_vr_pass_status", return_value="success"),
        patch.object(bridge, "get_ci_conclusion", return_value="success"),
        patch.object(bridge, "post_commit_status", mock_post_status),
        patch.object(bridge, "get_repo_owner_repo", return_value=("o", "r")),
    ):
        import argparse

        old_parse = bridge.argparse.ArgumentParser.parse_args

        def mock_parse(*args: object, **kwargs: object) -> argparse.Namespace:
            return argparse.Namespace(sha="abc123", outcome="PASS", owner="o", repo="r")

        bridge.argparse.ArgumentParser.parse_args = mock_parse  # type: ignore[method-assign]
        try:
            bridge.main()
        finally:
            bridge.argparse.ArgumentParser.parse_args = old_parse

    # Should post success (prior was success, CI green)
    assert len(posted) == 1
    assert posted[0]["state"] == "success"
