"""Structural consistency checker for Galaxy workflows."""

import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Any

UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


class StructuralChecker:
    """Check Galaxy workflow files for structural issues."""

    @classmethod
    def check(cls, ga_path: Path) -> tuple[List[Dict], Optional[Dict]]:
        """
        Parse a .ga file and check for structural issues.

        Returns (issues, workflow_dict).
        - If the file cannot be parsed, workflow_dict is None.
        - Each issue is a dict: {check, severity, message}
        """
        issues = []

        # 1. JSON parseable and a dict
        try:
            with open(ga_path) as f:
                workflow = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            issues.append({
                "check": "parse",
                "severity": "FAIL",
                "message": f"Cannot parse .ga file: {e}"
            })
            return issues, None

        if not isinstance(workflow, dict):
            issues.append({
                "check": "parse",
                "severity": "FAIL",
                "message": f"Expected a JSON object at top level, got {type(workflow).__name__}"
            })
            return issues, None

        # 2. Galaxy workflow marker
        has_marker = (
            workflow.get("a_galaxy_workflow") == "true"
            or workflow.get("a_galaxy_workflow") is True
            or workflow.get("class") == "GalaxyWorkflow"
        )
        if not has_marker:
            issues.append({
                "check": "galaxy_marker",
                "severity": "FAIL",
                "message": "Missing a_galaxy_workflow=true or class=GalaxyWorkflow",
            })

        # 3. Required top-level fields
        for field in ("steps", "uuid", "name"):
            if field not in workflow:
                issues.append({
                    "check": "required_field",
                    "severity": "FAIL",
                    "message": f"Missing required top-level field: '{field}'",
                })

        # 4. UUID format
        raw_uuid = workflow.get("uuid")
        if raw_uuid is None and "uuid" in workflow:
            issues.append({
                "check": "uuid_format",
                "severity": "FAIL",
                "message": "Workflow UUID is null",
            })
        elif raw_uuid is not None:
            wf_uuid = str(raw_uuid)
            if not UUID_RE.match(wf_uuid):
                issues.append({
                    "check": "uuid_format",
                    "severity": "FAIL",
                    "message": f"Malformed workflow UUID: '{wf_uuid}'",
                })

        # 5. Step connection IDs reference valid steps
        steps = workflow.get("steps", {})
        if not isinstance(steps, dict):
            issues.append({
                "check": "steps_type",
                "severity": "FAIL",
                "message": f"'steps' field must be a dict, got {type(steps).__name__}",
            })
            return issues, workflow

        cls._check_connections(steps, issues)

        return issues, workflow

    @classmethod
    def _check_connections(cls, steps_dict: dict, issues: List[Dict], source_label: str = "parent"):
        """Recursively check step connections."""
        valid_ids_str = set(steps_dict.keys())
        valid_ids_int = {int(k) for k in steps_dict.keys() if str(k).isdigit()}

        for step_id, step in steps_dict.items():
            if not isinstance(step, dict):
                continue

            input_connections = step.get("input_connections", {})
            if not isinstance(input_connections, dict):
                continue

            for input_name, conns in input_connections.items():
                if not isinstance(conns, list):
                    conns = [conns] if conns else []

                for conn in conns:
                    if not isinstance(conn, dict):
                        continue
                    src = conn.get("id")
                    if src is None:
                        continue

                    if str(src) not in valid_ids_str and src not in valid_ids_int:
                        loc = f" [in {source_label}]" if source_label != "parent" else ""
                        issues.append({
                            "check": "connection_ref",
                            "severity": "FAIL",
                            "message": (
                                f"Step {step_id} input '{input_name}' "
                                f"references non-existent step {src}{loc}"
                            ),
                        })

            # Recurse into embedded subworkflows
            if step.get("type") == "subworkflow":
                subwf = step.get("subworkflow", {})
                if isinstance(subwf, dict):
                    sub_steps = subwf.get("steps", {})
                    if isinstance(sub_steps, dict):
                        sub_label = step.get("label") or f"subworkflow_{step_id}"
                        cls._check_connections(sub_steps, issues, source_label=sub_label)
