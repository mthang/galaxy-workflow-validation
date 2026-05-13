#!/usr/bin/env python3
"""
Galaxy Workflow Tool Checker
Checks whether all tools required by Galaxy workflows are installed in a
target Galaxy instance (e.g. Galaxy Australia), without needing to run the workflow.

Supports workflows from Dockstore and/or WorkflowHub.
Reads Galaxy credentials from an existing Planemo profile.

Usage examples:
  # Check latest version of a WorkflowHub workflow by ID
  python galaxy_workflow_checker.py --source workflowhub --id 645

  # Check 3 most recent versions of a Dockstore workflow
  python galaxy_workflow_checker.py --source dockstore \
      --entry "github.com/iwc-workflows/Assembly-decontamination-VGP9/main" \
      --versions 3

  # Search both sources by keyword, check latest version of each result
  python galaxy_workflow_checker.py --source both --search "VGP" --versions latest

  # List matching workflows without checking tools
  python galaxy_workflow_checker.py --source workflowhub --search "assembly" --list-only
"""

import json
import sys
import os
import re
import subprocess
import argparse
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Union, Any, Set
from datetime import datetime

try:
    import urllib.request
    import urllib.parse
    import urllib.error
except ImportError:
    pass

try:
    from bioblend.galaxy import GalaxyInstance
    from bioblend import toolshed
    BIOBLEND_AVAILABLE = True
except ImportError:
    BIOBLEND_AVAILABLE = False
    print("Warning: BioBlend not installed. Install with: pip install bioblend")

WORKFLOWHUB_TRS_BASE = "https://workflowhub.eu/ga4gh/trs/v2"
WORKFLOWHUB_BASE = "https://workflowhub.eu"
DOCKSTORE_BASE = "https://dockstore.org"


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def read_planemo_profile(profile_name: str) -> Tuple[str, str]:
    """Read Galaxy URL and API key from a Planemo profile config file."""
    path = (Path.home() / ".planemo" / "profiles" /
            profile_name / "planemo_profile_options.json")
    if not path.exists():
        print(f"Error: Planemo profile not found at {path}")
        print("  Create a profile with:")
        print(f"  planemo profile_create {profile_name} --galaxy_url <url> "
              f"--galaxy_user_key <key> --engine external_galaxy")
        sys.exit(1)
    with open(path) as f:
        config = json.load(f)
    url = config.get("galaxy_url")
    key = config.get("galaxy_user_key")
    if not url or not key:
        print(f"Error: galaxy_url or galaxy_user_key missing in profile {profile_name}")
        sys.exit(1)
    return url, key


# ---------------------------------------------------------------------------
# Galaxy tool cache
# ---------------------------------------------------------------------------

def build_galaxy_tool_cache(galaxy_url: str, galaxy_key: str) -> Dict[str, set]:
    """
    Fetch all tools installed in Galaxy and return a mapping of
    base tool ID -> set of installed versions.
    Base ID format: toolshed.g2.bx.psu.edu/repos/{owner}/{repo}/{toolname}
    Version format: {x.y.z}+galaxyN (or whatever suffix convention is used)
    """
    if not BIOBLEND_AVAILABLE:
        print("Error: BioBlend required for Galaxy tool checking.")
        sys.exit(1)
    print(f"\nConnecting to Galaxy at {galaxy_url}...")
    gi = GalaxyInstance(url=galaxy_url, key=galaxy_key)
    try:
        tools = gi.tools.get_tools()
    except Exception as e:
        print(f"Error: Could not retrieve tools from Galaxy: {e}")
        sys.exit(1)
    cache: Dict[str, set] = {}
    for t in tools:
        tid = t.get("id", "")
        if "toolshed" in tid:
            # toolshed.g2.bx.psu.edu/repos/owner/repo/toolname/version
            parts = tid.split("/")
            if len(parts) >= 6:
                base = "/".join(parts[:5])
                version = parts[5]
                cache.setdefault(base, set()).add(version)
    print(f"  Found {len(tools)} tools installed ({len(cache)} unique ToolShed tools)")
    return cache


# ---------------------------------------------------------------------------
# Structural consistency check
# ---------------------------------------------------------------------------

UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)

