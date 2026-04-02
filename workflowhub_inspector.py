#!/usr/bin/env python3
"""
WorkflowHub Workflow Inspector
Queries WorkflowHub's TRS API to find Galaxy workflows, downloads them,
tests with Planemo, and reports missing tools via BioBlend/ToolShed.

Usage examples:
  python workflowhub_inspector.py --search "assembly"
  python workflowhub_inspector.py --id 2 --version 1
  python workflowhub_inspector.py --search "RNA" --max-workflows 5 --versions-per-workflow all
"""

import json
import sys
import os
import re
import time
import argparse
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any, Union
from datetime import datetime

try:
    import urllib.request
    import urllib.parse
    import urllib.error
except ImportError:
    pass

try:
    from bioblend import toolshed
    BIOBLEND_AVAILABLE = True
except ImportError:
    BIOBLEND_AVAILABLE = False
    print("Warning: BioBlend not installed. Tool information will be limited.")
    print("  Install with: pip install bioblend")

WORKFLOWHUB_TRS_BASE = "https://workflowhub.eu/ga4gh/trs/v2"


def trs_get(path: str, params: dict = None) -> Any:
    """Make a GET request to the WorkflowHub TRS API."""
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
        print(f"  Request failed for {url}: {e}")
        return None


class ToolShedInfo:
    """Fetch tool details from ToolShed using BioBlend."""

    def __init__(self, toolshed_url: str = "https://toolshed.g2.bx.psu.edu"):
        self.ts = None
        if BIOBLEND_AVAILABLE:
            try:
                self.ts = toolshed.ToolShedInstance(url=toolshed_url)
            except Exception as e:
                print(f"  Warning: Could not connect to ToolShed: {e}")

    def parse_tool_url(self, tool_url: str) -> Dict[str, str]:
        parts = tool_url.split("/")
        if len(parts) >= 6 and parts[1] == "repos":
            return {"owner": parts[2], "repository": parts[3],
                    "tool_name": parts[4], "version": parts[5]}
        elif len(parts) >= 4 and parts[1] == "repos":
            return {"owner": parts[2], "repository": parts[3],
                    "tool_name": parts[3], "version": None}
        return {"owner": None, "repository": None, "tool_name": None, "version": None}

    def get_tool_details(self, tool_url: str) -> Dict[str, Any]:
        if not self.ts:
            return {"error": "BioBlend not available or ToolShed connection failed"}
        parsed = self.parse_tool_url(tool_url)
        if not parsed["owner"] or not parsed["repository"]:
            return {"error": f"Could not parse tool URL: {tool_url}", "parsed": parsed}
        result = {
            "tool_url": tool_url,
            "owner": parsed["owner"],
            "repository": parsed["repository"],
            "tool_name": parsed["tool_name"],
            "version": parsed["version"],
            "revisions": [],
            "latest_revision": None,
            "repository_details": None,
            "error": None,
        }
        try:
            revisions = self.ts.repositories.get_ordered_installable_revisions(
                parsed["repository"], parsed["owner"]
            )
            result["revisions"] = revisions
            if revisions:
                result["latest_revision"] = revisions[-1]
            repositories = self.ts.repositories.get_repositories(
                name=parsed["repository"], owner=parsed["owner"]
            )
            if repositories:
                repo = repositories[0]
                result["repository_details"] = repo
                result["description"] = repo.get("description", "")
                result["long_description"] = repo.get("long_description", "")
                result["stars"] = repo.get("stars", 0)
                result["times_downloaded"] = repo.get("times_downloaded", 0)
        except Exception as e:
            result["error"] = str(e)
        return result

    def get_tool_installation_command(self, tool_url: str) -> str:
        parsed = self.parse_tool_url(tool_url)
        if not parsed["owner"] or not parsed["repository"]:
            return f"# Could not parse tool URL: {tool_url}"
        details = self.get_tool_details(tool_url)
        revision = details.get("latest_revision", "latest")
        if revision and revision != "latest":
            return (f"shed-tools install -g <galaxy_url> -a <api_key> "
                    f"--name {parsed['repository']} --owner {parsed['owner']} --revision {revision}")
        return (f"shed-tools install -g <galaxy_url> -a <api_key> "
                f"--name {parsed['repository']} --owner {parsed['owner']}")


