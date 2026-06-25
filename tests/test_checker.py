"""
Tests for galaxy_workflow_checker.py.

Two groups:

  * Offline static-check tests (run by default) -- exercise the checker in
    --static-only mode against the fixture .ga files in this folder. No network
    or Galaxy instance is needed, so these are safe to run on every PR.

  * Live keyless smoke test (opt-in) -- runs a real keyless check against
    Galaxy Australia's public tool panel. It is skipped unless the environment
    variable RUN_LIVE_TESTS=1 is set, and auto-skips if the instance is
    unreachable, so it never breaks an offline/CI run by accident.

Usage:
  pytest tests/                       # offline tests only
  RUN_LIVE_TESTS=1 pytest tests/      # also run the live keyless smoke test
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CHECKER = REPO / "galaxy_workflow_checker.py"
TESTS = REPO / "tests"


def run_checker(*args):
    """Run the checker CLI in a subprocess; return combined stdout+stderr."""
    result = subprocess.run(
        [sys.executable, str(CHECKER), *args],
        capture_output=True, text=True,
    )
    return result.stdout + result.stderr


def static_check(fixture):
    """Run a --static-only check against a fixture .ga and return the output."""
    return run_checker("--local-file", str(TESTS / fixture), "--static-only")


# --- Offline static-check tests -------------------------------------------

def test_good_workflow_passes():
    out = static_check("good_workflow.ga")
    assert "Structural consistency:" in out
    assert "PASS" in out
    assert "[FAIL]" not in out
    assert "[WARN]" not in out


def test_broken_connection_detected():
    out = static_check("bad_broken_connection.ga")
    assert "[FAIL]" in out
    assert "connection_ref" in out
    assert "non-existent step" in out


def test_malformed_uuid_detected():
    out = static_check("bad_malformed_uuid.ga")
    assert "[FAIL]" in out
    assert "uuid_format" in out
    assert "Malformed workflow UUID" in out


def test_missing_field_detected():
    out = static_check("bad_missing_field.ga")
    assert "[FAIL]" in out
    assert "required_field" in out
    assert "Missing required top-level field" in out


def test_wiring_gap_detected():
    out = static_check("bad_wiring_gap.ga")
    # Structural passes; the wiring check raises a WARN for the empty input.
    assert "[WARN]" in out
    assert "declared but not connected" in out


# --- Live keyless smoke test (opt-in) -------------------------------------

@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_TESTS") != "1",
    reason="set RUN_LIVE_TESTS=1 to run the live keyless check against Galaxy AU",
)
def test_live_keyless_galaxy_au(tmp_path):
    """Keyless check of WFHub 403 v2.0.8 against Galaxy Australia's public API."""
    out = run_checker(
        "--source", "workflowhub", "--id", "403:v2.0.8",
        "--galaxy-url", "https://usegalaxy.org.au",
        "--output", str(tmp_path / "live"),
        "--workspace", str(tmp_path / "ws"),
    )
    if "Could not retrieve public tool list" in out or "fetching public tool list" in out:
        pytest.skip("Galaxy Australia unreachable")
    # Confirm the keyless path ran and the workflow was processed end-to-end.
    assert "Fetching public tool panel" in out
    assert "ToolShed tools" in out
    assert "Checking version: v2.0.8" in out
