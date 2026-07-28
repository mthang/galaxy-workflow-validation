"""Wiring gap checker for Galaxy workflows."""

from typing import List, Dict


class WiringChecker:
    """Check tool steps for missing or empty input connections."""

    # Skip types that don't need connections
    SKIP_TYPES = {"data_input", "data_collection_input", "parameter_input", "pause"}

    @classmethod
    def check(cls, workflow: Dict, source_label: str = "parent", skip_types: set = None) -> List[Dict]:
        """
        Check tool steps for missing or empty input connections.

        Returns a list of issue dicts: {step_id, step_label, tool_id, source, severity, message}
        """
        issues = []
        steps = workflow.get("steps", {})
        if not isinstance(steps, dict):
            return issues

        skip = skip_types or cls.SKIP_TYPES

        for step_id, step in steps.items():
            if not isinstance(step, dict):
                continue

            step_type = step.get("type", "tool")
            if step_type in skip:
                continue

            if step_type == "subworkflow":
                continue  # handled below

            tool_id = step.get("tool_id", "")
            if not tool_id:
                continue

            # Derive human-readable step label
            raw_label = step.get("label") or ""
            if not raw_label and "/" in tool_id:
                raw_label = tool_id.split("/")[-2]
            step_label = raw_label or f"step_{step_id}"

            input_connections = step.get("input_connections", {})
            if not isinstance(input_connections, dict):
                input_connections = {}

            for input_name, conns in input_connections.items():
                if not isinstance(conns, list):
                    conns = [conns] if conns else []

                if not conns:
                    issues.append({
                        "step_id": step_id,
                        "step_label": step_label,
                        "tool_id": tool_id,
                        "source": source_label,
                        "input": input_name,
                        "severity": "WARN",
                        "message": (
                            f"Step {step_id} ({step_label}) input '{input_name}': "
                            "declared but not connected to any upstream step"
                        ),
                    })

        # Recurse into subworkflows
        for step_id, step in steps.items():
            if not isinstance(step, dict):
                continue
            if step.get("type") == "subworkflow":
                subwf = step.get("subworkflow", {})
                if isinstance(subwf, dict):
                    sub_label = step.get("label") or f"subworkflow_{step_id}"
                    issues.extend(cls.check(subwf, source_label=sub_label, skip_types=skip))

        return issues
