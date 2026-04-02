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
from typing import List, Dict, Optional, Tuple, Union, Any
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

def build_galaxy_tool_cache(galaxy_url: str, galaxy_key: str) -> set:
    """
    Fetch all tools installed in Galaxy and return a set of base tool IDs
    (without version suffix) for fast lookup.
    Base ID format: toolshed.g2.bx.psu.edu/repos/{owner}/{repo}/{toolname}
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
    cache = set()
    for t in tools:
        tid = t.get("id", "")
        if "toolshed" in tid:
            # Strip version: keep first 5 path components
            # e.g. toolshed.g2.bx.psu.edu/repos/owner/repo/toolname
            parts = tid.split("/")
            if len(parts) >= 5:
                cache.add("/".join(parts[:5]))
    print(f"  Found {len(tools)} tools installed ({len(cache)} ToolShed tools)")
    return cache


# ---------------------------------------------------------------------------
# Tool extraction from .ga file
# ---------------------------------------------------------------------------

def extract_tools_from_ga(ga_path: Path) -> List[str]:
    """
    Parse a Galaxy workflow (.ga) file and return a deduplicated sorted list
    of ToolShed tool IDs required by the workflow steps.
    Built-in Galaxy tools (no toolshed URL) are skipped.
    """
    with open(ga_path) as f:
        workflow = json.load(f)
    tools = set()
    steps = workflow.get("steps", {})
    for step in steps.values():
        tool_id = step.get("tool_id")
        if tool_id and "toolshed.g2.bx.psu.edu" in tool_id:
            tools.add(tool_id)
    return sorted(tools)


def check_tools(tool_ids: List[str], cache: set) -> Tuple[List[str], List[str]]:
    """
    Given a list of tool IDs from a workflow and a set of installed base IDs,
    return (present, missing) lists.
    Matching is done on the base ID (without version) so that a newer installed
    version still counts as present.
    """
    present, missing = [], []
    for tid in tool_ids:
        parts = tid.split("/")
        base = "/".join(parts[:5]) if len(parts) >= 5 else tid
        if base in cache:
            present.append(tid)
        else:
            missing.append(tid)
    return present, missing


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


def get_dockstore_versions(entry: str) -> List[str]:
    """Return list of version tags for a Dockstore workflow, newest first."""
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
    """Download a Galaxy workflow .ga file from Dockstore."""
    safe = entry.replace("/", "_").replace(":", "_").replace(".", "_")
    dest_dir = workspace / f"dockstore_{safe}" / version
    dest_dir.mkdir(parents=True, exist_ok=True)

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
                            ga_path: Path, tool_cache: set) -> Dict:
    """Run tool check on a single downloaded .ga file and return a result dict."""
    tool_ids = extract_tools_from_ga(ga_path)
    present, missing = check_tools(tool_ids, tool_cache)
    return {
        "source": source,
        "workflow_name": workflow_info.get("name", ""),
        "workflow_id": workflow_info.get("id", workflow_info.get("entry", "")),
        "workflow_url": workflow_info.get("url", ""),
        "version": version_label,
        "timestamp": datetime.now().isoformat(),
        "total_tools": len(tool_ids),
        "present_tools": present,
        "missing_tools": missing,
        "ga_path": str(ga_path),
    }


def process_workflowhub_workflow(workflow: Dict, version_spec: str,
                                  workspace: Path, tool_cache: set) -> List[Dict]:
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
        n_missing = len(result["missing_tools"])
        print(f"{result['total_tools']} tools, {n_missing} missing")
        results.append(result)
    return results


def process_dockstore_workflow(entry: str, version_spec: str,
                                workspace: Path, tool_cache: set) -> List[Dict]:
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
        n_missing = len(result["missing_tools"])
        print(f"{result['total_tools']} tools, {n_missing} missing")
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def generate_report(results: List[Dict], galaxy_url: str, profile: str) -> Dict:
    all_missing = sorted({t for r in results for t in r["missing_tools"]})
    return {
        "generated": datetime.now().isoformat(),
        "galaxy_url": galaxy_url,
        "profile": profile,
        "total_versions_checked": len(results),
        "unique_workflows": len({r["workflow_id"] for r in results}),
        "versions_all_tools_present": sum(1 for r in results if not r["missing_tools"]),
        "versions_with_missing_tools": sum(1 for r in results if r["missing_tools"]),
        "unique_missing_tools": all_missing,
        "unique_missing_tools_count": len(all_missing),
        "results": results,
    }


def write_text_report(report: Dict, path: str):
    """Write a plain-text aligned table report."""
    lines = []
    lines.append("Galaxy Workflow Tool Checker")
    lines.append(f"Generated : {report['generated']}")
    lines.append(f"Galaxy    : {report['galaxy_url']}")
    lines.append(f"Profile   : {report['profile']}")
    lines.append("")
    lines.append("Summary")
    lines.append("-" * 40)
    lines.append(f"Versions checked            : {report['total_versions_checked']}")
    lines.append(f"Unique workflows            : {report['unique_workflows']}")
    lines.append(f"All tools present           : {report['versions_all_tools_present']}")
    lines.append(f"Versions with missing tools : {report['versions_with_missing_tools']}")
    lines.append(f"Unique missing tools        : {report['unique_missing_tools_count']}")
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
        col_t    = len("Tools")
        col_m    = len("Missing")

        lines.append("Results")
        header = (f"{'Workflow':<{col_name}}  {'Source':<{col_src}}  "
                  f"{'Version':<{col_ver}}  {'Tools':>{col_t}}  {'Missing':>{col_m}}  URL")
        lines.append("-" * (len(header) + 10))
        lines.append(header)
        lines.append("-" * (len(header) + 10))
        for r in results:
            m = len(r["missing_tools"])
            lines.append(
                f"{r['workflow_name']:<{col_name}}  "
                f"{r['source']:<{col_src}}  "
                f"{str(r['version']):<{col_ver}}  "
                f"{r['total_tools']:>{col_t}}  "
                f"{m:>{col_m}}  "
                f"{r['workflow_url']}"
            )
        lines.append("")

        any_missing = any(r["missing_tools"] for r in results)
        if any_missing:
            lines.append("Missing tools detail")
            lines.append("-" * 40)
            for r in results:
                if not r["missing_tools"]:
                    continue
                lines.append(f"{r['workflow_name']} ({r['source']}, {r['version']})")
                for t in r["missing_tools"]:
                    lines.append(f"  {t}")
                lines.append("")

        if report["unique_missing_tools"]:
            lines.append("All unique missing tools")
            lines.append("-" * 40)
            for i, t in enumerate(report["unique_missing_tools"], 1):
                lines.append(f"  {i:>3}. {t}")
            lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Text report  : {path}")


def display_summary(report: Dict):
    """Print a brief summary to stdout."""
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print(f"  Versions checked            : {report['total_versions_checked']}")
    print(f"  Unique workflows            : {report['unique_workflows']}")
    print(f"  All tools present           : {report['versions_all_tools_present']}")
    print(f"  Versions with missing tools : {report['versions_with_missing_tools']}")
    print(f"  Unique missing tools        : {report['unique_missing_tools_count']}")
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

    args = parser.parse_args()

    # Validate combinations
    if args.source == "workflowhub" and args.entry:
        parser.error("--entry is for Dockstore workflows; use --id for WorkflowHub")
    if args.source == "dockstore" and args.id:
        parser.error("--id is for WorkflowHub workflows; use --entry for Dockstore")
    if not any([args.search, args.id, args.entry]):
        parser.error("Provide at least one of: --search, --id, --entry")

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