def check_structural_consistency(ga_path: Path) -> Tuple[List[Dict], Optional[Dict]]:
    """
    Parse a .ga file and check for structural issues before any other check.

    Returns (issues, workflow_dict).
    - If the file cannot be parsed, workflow_dict is None and further checks
      should be skipped.
    - Each issue is a dict: {check, severity, message}
      severity: "FAIL" = hard error that will prevent import/run,
                "WARN" = advisory only.
    """
    issues = []

    # 1. JSON parseable
    try:
        with open(ga_path) as f:
            workflow = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        issues.append({"check": "parse", "severity": "FAIL",
                       "message": f"Cannot parse .ga file: {e}"})
        return issues, None

    # 2. Galaxy workflow marker
    has_marker = (
        workflow.get("a_galaxy_workflow") == "true"
        or workflow.get("a_galaxy_workflow") is True
        or workflow.get("class") == "GalaxyWorkflow"
    )
    if not has_marker:
        issues.append({
            "check": "galaxy_marker", "severity": "FAIL",
            "message": "Missing a_galaxy_workflow=true or class=GalaxyWorkflow",
        })

    # 3. Required top-level fields
    for field in ("steps", "uuid", "name"):
        if field not in workflow:
            issues.append({
                "check": "required_field", "severity": "FAIL",
                "message": f"Missing required top-level field: '{field}'",
            })

    # 4. UUID format — skip if uuid field is absent (already flagged above) or null
    raw_uuid = workflow.get("uuid")
    if raw_uuid is None and "uuid" in workflow:
        issues.append({
            "check": "uuid_format", "severity": "FAIL",
            "message": "Workflow UUID is null",
        })
    elif raw_uuid is not None:
        wf_uuid = str(raw_uuid)
        if not UUID_RE.match(wf_uuid):
            issues.append({
                "check": "uuid_format", "severity": "FAIL",
                "message": f"Malformed workflow UUID: '{wf_uuid}'",
            })

    # 5. Step connection IDs reference valid steps
    steps = workflow.get("steps", {})
    if not isinstance(steps, dict):
        issues.append({
            "check": "steps_type", "severity": "FAIL",
            "message": f"'steps' field must be a dict, got {type(steps).__name__}",
        })
        return issues, workflow
    valid_ids_str = set(steps.keys())
    valid_ids_int = {int(k) for k in steps.keys() if str(k).isdigit()}

    for step_id, step in steps.items():
        for input_name, conns in step.get("input_connections", {}).items():
            if not isinstance(conns, list):
                conns = [conns] if conns else []
            for conn in conns:
                if not isinstance(conn, dict):
                    continue
                src = conn.get("id")
                if src is None:
                    continue
                if str(src) not in valid_ids_str and src not in valid_ids_int:
                    issues.append({
                        "check": "connection_ref", "severity": "FAIL",
                        "message": (
                            f"Step {step_id} input '{input_name}' "
                            f"references non-existent step {src}"
                        ),
                    })

    return issues, workflow


# ---------------------------------------------------------------------------
# Wiring gaps check
# ---------------------------------------------------------------------------

_SKIP_TYPES = {"data_input", "data_collection_input", "parameter_input", "pause"}


def check_wiring_gaps(workflow: Dict, source_label: str = "parent") -> List[Dict]:
    """
    Check tool steps for missing or empty input connections.

    Without querying the Galaxy tool XML we cannot determine which inputs are
    required vs optional, so all flagged steps are reported as WARN.  The
    caller should note this limitation in the report.

    Also recurses into embedded subworkflows.

    Returns a list of issue dicts: {step_id, step_label, tool_id, source,
    severity, message}
    """
    issues = []
    steps = workflow.get("steps", {})
    if not isinstance(steps, dict):
        return issues  # structural check will have caught this already

    for step_id, step in steps.items():
        step_type = step.get("type", "tool")
        if step_type in _SKIP_TYPES:
            continue
        if step_type == "subworkflow":
            # recurse — handled below
            continue

        tool_id = step.get("tool_id", "")
        if not tool_id:
            continue  # skip steps with no tool_id (e.g. pause steps)

        # Derive a human-readable step label
        raw_label = step.get("label") or ""
        if not raw_label and "/" in tool_id:
            # use the tool name segment from the toolshed ID
            raw_label = tool_id.split("/")[-2]
        step_label = raw_label or f"step_{step_id}"

        input_connections = step.get("input_connections", {})

        if not input_connections:
            issues.append({
                "step_id": step_id,
                "step_label": step_label,
                "tool_id": tool_id,
                "source": source_label,
                "severity": "WARN",
                "message": (
                    f"Step {step_id} ({step_label}): no input connections — "
                    "relies entirely on hardcoded parameters or has no inputs"
                ),
            })
        else:
            for input_name, conns in input_connections.items():
                if not isinstance(conns, list):
                    conns = [conns] if conns else []
                # Empty list = input declared but nothing connected
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

    # Recurse into subworkflow steps
    for step_id, step in steps.items():
        if step.get("type") == "subworkflow":
            subwf = step.get("subworkflow", {})
            if subwf:
                sub_label = step.get("label") or f"subworkflow_{step_id}"
                issues.extend(check_wiring_gaps(subwf, source_label=sub_label))

    return issues


# ---------------------------------------------------------------------------
# Tool extraction from .ga file (with subworkflow recursion)
# ---------------------------------------------------------------------------

def _extract_tools_from_dict(workflow: Dict,
                              source_label: str = "parent") -> List[Dict]:
    """
    Recursively extract ToolShed tool IDs from a workflow dict, including any
    embedded subworkflows.  Returns a list of {id, source} dicts where source
    is "parent" for the top-level workflow or the subworkflow label.
    """
    seen: Dict[str, str] = {}  # id -> source (first occurrence wins)
    steps = workflow.get("steps", {})
    if not isinstance(steps, dict):
        return []  # structural check will have caught this already
    for step in steps.values():
        tool_id = step.get("tool_id")
        if tool_id and "toolshed.g2.bx.psu.edu" in tool_id:
            if tool_id not in seen:
                seen[tool_id] = source_label
        if step.get("type") == "subworkflow":
            subwf = step.get("subworkflow", {})
            if subwf:
                sub_label = step.get("label") or f"subworkflow_{step.get('id', '?')}"
                for entry in _extract_tools_from_dict(subwf, source_label=sub_label):
                    if entry["id"] not in seen:
                        seen[entry["id"]] = entry["source"]
    return [{"id": tid, "source": src} for tid, src in seen.items()]


