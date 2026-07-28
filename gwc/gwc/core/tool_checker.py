"""Tool availability checker for Galaxy workflows."""

from typing import List, Dict, Set, Union

from ..utils.version_utils import parse_version, mismatch_direction


class ToolChecker:
    """Check tool availability in a Galaxy instance."""

    @classmethod
    def extract_tools(cls, workflow: Dict, source_label: str = "parent") -> List[Dict]:
        """
        Recursively extract ToolShed tool IDs from a workflow dict.

        Returns a list of {id, source} dicts.
        """
        seen: Dict[str, str] = {}
        steps = workflow.get("steps", {})
        if not isinstance(steps, dict):
            return []

        for step in steps.values():
            if not isinstance(step, dict):
                continue

            tool_id = step.get("tool_id")
            if tool_id and "toolshed.g2.bx.psu.edu" in tool_id:
                if tool_id not in seen:
                    seen[tool_id] = source_label

            if step.get("type") == "subworkflow":
                subwf = step.get("subworkflow", {})
                if isinstance(subwf, dict):
                    sub_label = step.get("label") or f"subworkflow_{step.get('id', '?')}"
                    for entry in cls.extract_tools(subwf, source_label=sub_label):
                        if entry["id"] not in seen:
                            seen[entry["id"]] = entry["source"]

        return [{"id": tid, "source": src} for tid, src in seen.items()]

    @classmethod
    def build_cache(cls, tools: List[Dict]) -> Dict[str, Set[str]]:
        """
        Build mapping of base tool ID -> set of installed versions.

        Base ID format: toolshed.g2.bx.psu.edu/repos/{owner}/{repo}/{toolname}
        Version format: {x.y.z}+galaxyN
        """
        cache: Dict[str, Set[str]] = {}
        for t in tools:
            tid = t.get("id", "")
            if "toolshed" in tid:
                parts = tid.split("/")
                if len(parts) >= 6:
                    base = "/".join(parts[:5])
                    version = parts[5]
                    cache.setdefault(base, set()).add(version)
        return cache

    @classmethod
    def check_tools(cls, tool_entries: List, cache: Dict[str, Set[str]]) -> List[Dict]:
        """
        Classify each workflow tool against the Galaxy tool cache.

        Returns a list of dicts with:
          id, base, version, status, source, available_versions
        """
        results = []

        for entry in tool_entries:
            if isinstance(entry, dict):
                tid = entry["id"]
                source = entry.get("source", "parent")
            else:
                tid = entry
                source = "parent"

            parts = tid.split("/")
            if len(parts) < 6:
                results.append({
                    "id": tid,
                    "base": tid,
                    "version": None,
                    "status": "unversioned",
                    "source": source,
                })
                continue

            base = "/".join(parts[:5])
            version = parts[5]

            if base not in cache:
                results.append({
                    "id": tid,
                    "base": base,
                    "version": version,
                    "status": "missing",
                    "source": source,
                })
            elif version in cache[base]:
                results.append({
                    "id": tid,
                    "base": base,
                    "version": version,
                    "status": "exact_match",
                    "source": source,
                })
            else:
                avail = sorted(cache[base], key=parse_version)
                results.append({
                    "id": tid,
                    "base": base,
                    "version": version,
                    "status": "version_mismatch",
                    "available_versions": avail,
                    "version_direction": mismatch_direction(version, avail),
                    "source": source,
                })

        return results
