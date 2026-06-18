"""Shared fixtures and module imports for tests."""

import importlib.util
import pathlib
import sys

# Make ztb_vr_pass_bridge importable via importlib
_bridge_path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "ztb-vr-pass-bridge.py"
_spec = importlib.util.spec_from_file_location("ztb_vr_pass_bridge", str(_bridge_path))
_bridge_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bridge_mod)

sys.modules["ztb_vr_pass_bridge"] = _bridge_mod

# Make ztb_evidence_gate_check importable via importlib
_gate_path = (
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "ztb-evidence-gate-check.py"
)
_gate_spec = importlib.util.spec_from_file_location("ztb_evidence_gate_check", str(_gate_path))
_gate_mod = importlib.util.module_from_spec(_gate_spec)
_gate_spec.loader.exec_module(_gate_mod)

sys.modules["ztb_evidence_gate_check"] = _gate_mod