class WorkflowHubInspector:

    def __init__(self, workspace_dir: str = "./workflowhub_workspace",
                 galaxy_profile: str = "galaxy_profile",
                 toolshed_url: str = "https://toolshed.g2.bx.psu.edu"):
        self.workspace = Path(workspace_dir)
        self.workspace.mkdir(exist_ok=True)
        self.galaxy_profile = galaxy_profile
        self.toolshed_info = ToolShedInfo(toolshed_url) if BIOBLEND_AVAILABLE else None

    def search_workflows(self, name: str = None, organization: str = None,
                         max_results: int = 50) -> List[Dict]:
        """Search WorkflowHub TRS API for Galaxy workflows."""
        print(f"\nSearching WorkflowHub for Galaxy workflows...")
        params = {"descriptorType": "GALAXY", "limit": 100, "offset": 0}
        if name:
            params["name"] = name
            print(f"  Name filter: {name}")
        if organization:
            params["organization"] = organization
            print(f"  Organization filter: {organization}")

        workflows = []
        while len(workflows) < max_results:
            page = trs_get("/tools", params)
            if not page:
                break
            if not page:
                break
            # Filter to only GALAXY descriptor types (API may return mixed)
            galaxy_wfs = [
                w for w in page
                if any(
                    "GALAXY" in v.get("descriptor_type", [])
                    for v in w.get("versions", [])
                )
            ]
            workflows.extend(galaxy_wfs)
            if len(page) < params["limit"]:
                break  # Last page
            params["offset"] += params["limit"]

        workflows = workflows[:max_results]
        print(f"  Found {len(workflows)} Galaxy workflows")
        return workflows

    def get_workflow_by_id(self, workflow_id: str) -> Optional[Dict]:
        """Fetch a single workflow by its WorkflowHub ID."""
        result = trs_get(f"/tools/{workflow_id}")
        return result

    def get_galaxy_versions(self, workflow: Dict) -> List[Dict]:
        """Return only versions that have GALAXY descriptor type."""
        return [
            v for v in workflow.get("versions", [])
            if "GALAXY" in v.get("descriptor_type", [])
        ]

    def download_workflow(self, workflow_id: str, version_id: str,
                          workflow_name: str = None) -> Optional[Path]:
        """Download a Galaxy workflow .ga file and associated test files from WorkflowHub TRS."""
        safe_name = (workflow_name or workflow_id).replace("/", "_").replace(" ", "_")[:60]
        workflow_dir = self.workspace / f"{safe_name}__{workflow_id}" / f"v{version_id}"
        workflow_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n  Downloading workflow {workflow_id} version {version_id}...")

        descriptor = trs_get(f"/tools/{workflow_id}/versions/{version_id}/GALAXY/descriptor")
        if not descriptor or "content" not in descriptor:
            print(f"  Failed to get descriptor for {workflow_id}:{version_id}")
            return None

        content = descriptor["content"]
        # Validate it's actually a Galaxy workflow
        try:
            parsed = json.loads(content)
            if not (parsed.get("a_galaxy_workflow") or parsed.get("class") == "GalaxyWorkflow"):
                print(f"  Warning: content doesn't look like a Galaxy workflow")
        except json.JSONDecodeError:
            print(f"  Warning: descriptor content is not valid JSON")
            return None

        # Use the original filename from the TRS files list if available, else derive from name
        files = trs_get(f"/tools/{workflow_id}/versions/{version_id}/GALAXY/files") or []
        ga_filename = next(
            (f["path"] for f in files if f.get("file_type") == "PRIMARY_DESCRIPTOR"),
            None
        )
        if not ga_filename:
            wf_name = (parsed.get("name") or f"workflow_{workflow_id}").strip().replace("/", "_")
            ga_filename = f"{wf_name}.ga"

        ga_path = workflow_dir / ga_filename
        with open(ga_path, "w") as f:
            f.write(content)
        print(f"  Saved: {ga_path.name}")

        # Download test yml and test-data files so Planemo can run tests
        other_files = [f["path"] for f in files if f.get("file_type") == "OTHER"]
        for file_path in other_files:
            # Skip HTML/metadata files that aren't needed for testing
            if any(file_path.endswith(ext) for ext in [".html", ".json"]):
                continue
            file_data = trs_get(
                f"/tools/{workflow_id}/versions/{version_id}/GALAXY/descriptor",
                {"path": file_path}
            )
            if not file_data or "content" not in file_data:
                continue
            dest = workflow_dir / file_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "w") as f:
                f.write(file_data["content"])
            print(f"  Saved: {file_path}")

        return ga_path

    def run_planemo_test(self, workflow_path: Path) -> Optional[subprocess.Popen]:
        """Start planemo test in the background, outputting JSON only."""
        workflow_dir = workflow_path.parent
        json_path = workflow_dir / "tool_test_output.json"
        if json_path.exists():
            json_path.unlink()

        cmd = [
            "planemo", "test",
            workflow_path.name,
            "--profile", self.galaxy_profile,
            "--test_output_json", "tool_test_output.json",
        ]
        print(f"\n  Starting planemo test: {workflow_path.name}")
        print(f"  Directory: {workflow_dir}")
        try:
            process = subprocess.Popen(
                cmd, cwd=str(workflow_dir),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            return process
        except Exception as e:
            print(f"  Failed to start planemo: {e}")
            return None

    def wait_for_json_file(self, workflow_dir: Path, timeout_minutes: int = 60) -> Optional[Path]:
        """Wait for tool_test_output.json to be written by Planemo."""
        json_path = workflow_dir / "tool_test_output.json"
        start_time = time.time()
        timeout_seconds = timeout_minutes * 60
        print(f"\n  Waiting for Planemo JSON output (timeout: {timeout_minutes}m)...")

        while time.time() - start_time < timeout_seconds:
            elapsed = int(time.time() - start_time)
            if json_path.exists():
                try:
                    size = json_path.stat().st_size
                    if size == 0:
                        time.sleep(2)
                        continue
                    with open(json_path) as f:
                        first = f.read(1)
                    if first == "{":
                        print(f"  JSON ready after {elapsed}s ({size} bytes)")
                        time.sleep(2)
                        return json_path
                except Exception:
                    pass
            if elapsed % 30 == 0 and elapsed > 0:
                print(f"  Still waiting... ({elapsed // 60}m {elapsed % 60}s)")
            time.sleep(5)

        print(f"  Timeout after {timeout_minutes} minutes")
        return None

    def parse_missing_tools(self, json_path: Path,
                            fetch_details: bool = True) -> Tuple[List[str], List[Dict]]:
        """Parse tool_test_output.json for missing tool errors."""
        missing_tools = []
        tool_details = []

        if not json_path or not json_path.exists():
            return missing_tools, tool_details

        try:
            with open(json_path) as f:
                test_output = json.load(f)
        except json.JSONDecodeError as e:
            print(f"  Invalid JSON: {e}")
            return missing_tools, tool_details

        tests = test_output.get("tests", [])
        print(f"  Parsed {len(tests)} test entries")

        for test in tests:
            execution_problem = test.get("data", {}).get("execution_problem")
            if not execution_problem:
                continue
            if "the following required tools are not installed:" in execution_problem:
                tools_part = execution_problem.split("not installed:")[-1].strip()
                tools_part = re.sub(r'[")]$', "", tools_part)
                for entry in tools_part.split(","):
                    entry = entry.strip()
                    m = re.search(r"(toolshed\.g2\.bx\.psu\.edu[^\s\(]+)", entry)
                    if m:
                        tool_id = m.group(1)
                        missing_tools.append(tool_id)
            json_match = re.search(r"(\{.*\})", execution_problem)
            if json_match:
                try:
                    err = json.loads(json_match.group(1)).get("err_msg", "")
                    m = re.search(r"(toolshed\.g2\.bx\.psu\.edu[^\s]+)", err)
                    if m and m.group(1) not in missing_tools:
                        missing_tools.append(m.group(1))
                except Exception:
                    pass

        missing_tools = sorted(set(missing_tools))

        if missing_tools:
            print(f"  Missing tools ({len(missing_tools)}):")
            for t in missing_tools:
                print(f"    - {t}")
        else:
            print(f"  No missing tools found")

        summary = test_output.get("summary", {})
        if summary:
            print(f"  Test summary: total={summary.get('total',0)} "
                  f"passed={summary.get('passed',0)} failed={summary.get('failed',0)}")

        if fetch_details and missing_tools and self.toolshed_info:
            print(f"\n  Fetching ToolShed details for {len(missing_tools)} tools...")
            for tool_url in missing_tools:
                details = self.toolshed_info.get_tool_details(tool_url)
                tool_details.append(details)
                if details.get("error"):
                    print(f"    Warning: {details['error']}")
                else:
                    print(f"    {details['repository']} (owner: {details['owner']})")

        return missing_tools, tool_details

    def test_workflow(self, ga_path: Path, timeout_minutes: int = 60,
                      fetch_details: bool = True) -> Tuple[List[str], List[Dict], Dict]:
        """Run full test cycle: planemo → parse JSON → ToolShed lookup."""
        print(f"\n{'='*60}")
        print(f"Testing: {ga_path.name}")
        print(f"{'='*60}")

        process = self.run_planemo_test(ga_path)
        if not process:
            return [], [], {}

        json_path = self.wait_for_json_file(ga_path.parent, timeout_minutes)
        if not json_path:
            return [], [], {}

        missing_tools, tool_details = self.parse_missing_tools(json_path, fetch_details)
        test_results = {}
        try:
            with open(json_path) as f:
                test_results = json.load(f)
        except Exception:
            pass

        return missing_tools, tool_details, test_results

    def process_workflow(self, workflow: Dict, max_versions: Union[int, str] = 2,
                         timeout_minutes: int = 60,
                         fetch_details: bool = True) -> List[Dict]:
        """Download and test versions of a workflow."""
        wf_id = workflow["id"]
        wf_name = workflow.get("name", f"workflow_{wf_id}")
        print(f"\n{'='*70}")
        print(f"Workflow: {wf_name} (ID: {wf_id})")
        print(f"  URL: {workflow.get('url', '')}")
        print(f"{'='*70}")

        galaxy_versions = self.get_galaxy_versions(workflow)
        if not galaxy_versions:
            print("  No Galaxy versions found")
            return []

        if max_versions == "all":
            versions_to_process = galaxy_versions
        else:
            versions_to_process = galaxy_versions[:max_versions]

        print(f"  Processing {len(versions_to_process)} of {len(galaxy_versions)} versions")
        reports = []

        for i, version in enumerate(versions_to_process, 1):
            ver_id = version["id"]
            ver_name = version.get("name", ver_id)
            print(f"\n  [{i}/{len(versions_to_process)}] Version: {ver_name} (id: {ver_id})")

            ga_path = self.download_workflow(wf_id, ver_id, wf_name)
            if not ga_path:
                continue

            missing_tools, tool_details, test_results = self.test_workflow(
                ga_path, timeout_minutes, fetch_details
            )

            report = {
                "source": "workflowhub",
                "workflow_id": wf_id,
                "workflow_name": wf_name,
                "workflow_url": workflow.get("url", ""),
                "organization": workflow.get("organization", ""),
                "version_id": ver_id,
                "version_name": ver_name,
                "timestamp": datetime.now().isoformat(),
                "workflow_path": str(ga_path),
                "galaxy_profile": self.galaxy_profile,
                "missing_tools": missing_tools,
                "tool_details": tool_details,
                "test_results": test_results,
                "status": "tested",
            }

            json_path = ga_path.parent / "tool_test_output.json"
            if json_path.exists():
                report["test_output_json"] = str(json_path)
                report["test_output_json_size"] = json_path.stat().st_size

            reports.append(report)
            if i < len(versions_to_process):
                time.sleep(2)

        return reports

    def batch_process(self, search: str = None, organization: str = None,
                      max_workflows: int = 3, versions_per_workflow: Union[int, str] = 2,
                      timeout_minutes: int = 60, fetch_details: bool = True) -> List[Dict]:
        """Search WorkflowHub and test multiple workflows."""
        workflows = self.search_workflows(
            name=search, organization=organization, max_results=max_workflows
        )
        if not workflows:
            print("No workflows found")
            return []

        all_reports = []
        for i, wf in enumerate(workflows, 1):
            print(f"\n[{i}/{len(workflows)}] {wf.get('name', wf['id'])}")
            reports = self.process_workflow(
                wf, max_versions=versions_per_workflow,
                timeout_minutes=timeout_minutes, fetch_details=fetch_details
            )
            all_reports.extend(reports)

        return all_reports

    def generate_report(self, reports: List[Dict]) -> Dict:
        """Aggregate results into a master report."""
        master = {
            "generated": datetime.now().isoformat(),
            "source": "workflowhub",
            "galaxy_profile": self.galaxy_profile,
            "bioblend_available": BIOBLEND_AVAILABLE,
            "total_versions_processed": len(reports),
            "unique_workflows": len(set(r["workflow_id"] for r in reports)),
            "workflows_with_missing_tools": 0,
            "all_missing_tools": [],
            "all_tool_details": [],
            "workflow_details": reports,
            "statistics": {"total_missing_tool_instances": 0},
        }
        all_tools = []
        for r in reports:
            if r.get("missing_tools"):
                master["workflows_with_missing_tools"] += 1
                all_tools.extend(r["missing_tools"])
                master["statistics"]["total_missing_tool_instances"] += len(r["missing_tools"])
                if r.get("tool_details"):
                    master["all_tool_details"].extend(r["tool_details"])
        master["all_missing_tools"] = sorted(set(all_tools))
        master["unique_missing_tools_count"] = len(master["all_missing_tools"])
        return master

    def write_text_report(self, master: Dict, path: str):
        """Write a plain-text table report."""
        lines = []
        lines.append("WorkflowHub Inspector Report")
        lines.append(f"Generated : {master['generated']}")
        lines.append(f"Profile   : {master['galaxy_profile']}")
        lines.append("")

        # Summary block
        lines.append("Summary")
        lines.append("-" * 40)
        lines.append(f"Versions tested             : {master['total_versions_processed']}")
        lines.append(f"Unique workflows            : {master['unique_workflows']}")
        lines.append(f"Workflows with missing tools: {master['workflows_with_missing_tools']}")
        lines.append(f"Unique missing tools        : {master['unique_missing_tools_count']}")
        lines.append(f"Total missing tool instances: {master['statistics']['total_missing_tool_instances']}")
        lines.append("")

        # Per-version results table
        lines.append("Results by workflow version")
        lines.append("-" * 40)
        col_wf  = max((len(r["workflow_name"]) for r in master["workflow_details"]), default=20)
        col_wf  = max(col_wf, len("Workflow"))
        col_ver = max((len(str(r["version_name"])) for r in master["workflow_details"]), default=10)
        col_ver = max(col_ver, len("Version"))
        col_org = max((len(r.get("organization", "")) for r in master["workflow_details"]), default=12)
        col_org = max(col_org, len("Organization"))
        col_n   = len("Missing tools")

        header = (f"{'Workflow':<{col_wf}}  {'Version':<{col_ver}}  "
                  f"{'Organization':<{col_org}}  {'Missing tools':>{col_n}}")
        sep    = "-" * len(header)
        lines.append(header)
        lines.append(sep)

        for r in master["workflow_details"]:
            n = len(r.get("missing_tools", []))
            status = str(n) if n else "none"
            lines.append(
                f"{r['workflow_name']:<{col_wf}}  "
                f"{str(r['version_name']):<{col_ver}}  "
                f"{r.get('organization', ''):<{col_org}}  "
                f"{status:>{col_n}}"
            )

        lines.append("")

        # Missing tools detail per workflow
        any_missing = any(r.get("missing_tools") for r in master["workflow_details"])
        if any_missing:
            lines.append("Missing tools detail")
            lines.append("-" * 40)
            for r in master["workflow_details"]:
                tools = r.get("missing_tools", [])
                if not tools:
                    continue
                lines.append(f"{r['workflow_name']} ({r['version_name']})")
                for t in tools:
                    lines.append(f"  {t}")
                lines.append("")

        # All unique missing tools
        if master["all_missing_tools"]:
            lines.append("All unique missing tools")
            lines.append("-" * 40)
            for i, t in enumerate(master["all_missing_tools"], 1):
                lines.append(f"  {i:>3}. {t}")
            lines.append("")

        with open(path, "w") as f:
            f.write("\n".join(lines) + "\n")
        print(f"Text report saved to: {path}")

    def display_report(self, master: Dict):
        """Print master report to terminal."""
        print("\n" + "="*80)
        print("WORKFLOWHUB INSPECTOR - REPORT")
        print(f"  Generated: {master['generated']}")
        print(f"  Galaxy Profile: {master['galaxy_profile']}")
        print(f"  BioBlend: {'Available' if master['bioblend_available'] else 'Not available'}")
        print("="*80)
        print(f"\nSummary:")
        print(f"  Versions tested:              {master['total_versions_processed']}")
        print(f"  Unique workflows:             {master['unique_workflows']}")
        print(f"  Workflows with missing tools: {master['workflows_with_missing_tools']}")
        print(f"  Unique missing tools:         {master['unique_missing_tools_count']}")
        print(f"  Total missing tool instances: {master['statistics']['total_missing_tool_instances']}")

        if master["all_missing_tools"]:
            print(f"\nAll missing tools:")
            for i, t in enumerate(master["all_missing_tools"], 1):
                print(f"  {i}. {t}")

        print(f"\nPer-version results:")
        for r in master["workflow_details"]:
            missing = len(r.get("missing_tools", []))
            status = f"{missing} missing tools" if missing else "OK - no missing tools"
            print(f"  {r['workflow_name']} ({r['version_name']}): {status}")
            if r.get("test_output_json"):
                size = r.get("test_output_json_size", 0)
                print(f"    JSON: {os.path.basename(r['test_output_json'])} ({size} bytes)")

        print("="*80)


def parse_versions_arg(value: str) -> Union[int, str]:
    if value.lower() == "all":
        return "all"
    try:
        return int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid --versions-per-workflow value: '{value}'. Use an integer or 'all'."
        )


