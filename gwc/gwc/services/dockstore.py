"""Dockstore API client."""

import json
import re
import subprocess
import urllib.parse
from pathlib import Path
from typing import List, Optional, Dict, Any


class DockstoreClient:
    """Client for Dockstore TRS API with CLI fallback."""

    def __init__(self, trs_base: str, base_url: str):
        self.trs_base = trs_base.rstrip("/")
        self.base_url = base_url.rstrip("/")

    def _trs_get(self, path: str) -> Any:
        """GET request to Dockstore TRS API."""
        url = self.trs_base + path
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

    def _tool_id(self, entry: str) -> str:
        """Convert a Dockstore entry path to a URL-encoded TRS tool ID."""
        return urllib.parse.quote(f"#workflow/{entry}", safe="")

    def search(self, pattern: str, max_results: int = 10) -> List[Dict]:
        """Search Dockstore for workflows matching a pattern."""
        cmd = ["dockstore", "workflow", "search", "--pattern", pattern]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError:
            print("Error: dockstore CLI not found. Install it to use Dockstore.")
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
                            "url": f"{self.base_url}/workflows/{entry}",
                        })

        return workflows[:max_results]

    def get_versions(self, entry: str) -> List[str]:
        """Return version names for a Dockstore workflow, newest first."""
        tool_id = self._tool_id(entry)
        data = self._trs_get(f"/tools/{tool_id}")

        if data and data.get("versions"):
            return [v["name"] for v in data["versions"]
                    if "GALAXY" in v.get("descriptor_type", [])]

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

    def download_ga(self, entry: str, version: str, workspace: Path) -> Optional[Path]:
        """Download a Galaxy workflow .ga file from Dockstore."""
        safe = entry.replace("/", "_").replace(":", "_").replace(".", "_")
        dest_dir = workspace / f"dockstore_{safe}" / version
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Try TRS API first
        tool_id = self._tool_id(entry)
        ver_id = urllib.parse.quote(version, safe="")
        descriptor = self._trs_get(f"/tools/{tool_id}/versions/{ver_id}/GALAXY/descriptor")

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
        cmd = [
            "dockstore", "workflow", "download",
            "--entry", f"{entry}:{version}",
            "--descriptor", "all",
            "--output-dir", str(dest_dir)
        ]

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