def extract_tools_from_ga(ga_path: Path) -> List[str]:
    """
    Parse a Galaxy workflow (.ga) file and return a deduplicated sorted list
    of ToolShed tool IDs required by the workflow steps.
    Built-in Galaxy tools (no toolshed URL) are skipped.
    Includes tools from embedded subworkflows.
    """
    with open(ga_path) as f:
        workflow = json.load(f)
    entries = _extract_tools_from_dict(workflow)
    return sorted(e["id"] for e in entries)


def _version_tuple(v: str) -> tuple:
    """
    Convert a tool version string to a sortable tuple for comparison.
    Strips +galaxyN suffix before parsing, e.g. '2.1.0+galaxy1' -> (2, 1, 0).
    Non-numeric segments become 0.
    """
    base = v.split("+")[0]  # drop +galaxyN
    parts = []
    for seg in base.split("."):
        try:
            parts.append(int(seg))
        except ValueError:
            parts.append(0)
    return tuple(parts) if parts else (0,)


def _mismatch_direction(wanted: str, available: List[str]) -> str:
    """
    Given the version the workflow wants and the list of installed versions,
    return a human-readable label describing the direction of the gap.

    Returns one of:
      "installed older"  — all installed versions are older than wanted
      "installed newer"  — all installed versions are newer than wanted
      "mixed"            — installed versions span both sides of wanted
    """
    wt = _version_tuple(wanted)
    older = [v for v in available if _version_tuple(v) < wt]
    newer = [v for v in available if _version_tuple(v) > wt]
    if older and not newer:
        return "installed older"
    if newer and not older:
        return "installed newer"
    return "mixed"


