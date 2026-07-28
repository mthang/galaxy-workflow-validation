"""Core workflow analysis engine."""

from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from .structural_checker import StructuralChecker
from .wiring_checker import WiringChecker
from .tool_checker import ToolChecker


class WorkflowAnalyzer:
    """Analyze Galaxy workflows for issues."""

    @classmethod
    def analyze(cls, ga_path: Path, tool_cache: Dict, skip_types: set = None) -> Dict:
        """
        Run all static checks on a downloaded .ga file.

        Order of checks:
          1. Structural consistency -- aborts remaining checks on FAIL
          2. Wiring gaps -- runs if structural check passes
          3. Tool availability -- includes subworkflow tools automatically
        """
        # --- 1. Structural consistency ---
        structural_issues, workflow_dict = StructuralChecker.check(ga_path)
        structural_fails = [i for i in structural_issues if i["severity"] == "FAIL"]

        if structural_fails or workflow_dict is None:
            return {
                "total_tools": 0,
                "n_exact": 0,
                "n_version_mismatch": 0,
                "n_missing": 0,
                "n_wiring_issues": 0,
                "n_structural_issues": len(structural_issues),
                "workflow_status": "structural_error",
                "ready_to_run": False,
                "structural_issues": structural_issues,
                "wiring_issues": [],
                "tool_statuses": [],
                "ga_path": str(ga_path),
            }

        # --- 2. Wiring gaps ---
        wiring_issues = WiringChecker.check(workflow_dict, skip_types=skip_types)

        # --- 3. Tool availability ---
        tool_entries = ToolChecker.extract_tools(workflow_dict)
        classified = ToolChecker.check_tools(tool_entries, tool_cache) if tool_cache else []

        exact = [t for t in classified if t["status"] == "exact_match"]
        mismatch = [t for t in classified if t["status"] == "version_mismatch"]
        missing = [t for t in classified if t["status"] == "missing"]

        # Overall status precedence:
        # tool errors > wiring warnings > no_toolshed_tools > ready
        if missing:
            workflow_status = "missing_tool"
        elif mismatch:
            workflow_status = "version_mismatch"
        elif wiring_issues:
            workflow_status = "wiring_issues"
        elif not classified:
            workflow_status = "no_toolshed_tools"
        else:
            workflow_status = "ready"

        return {
            "total_tools": len(tool_entries),
            "n_exact": len(exact),
            "n_version_mismatch": len(mismatch),
            "n_missing": len(missing),
            "n_wiring_issues": len(wiring_issues),
            "n_structural_issues": len(structural_issues),
            "workflow_status": workflow_status,
            "ready_to_run": workflow_status == "ready",
            "structural_issues": structural_issues,
            "wiring_issues": wiring_issues,
            "tool_statuses": classified,
            "ga_path": str(ga_path),
        }
