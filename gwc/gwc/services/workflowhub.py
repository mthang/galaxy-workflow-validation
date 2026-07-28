"""WorkflowHub API client."""

import json
import urllib.parse
from pathlib import Path
from typing import Optional, List, Dict, Any


class WorkflowHubClient:
    """Client for WorkflowHub TRS API."""

    def __init__(self, trs_base: str, base_url: str):
        self.trs_base = trs_base.rstrip("/")
        self.base_url = base_url.rstrip("/")

    def _get(self, path: str, params: dict = None) -> Any:
        """GET request to WorkflowHub TRS API."""
        url = self.trs_base + path
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

    def search(self, name: str = None, organization: str = None, max_results: int = 10) -> List[Dict]:
        """Search WorkflowHub for Galaxy workflows."""
        params = {"descriptorType": "GALAXY", "limit": 100, "offset": 0}
        if name:
            params["name"] = name
        if organization:
            params["organization"] = organization

        results = []
        while len(results) < max_results:
            page = self._get("/tools", params)
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

    def get_workflow(self, workflow_id: str) -> Optional[Dict]:
        """Get workflow by ID."""
        return self._get(f"/tools/{workflow_id}")

    def get_galaxy_versions(self, workflow: Dict) -> List[Dict]:
        """Return versions that have a GALAXY descriptor, oldest-first."""
        versions = [v for v in workflow.get("versions", [])
                    if "GALAXY" in v.get("descriptor_type", [])]
        return versions

    def download_ga(self, workflow_id: str, version_id: str,
                   workspace: Path, workflow_name: str = None) -> Optional[Path]:
        """Download a .ga file from WorkflowHub."""
        safe_name = (workflow_name or workflow_id).replace("/", "_").replace(" ", "_")[:60]
        dest_dir = workspace / f"workflowhub_{workflow_id}" / f"v{version_id}"
        dest_dir.mkdir(parents=True, exist_ok=True)

        descriptor = self._get(f"/tools/{workflow_id}/versions/{version_id}/GALAXY/descriptor")
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
        files = self._get(f"/tools/{workflow_id}/versions/{version_id}/GALAXY/files") or []
        ga_filename = next(
            (f["path"] for f in files if f.get("file_type") == "PRIMARY_DESCRIPTOR"), None
        )

        if not ga_filename:
            raw_name = (parsed.get("name") or f"workflow_{workflow_id}").strip()
            ga_filename = raw_name.replace("/", "_") + ".ga"

        # Use only the filename part
        ga_path = dest_dir / Path(ga_filename).name
        ga_path.parent.mkdir(parents=True, exist_ok=True)

        with open(ga_path, "w") as f:
            f.write(content)

        return ga_path