def check_tools(tool_entries: List, cache: Dict[str, set]) -> List[Dict]:
    """
    Classify each workflow tool against the Galaxy tool cache.
    Strict version matching: a tool is exact_match only if the exact
    versioned ID (including +galaxyN suffix) is installed.

    tool_entries: list of tool ID strings OR {id, source} dicts.

    Returns a list of dicts, one per tool, with:
      id       -- full versioned tool ID as found in the workflow
      base     -- base tool ID (no version)
      version  -- version string from the workflow (may be None)
      status   -- "exact_match" | "version_mismatch" | "missing" | "unversioned"
      source   -- "parent" or subworkflow label
      available_versions -- sorted list of installed versions (version_mismatch only)
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
                "id": tid, "base": tid, "version": None,
                "status": "unversioned", "source": source,
            })
            continue
        base = "/".join(parts[:5])
        version = parts[5]
        if base not in cache:
            results.append({
                "id": tid, "base": base, "version": version,
                "status": "missing", "source": source,
            })
        elif version in cache[base]:
            results.append({
                "id": tid, "base": base, "version": version,
                "status": "exact_match", "source": source,
            })
        else:
            avail = sorted(cache[base])
            results.append({
                "id": tid, "base": base, "version": version,
                "status": "version_mismatch",
                "available_versions": avail,
                "version_direction": _mismatch_direction(version, avail),
                "source": source,
            })
    return results


# ---------------------------------------------------------------------------
# WorkflowHub TRS helpers
# ---------------------------------------------------------------------------

def trs_get(path: str, params: dict = None) -> Any:
    """GET request to the WorkflowHub TRS API."""
    url = WORKFLOWHUB_TRS_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} for {url}")
        return None
    except Exception as e:
        print(f"  Request error: {e}")
        return None


def search_workflowhub(name: str = None, organization: str = None,
                       max_results: int = 10) -> List[Dict]:
    """Search WorkflowHub for Galaxy workflows via TRS API."""
    params = {"descriptorType": "GALAXY", "limit": 100, "offset": 0}
    if name:
        params["name"] = name
    if organization:
        params["organization"] = organization
    results = []
    while len(results) < max_results:
        page = trs_get("/tools", params)
        if not page:
            break
        galaxy_wfs = [
            w for w in page
            if any("GALAXY" in v.get("descriptor_type", [])
                   for v in w.get("versions", []))
        ]
        results.extend(galaxy_wfs)
        if len(page) < params["limit"]:
            break
        params["offset"] += params["limit"]
    return results[:max_results]


def get_workflowhub_workflow(workflow_id: str) -> Optional[Dict]:
    return trs_get(f"/tools/{workflow_id}")


def get_workflowhub_galaxy_versions(workflow: Dict) -> List[Dict]:
    """Return versions that have a GALAXY descriptor, oldest-first."""
    versions = [v for v in workflow.get("versions", [])
                if "GALAXY" in v.get("descriptor_type", [])]
    return versions


def download_workflowhub_ga(workflow_id: str, version_id: str,
                             workspace: Path, workflow_name: str = None) -> Optional[Path]:
    """Download a .ga file from WorkflowHub TRS."""
    safe_name = (workflow_name or workflow_id).replace("/", "_").replace(" ", "_")[:60]
    dest_dir = workspace / f"workflowhub_{workflow_id}" / f"v{version_id}"
    dest_dir.mkdir(parents=True, exist_ok=True)

    descriptor = trs_get(f"/tools/{workflow_id}/versions/{version_id}/GALAXY/descriptor")
    if not descriptor or "content" not in descriptor:
        print(f"  Failed to download descriptor for {workflow_id}:{version_id}")
        return None
    content = descriptor["content"]
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        print(f"  Descriptor is not valid JSON for {workflow_id}:{version_id}")
        return None
    if not (parsed.get("a_galaxy_workflow") or parsed.get("class") == "GalaxyWorkflow"):
        print(f"  Warning: content may not be a Galaxy workflow")

    # Use original filename from TRS file listing if available
    files = trs_get(f"/tools/{workflow_id}/versions/{version_id}/GALAXY/files") or []
    ga_filename = next(
        (f["path"] for f in files if f.get("file_type") == "PRIMARY_DESCRIPTOR"), None
    )
    if not ga_filename:
        raw_name = (parsed.get("name") or f"workflow_{workflow_id}").strip()
        ga_filename = raw_name.replace("/", "_") + ".ga"

    ga_path = dest_dir / ga_filename
    with open(ga_path, "w") as f:
        f.write(content)
    return ga_path


# ---------------------------------------------------------------------------
# Dockstore helpers
# ---------------------------------------------------------------------------

def search_dockstore(pattern: str, max_results: int = 10) -> List[Dict]:
    """Search Dockstore for workflows matching a pattern."""
    cmd = ["dockstore", "workflow", "search", "--pattern", pattern]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        print("Error: dockstore CLI not found. Install it to use --source dockstore.")
        return []
    workflows = []
    if result.returncode == 0:
        for line in result.stdout.strip().split("\n")[1:]:
            if line.strip() and not line.startswith("-"):
                parts = line.split()
                if parts and "/" in parts[0]:
                    entry = parts[0].strip("*").strip()
                    workflows.append({
                        "entry": entry,
                        "name": entry.split("/")[-1],
                        "url": f"{DOCKSTORE_BASE}/workflows/{entry}",
                    })
    return workflows[:max_results]


DOCKSTORE_TRS_BASE = "https://dockstore.org/api/ga4gh/trs/v2"


def _dockstore_trs_get(path: str) -> Any:
    """GET request to the Dockstore TRS API."""
    url = DOCKSTORE_TRS_BASE + path
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} for {url}")
        return None
    except Exception as e:
        print(f"  Request error: {e}")
        return None


def _dockstore_tool_id(entry: str) -> str:
    """Convert a Dockstore entry path to a URL-encoded TRS tool ID."""
    return urllib.parse.quote(f"#workflow/{entry}", safe="")


def get_dockstore_versions(entry: str) -> List[str]:
    """Return version names for a Dockstore workflow via TRS API, newest first.
    Falls back to the CLI if the API call fails."""
    tool_id = _dockstore_tool_id(entry)
    data = _dockstore_trs_get(f"/tools/{tool_id}")
    if data and data.get("versions"):
        return [v["name"] for v in data["versions"] if "GALAXY" in v.get("descriptor_type", [])]
    # CLI fallback
    cmd = ["dockstore", "workflow", "info", "--entry", entry]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []
    versions = []
    m = re.search(r"WORKFLOW VERSIONS\s*\n\s*([^\n]+)", result.stdout, re.IGNORECASE)
    if m:
        raw = m.group(1)
        versions = [v.strip() for v in re.split(r",|\s+", raw) if v.strip()]
    return versions


def download_dockstore_ga(entry: str, version: str,
                           workspace: Path) -> Optional[Path]:
    """Download a Galaxy workflow .ga file from Dockstore via TRS API.
    Falls back to the CLI if the API call fails."""
    safe = entry.replace("/", "_").replace(":", "_").replace(".", "_")
    dest_dir = workspace / f"dockstore_{safe}" / version
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Try TRS API first (version name goes directly in path, not the full #workflow/... id)
    tool_id = _dockstore_tool_id(entry)
    ver_id  = urllib.parse.quote(version, safe="")
    descriptor = _dockstore_trs_get(f"/tools/{tool_id}/versions/{ver_id}/GALAXY/descriptor")
    if descriptor and "content" in descriptor:
        content = descriptor["content"]
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = {}
        raw_name = (parsed.get("name") or f"workflow_{version}").strip()
        ga_filename = raw_name.replace("/", "_") + ".ga"
        ga_path = dest_dir / ga_filename
        with open(ga_path, "w") as f:
            f.write(content)
        return ga_path

    # CLI fallback
    cmd = ["dockstore", "workflow", "download",
           "--entry", f"{entry}:{version}",
           "--descriptor", "all",
           "--output-dir", str(dest_dir)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(dest_dir))
    except FileNotFoundError:
        print("  Error: dockstore CLI not found")
        return None
    if result.returncode != 0:
        print(f"  Download failed: {result.stderr[:200]}")
        return None
    ga_files = list(dest_dir.glob("*.ga"))
    if not ga_files:
        print(f"  No .ga file found in {dest_dir}")
        return None
    return ga_files[0]


# ---------------------------------------------------------------------------
# Version selection
# ---------------------------------------------------------------------------

def select_versions_workflowhub(versions: List[Dict], spec: str) -> List[Dict]:
    """
    Select WorkflowHub versions based on spec:
      latest   → most recent 1
      all      → all versions
      N        → N most recent (integer)
      v1.3     → match by version name
      v1.3,v1.4 → multiple specific names
    """
    if spec == "latest":
        return versions[-1:] if versions else []
    if spec == "all":
        return versions
    try:
        n = int(spec)
        return versions[-n:] if len(versions) >= n else versions
    except ValueError:
        names = {v.strip().lower() for v in spec.split(",")}
        matched = [v for v in versions
                   if v.get("name", "").lower() in names
                   or str(v.get("id", "")).lower() in names]
        if not matched:
            print(f"  Warning: no versions matched '{spec}', using latest")
            return versions[-1:] if versions else []
        return matched


def select_versions_dockstore(versions: List[str], spec: str) -> List[str]:
    """
    Select Dockstore versions based on spec.
    Dockstore lists newest first, so 'latest' = versions[0].
    """
    if spec == "latest":
        return versions[:1] if versions else []
    if spec == "all":
        return versions
    try:
        n = int(spec)
        return versions[:n]
    except ValueError:
        names = {v.strip() for v in spec.split(",")}
        matched = [v for v in versions if v in names]
        if not matched:
            print(f"  Warning: no versions matched '{spec}', using latest")
            return versions[:1] if versions else []
        return matched


# ---------------------------------------------------------------------------
# Core checking logic
# ---------------------------------------------------------------------------

def check_workflow_version(source: str, workflow_info: Dict, version_label: str,
                            ga_path: Path, tool_cache: Dict[str, set]) -> Dict:
    """
    Run all static checks on a single downloaded .ga file and return a result dict.

    Order of checks:
      1. Structural consistency  -- aborts remaining checks on FAIL
      2. Wiring gaps             -- runs if structural check passes
      3. Tool availability       -- includes subworkflow tools automatically
    """
    # --- 1. Structural consistency ---
    structural_issues, workflow_dict = check_structural_consistency(ga_path)
    structural_fails = [i for i in structural_issues if i["severity"] == "FAIL"]

    if structural_fails or workflow_dict is None:
        return {
            "source": source,
            "workflow_name": workflow_info.get("name", ""),
            "workflow_id": workflow_info.get("id", workflow_info.get("entry", "")),
            "workflow_url": workflow_info.get("url", ""),
            "version": version_label,
            "timestamp": datetime.now().isoformat(),
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
    wiring_issues = check_wiring_gaps(workflow_dict)

    # --- 3. Tool availability (parent + subworkflows) ---
    tool_entries = _extract_tools_from_dict(workflow_dict)
    classified   = check_tools(tool_entries, tool_cache)

    exact    = [t for t in classified if t["status"] == "exact_match"]
    mismatch = [t for t in classified if t["status"] == "version_mismatch"]
    missing  = [t for t in classified if t["status"] == "missing"]

    # Overall status: tool issues take precedence over wiring warnings
    if not classified:
        workflow_status = "no_toolshed_tools"
    elif missing:
        workflow_status = "missing_tool"
    elif mismatch:
        workflow_status = "version_mismatch"
    elif wiring_issues:
        workflow_status = "wiring_issues"
    else:
        workflow_status = "ready"

    return {
        "source": source,
        "workflow_name": workflow_info.get("name", ""),
        "workflow_id": workflow_info.get("id", workflow_info.get("entry", "")),
        "workflow_url": workflow_info.get("url", ""),
        "version": version_label,
        "timestamp": datetime.now().isoformat(),
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


def process_workflowhub_workflow(workflow: Dict, version_spec: str,
                                  workspace: Path, tool_cache: Dict[str, set]) -> List[Dict]:
    wf_id = workflow["id"]
    wf_name = workflow.get("name", f"workflow_{wf_id}")
    wf_url = workflow.get("url", f"{WORKFLOWHUB_BASE}/workflows/{wf_id}")
    print(f"\n  WorkflowHub: {wf_name} (ID: {wf_id})")

    all_versions = get_workflowhub_galaxy_versions(workflow)
    chosen = select_versions_workflowhub(all_versions, version_spec)
    if not chosen:
        print(f"  No versions found")
        return []
    print(f"  Versions to check: {[v.get('name', v['id']) for v in chosen]}")

    results = []
    for ver in chosen:
        ver_id = ver["id"]
        ver_label = ver.get("name", str(ver_id))
        print(f"  Checking version: {ver_label}...", end=" ", flush=True)
        ga_path = download_workflowhub_ga(wf_id, ver_id, workspace, wf_name)
        if not ga_path:
            print("download failed")
            continue
        info = {"name": wf_name, "id": wf_id, "url": wf_url}
        result = check_workflow_version("workflowhub", info, ver_label, ga_path, tool_cache)
        print(f"{result['total_tools']} tools | "
              f"exact={result['n_exact']} "
              f"mismatch={result['n_version_mismatch']} "
              f"missing={result['n_missing']} "
              f"[{result['workflow_status']}]")
        results.append(result)
    return results


def process_dockstore_workflow(entry: str, version_spec: str,
                                workspace: Path, tool_cache: Dict[str, set]) -> List[Dict]:
    wf_name = entry.split("/")[-1]
    wf_url = f"{DOCKSTORE_BASE}/workflows/{entry}"
    print(f"\n  Dockstore: {entry}")

    all_versions = get_dockstore_versions(entry)
    if not all_versions:
        print(f"  Could not retrieve versions")
        return []
    chosen = select_versions_dockstore(all_versions, version_spec)
    print(f"  Versions to check: {chosen}")

    results = []
    for version in chosen:
        print(f"  Checking version: {version}...", end=" ", flush=True)
        ga_path = download_dockstore_ga(entry, version, workspace)
        if not ga_path:
            print("download failed")
            continue
        info = {"name": wf_name, "id": entry, "url": wf_url}
        result = check_workflow_version("dockstore", info, version, ga_path, tool_cache)
        print(f"{result['total_tools']} tools | "
              f"exact={result['n_exact']} "
              f"mismatch={result['n_version_mismatch']} "
              f"missing={result['n_missing']} "
              f"[{result['workflow_status']}]")
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def generate_report(results: List[Dict], galaxy_url: str, profile: str) -> Dict:
    missing_tools = sorted({
        t["id"] for r in results for t in r["tool_statuses"]
        if t["status"] == "missing"
    })
    mismatch_tools = sorted({
        t["id"] for r in results for t in r["tool_statuses"]
        if t["status"] == "version_mismatch"
    })
    return {
        "generated": datetime.now().isoformat(),
        "galaxy_url": galaxy_url,
        "profile": profile,
        "strict_version_matching": True,
        "total_versions_checked": len(results),
        "unique_workflows": len({r["workflow_id"] for r in results}),
        "versions_ready": sum(1 for r in results if r["workflow_status"] == "ready"),
        "versions_version_mismatch": sum(
            1 for r in results if r["workflow_status"] == "version_mismatch"
        ),
        "versions_missing_tool": sum(
            1 for r in results if r["workflow_status"] == "missing_tool"
        ),
        "versions_structural_error": sum(
            1 for r in results if r["workflow_status"] == "structural_error"
        ),
        "versions_wiring_issues": sum(
            1 for r in results if r.get("wiring_issues")
        ),
        "unique_missing_tools": missing_tools,
        "unique_missing_tools_count": len(missing_tools),
        "unique_mismatched_tools": mismatch_tools,
        "unique_mismatched_tools_count": len(mismatch_tools),
        "results": results,
    }


def write_text_report(report: Dict, path: str):
    """Write a plain-text aligned table report."""
    lines = []
    lines.append("Galaxy Workflow Tool Checker (strict version matching)")
    lines.append(f"Generated : {report['generated']}")
    lines.append(f"Galaxy    : {report['galaxy_url']}")
    lines.append(f"Profile   : {report['profile']}")
    lines.append("")
    lines.append("Summary")
    lines.append("-" * 40)
    lines.append(f"Versions checked              : {report['total_versions_checked']}")
    lines.append(f"Unique workflows              : {report['unique_workflows']}")
    lines.append(f"Ready to run (all exact)      : {report['versions_ready']}")
    lines.append(f"Structural errors             : {report['versions_structural_error']}")
    lines.append(f"Wiring issues (warnings)      : {report['versions_wiring_issues']}")
    lines.append(f"Blocked by version mismatch   : {report['versions_version_mismatch']}")
    lines.append(f"Blocked by missing tool       : {report['versions_missing_tool']}")
    lines.append(f"Unique mismatched tools       : {report['unique_mismatched_tools_count']}")
    lines.append(f"Unique missing tools          : {report['unique_missing_tools_count']}")
    lines.append("")

    results = report["results"]
    if not results:
        lines.append("No results.")
    else:
        col_name = max((len(r["workflow_name"]) for r in results), default=20)
        col_name = max(col_name, len("Workflow"))
        col_src  = max((len(r["source"]) for r in results), default=10)
        col_src  = max(col_src, len("Source"))
        col_ver  = max((len(str(r["version"])) for r in results), default=9)
        col_ver  = max(col_ver, len("Version"))
        col_status = max((len(r["workflow_status"]) for r in results), default=10)
        col_status = max(col_status, len("Status"))

        lines.append("Results")
        header = (f"{'Workflow':<{col_name}}  {'Source':<{col_src}}  "
                  f"{'Version':<{col_ver}}  "
                  f"{'Status':<{col_status}}  "
                  f"{'Tools':>5}  {'Exact':>5}  {'Mism':>5}  {'Miss':>5}  "
                  f"{'Wire':>4}  URL")
        lines.append("-" * (len(header) + 5))
        lines.append(header)
        lines.append("-" * (len(header) + 5))
        for r in results:
            lines.append(
                f"{r['workflow_name']:<{col_name}}  "
                f"{r['source']:<{col_src}}  "
                f"{str(r['version']):<{col_ver}}  "
                f"{r['workflow_status']:<{col_status}}  "
                f"{r['total_tools']:>5}  "
                f"{r['n_exact']:>5}  "
                f"{r['n_version_mismatch']:>5}  "
                f"{r['n_missing']:>5}  "
                f"{r['n_wiring_issues']:>4}  "
                f"{r['workflow_url']}"
            )
        lines.append("")

        # Per-workflow detail for non-ready versions
        non_ready = [r for r in results if r["workflow_status"] != "ready"]
        if non_ready:
            lines.append("Blocker / issue detail")
            lines.append("-" * 40)
            for r in non_ready:
                lines.append(f"{r['workflow_name']} ({r['source']}, {r['version']}) "
                             f"[{r['workflow_status']}]")

                # Structural issues
                for issue in r.get("structural_issues", []):
                    lines.append(f"  STRUCTURAL  [{issue['severity']}] {issue['message']}")

                # No ToolShed tools found
                if r["workflow_status"] == "no_toolshed_tools":
                    lines.append("  INFO  No ToolShed tools found — workflow may use only "
                                 "built-in Galaxy tools, or tool_id fields may be missing.")

                # Tool issues
                for t in r["tool_statuses"]:
                    src_tag = f" [{t['source']}]" if t.get("source", "parent") != "parent" else ""
                    if t["status"] == "version_mismatch":
                        avail = ", ".join(t.get("available_versions", []))
                        direction = t.get("version_direction", "")
                        dir_tag = f"  ({direction})" if direction else ""
                        lines.append(f"  MISMATCH{src_tag}{dir_tag}  {t['base']}")
                        lines.append(f"            wants : {t['version']}")
                        lines.append(f"            avail : {avail}")
                    elif t["status"] == "missing":
                        lines.append(f"  MISSING{src_tag}   {t['id']}")

                # Wiring issues
                for w in r.get("wiring_issues", []):
                    src_tag = f" [{w['source']}]" if w.get("source", "parent") != "parent" else ""
                    lines.append(f"  WIRING{src_tag}    [{w['severity']}] {w['message']}")

                lines.append("")

        if report["unique_mismatched_tools"]:
            lines.append("All unique mismatched tool IDs (version not installed)")
            lines.append("-" * 40)
            for i, t in enumerate(report["unique_mismatched_tools"], 1):
                lines.append(f"  {i:>3}. {t}")
            lines.append("")

        if report["unique_missing_tools"]:
            lines.append("All unique missing tool IDs (base not installed)")
            lines.append("-" * 40)
            for i, t in enumerate(report["unique_missing_tools"], 1):
                lines.append(f"  {i:>3}. {t}")
            lines.append("")

        lines.append(
            "Note: wiring issues are reported as WARN — without querying the\n"
            "Galaxy tool XML the checker cannot confirm whether unconnected\n"
            "inputs are required or optional."
        )
        lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Text report  : {path}")


def display_summary(report: Dict):
    """Print a brief summary to stdout."""
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY (strict version matching)")
    print(f"  Versions checked              : {report['total_versions_checked']}")
    print(f"  Unique workflows              : {report['unique_workflows']}")
    print(f"  Ready to run (all exact)      : {report['versions_ready']}")
    print(f"  Structural errors             : {report['versions_structural_error']}")
    print(f"  Wiring issues (warnings)      : {report['versions_wiring_issues']}")
    print(f"  Blocked by version mismatch   : {report['versions_version_mismatch']}")
    print(f"  Blocked by missing tool       : {report['versions_missing_tool']}")
    print(f"  Unique mismatched tools       : {report['unique_mismatched_tools_count']}")
    print(f"  Unique missing tools          : {report['unique_missing_tools_count']}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Check whether Galaxy workflow tools are installed in a Galaxy instance"
    )
    # Source
    parser.add_argument("--source", choices=["dockstore", "workflowhub", "both"],
                        default="both",
                        help="Workflow registry to query (default: both)")
    # Workflow selection
    parser.add_argument("--search", "-s",
                        help="Search workflows by keyword/name")
    parser.add_argument("--id",
                        help="WorkflowHub workflow ID (use with --source workflowhub)")
    parser.add_argument("--entry", "-e",
                        help="Dockstore workflow entry, e.g. "
                             "github.com/iwc-workflows/Assembly-decontamination-VGP9/main")
    parser.add_argument("--max-workflows", "-mw", type=int, default=10,
                        help="Max workflows to return from a search (default: 10)")
    # Version selection
    parser.add_argument("--versions", "-v", default="latest",
                        help="Which versions to check: latest (default) | all | "
                             "N (e.g. 3 most recent) | specific e.g. v1.3 | "
                             "comma-separated e.g. v1.3,v1.4")
    # Galaxy credentials
    parser.add_argument("--profile", default="galaxy_profile",
                        help="Planemo profile name to read Galaxy credentials from "
                             "(default: galaxy_profile)")
    # Output
    parser.add_argument("--output", "-o", default="workflow_check_report",
                        help="Base name for output files, no extension "
                             "(default: workflow_check_report) "
                             "produces <name>.txt and <name>.json")
    parser.add_argument("--workspace", "-w", default="./workflow_workspace",
                        help="Directory for downloaded .ga files (default: ./workflow_workspace)")
    # Flags
    parser.add_argument("--list-only", action="store_true",
                        help="List matching workflows without checking tools")
    parser.add_argument("--local-file", metavar="PATH",
                        help="Check a local .ga file directly instead of fetching from a registry. "
                             "All static checks and (if credentials are available) tool availability "
                             "checks are run. Use --version-label to set the version shown in the report.")
    parser.add_argument("--version-label", default="local",
                        help="Version label to use in the report when checking a local file "
                             "(default: local). Only used with --local-file.")
    parser.add_argument("--static-only", action="store_true",
                        help="Run only the static checks (structural consistency and wiring gaps). "
                             "Skip the Galaxy tool availability check. No Galaxy credentials needed. "
                             "Only used with --local-file.")

    args = parser.parse_args()

    # Validate combinations
    if args.local_file:
        if not Path(args.local_file).exists():
            parser.error(f"--local-file: file not found: {args.local_file}")
        return args  # skip registry-mode validation

    if args.source == "workflowhub" and args.entry:
        parser.error("--entry is for Dockstore workflows; use --id for WorkflowHub")
    if args.source == "dockstore" and args.id:
        parser.error("--id is for WorkflowHub workflows; use --entry for Dockstore")
    if not any([args.search, args.id, args.entry]):
        parser.error("Provide at least one of: --search, --id, --entry (or use --local-file)")

    return args


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    workspace = Path(args.workspace)
    workspace.mkdir(exist_ok=True)

    # --- List-only mode ---
    if args.list_only:
        if args.source in ("workflowhub", "both") and args.search:
            print(f"\nWorkflowHub results for '{args.search}':")
            for wf in search_workflowhub(name=args.search, max_results=args.max_workflows):
                versions = get_workflowhub_galaxy_versions(wf)
                print(f"  ID {wf['id']:>6}: {wf.get('name','')}  "
                      f"({len(versions)} version(s))  {wf.get('url','')}")
        if args.source in ("workflowhub", "both") and args.id:
            wf = get_workflowhub_workflow(args.id)
            if wf:
                versions = get_workflowhub_galaxy_versions(wf)
                print(f"\nWorkflowHub ID {args.id}: {wf.get('name','')}")
                for v in versions:
                    print(f"  version id={v['id']}  name={v.get('name','')}")
        if args.source in ("dockstore", "both") and args.search:
            print(f"\nDockstore results for '{args.search}':")
            for wf in search_dockstore(args.search, max_results=args.max_workflows):
                print(f"  {wf['entry']}  {wf['url']}")
        if args.source in ("dockstore", "both") and args.entry:
            versions = get_dockstore_versions(args.entry)
            print(f"\nDockstore {args.entry}: {len(versions)} version(s)")
            for v in versions:
                print(f"  {v}")
        return

    # --- Local file mode ---
    if args.local_file:
        ga_path = Path(args.local_file)
        # Derive a display name from the filename
        wf_name = ga_path.stem

        if args.static_only:
            # Static checks only — no Galaxy connection needed
            print(f"\nStatic-only check: {ga_path}")
            structural_issues, wf_dict = check_structural_consistency(ga_path)
            structural_fails = [i for i in structural_issues if i["severity"] == "FAIL"]
            print("\nStructural consistency:")
            if not structural_issues:
                print("  PASS")
            for issue in structural_issues:
                print(f"  [{issue['severity']}] {issue['check']}: {issue['message']}")
            if wf_dict and not structural_fails:
                wiring = check_wiring_gaps(wf_dict)
                print("\nWiring gaps:")
                if not wiring:
                    print("  PASS")
                for w in wiring:
                    print(f"  [{w['severity']}] {w['message']}")
                tools = _extract_tools_from_dict(wf_dict)
                print(f"\nToolShed tools found: {len(tools)}")
                for t in tools:
                    src = f" [{t['source']}]" if t['source'] != 'parent' else ''
                    print(f"  {t['id']}{src}")
            else:
                print("\n(Wiring and tool checks skipped — structural FAIL)")
            return

        # Full check (static + tool availability)
        galaxy_url, galaxy_key = read_planemo_profile(args.profile)
        print(f"Galaxy URL : {galaxy_url}")
        print(f"Profile    : {args.profile}")
        tool_cache = build_galaxy_tool_cache(galaxy_url, galaxy_key)

        workflow_info = {"name": wf_name, "id": wf_name, "url": str(ga_path.resolve())}
        result = check_workflow_version(
            source="local",
            workflow_info=workflow_info,
            version_label=args.version_label,
            ga_path=ga_path,
            tool_cache=tool_cache,
        )
        all_results = [result]
        report = generate_report(all_results, galaxy_url, args.profile)
        display_summary(report)
        json_path = args.output + ".json"
        txt_path  = args.output + ".txt"
        with open(json_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"JSON report  : {json_path}")
        write_text_report(report, txt_path)
        return

    # --- Tool checking mode ---
    galaxy_url, galaxy_key = read_planemo_profile(args.profile)
    print(f"Galaxy URL : {galaxy_url}")
    print(f"Profile    : {args.profile}")

    tool_cache = build_galaxy_tool_cache(galaxy_url, galaxy_key)

    all_results = []

    # WorkflowHub
    if args.source in ("workflowhub", "both"):
        if args.id:
            wf = get_workflowhub_workflow(args.id)
            if wf:
                all_results.extend(
                    process_workflowhub_workflow(wf, args.versions, workspace, tool_cache)
                )
            else:
                print(f"WorkflowHub workflow ID {args.id} not found")
        elif args.search:
            workflows = search_workflowhub(name=args.search, max_results=args.max_workflows)
            print(f"\nFound {len(workflows)} WorkflowHub workflows for '{args.search}'")
            for wf in workflows:
                all_results.extend(
                    process_workflowhub_workflow(wf, args.versions, workspace, tool_cache)
                )

    # Dockstore
    if args.source in ("dockstore", "both"):
        if args.entry:
            all_results.extend(
                process_dockstore_workflow(args.entry, args.versions, workspace, tool_cache)
            )
        elif args.search:
            workflows = search_dockstore(args.search, max_results=args.max_workflows)
            print(f"\nFound {len(workflows)} Dockstore workflows for '{args.search}'")
            for wf in workflows:
                all_results.extend(
                    process_dockstore_workflow(wf["entry"], args.versions, workspace, tool_cache)
                )

    if not all_results:
        print("\nNo results to report.")
        return

    report = generate_report(all_results, galaxy_url, args.profile)
    display_summary(report)

    json_path = args.output + ".json"
    txt_path  = args.output + ".txt"

    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"JSON report  : {json_path}")
    write_text_report(report, txt_path)


if __name__ == "__main__":
    main()