def main():
    parser = argparse.ArgumentParser(
        description="WorkflowHub Inspector - test Galaxy workflows from WorkflowHub"
    )
    parser.add_argument("--search", "-s", help="Search by name (e.g. 'assembly', 'RNA')")
    parser.add_argument("--organization", "-org", help="Filter by organization name")
    parser.add_argument("--id", help="Specific WorkflowHub workflow ID")
    parser.add_argument("--version", help="Specific version ID (use with --id)")
    parser.add_argument("--profile", default="galaxy_profile",
                        help="Planemo Galaxy profile (default: galaxy_profile)")
    parser.add_argument("--max-workflows", "-mw", type=int, default=3,
                        help="Max workflows to process (default: 3)")
    parser.add_argument("--versions-per-workflow", "-vpw", type=parse_versions_arg, default=2,
                        help="Versions per workflow: integer or 'all' (default: 2)")
    parser.add_argument("--timeout", "-t", type=int, default=60,
                        help="Planemo timeout in minutes (default: 60)")
    parser.add_argument("--workspace", "-w", default="./workflowhub_workspace",
                        help="Directory for downloaded workflows and outputs")
    parser.add_argument("--output", "-o", default="workflowhub_report.json",
                        help="Output report filename (default: workflowhub_report.json)")
    parser.add_argument("--no-tool-details", action="store_true",
                        help="Skip ToolShed lookups for missing tools")
    parser.add_argument("--toolshed-url", default="https://toolshed.g2.bx.psu.edu",
                        help="ToolShed URL (default: https://toolshed.g2.bx.psu.edu)")
    parser.add_argument("--list-only", action="store_true",
                        help="List matching workflows without testing them")

    args = parser.parse_args()

    if not any([args.search, args.organization, args.id]):
        parser.error("Provide at least one of: --search, --organization, --id")

    # Check planemo is available (unless just listing)
    if not args.list_only:
        if subprocess.run("which planemo", shell=True, capture_output=True).returncode != 0:
            print("Error: planemo not found. Activate your planemo virtualenv first:")
            print("  source ~/planemo/bin/activate")
            sys.exit(1)

    inspector = WorkflowHubInspector(
        workspace_dir=args.workspace,
        galaxy_profile=args.profile,
        toolshed_url=args.toolshed_url,
    )

    fetch_details = BIOBLEND_AVAILABLE and not args.no_tool_details

    print("WorkflowHub Inspector")
    print(f"  Profile: {args.profile}")
    print(f"  Workspace: {args.workspace}")
    print(f"  BioBlend: {'enabled' if fetch_details else 'disabled'}")

    reports = []

    if args.id:
        # Single workflow by ID
        wf = inspector.get_workflow_by_id(args.id)
        if not wf:
            print(f"Workflow ID {args.id} not found")
            sys.exit(1)

        if args.list_only:
            print(f"\n{wf['id']}: {wf.get('name', '')}")
            for v in inspector.get_galaxy_versions(wf):
                print(f"  version {v['id']}: {v.get('name', '')}")
            return

        if args.version:
            # Single version
            ga_path = inspector.download_workflow(args.id, args.version, wf.get("name"))
            if ga_path:
                missing_tools, tool_details, test_results = inspector.test_workflow(
                    ga_path, args.timeout, fetch_details
                )
                reports = [{
                    "source": "workflowhub",
                    "workflow_id": args.id,
                    "workflow_name": wf.get("name", args.id),
                    "workflow_url": wf.get("url", ""),
                    "organization": wf.get("organization", ""),
                    "version_id": args.version,
                    "version_name": args.version,
                    "timestamp": datetime.now().isoformat(),
                    "workflow_path": str(ga_path),
                    "galaxy_profile": args.profile,
                    "missing_tools": missing_tools,
                    "tool_details": tool_details,
                    "test_results": test_results,
                    "status": "tested",
                }]
        else:
            reports = inspector.process_workflow(
                wf, max_versions=args.versions_per_workflow,
                timeout_minutes=args.timeout, fetch_details=fetch_details
            )
    else:
        # Search-based batch
        if args.list_only:
            workflows = inspector.search_workflows(
                name=args.search, organization=args.organization,
                max_results=args.max_workflows
            )
            print(f"\nFound {len(workflows)} workflows:")
            for wf in workflows:
                galaxy_versions = inspector.get_galaxy_versions(wf)
                print(f"  ID {wf['id']}: {wf.get('name', '')} "
                      f"({len(galaxy_versions)} Galaxy version(s)) "
                      f"[{wf.get('organization', '')}]")
            return

        reports = inspector.batch_process(
            search=args.search,
            organization=args.organization,
            max_workflows=args.max_workflows,
            versions_per_workflow=args.versions_per_workflow,
            timeout_minutes=args.timeout,
            fetch_details=fetch_details,
        )

    if not reports:
        print("No workflows were tested.")
        return

    master = inspector.generate_report(reports)
    inspector.display_report(master)

    with open(args.output, "w") as f:
        json.dump(master, f, indent=2)
    print(f"\nReport saved to: {args.output}")

    txt_output = args.output.replace(".json", ".txt") if args.output.endswith(".json") else args.output + ".txt"
    inspector.write_text_report(master, txt_output)


if __name__ == "__main__":
    main()
