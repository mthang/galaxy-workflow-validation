"""WorkflowHub REST API client (non-TRS) for metadata retrieval."""

import json
import time
import sys
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any

import requests

logger = logging.getLogger(__name__)


class WorkflowHubREST:
    """Client for WorkflowHub REST API (using token authentication)."""

    def __init__(
        self,
        base_url: str = "https://workflowhub.eu",
        token: Optional[str] = None,
        token_file: Optional[Path] = None,
        rate_limit: float = 0.2
    ):
        """
        Initialize the client.

        Args:
            base_url: WorkflowHub base URL
            token: API token (if provided, overrides token_file)
            token_file: Path to file containing token (default ~/.workflowhub/api_token.txt)
            rate_limit: Seconds to sleep between requests (to be respectful)
        """
        self.base_url = base_url.rstrip('/')
        self.rate_limit = rate_limit
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

        # Determine token
        if token:
            self.token = token
        else:
            self.token = self._read_token(token_file)

        if self.token:
            self.session.headers.update({"Authorization": f"Token {self.token}"})

    @staticmethod
    def _read_token(token_file: Optional[Path]) -> Optional[str]:
        """Read token from file."""
        if token_file is None:
            token_file = Path.home() / ".workflowhub" / "api_token.txt"
        try:
            with open(token_file) as f:
                return f.read().strip()
        except FileNotFoundError:
            logger.error(f"Token file not found: {token_file}")
            return None

    def _request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Make a GET request, handle errors, and respect rate limit."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            time.sleep(self.rate_limit)
            return resp.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error {e.response.status_code} for {url}")
            return None
        except Exception as e:
            logger.error(f"Request failed: {e}")
            return None

    def get_current_user_id(self) -> Optional[str]:
        """Get the authenticated user's ID."""
        data = self._request("/people/current")
        if data:
            return data.get('data', {}).get('id')
        return None

    def list_mine(self) -> List[Dict]:
        """List workflows contributed by the authenticated user."""
        user_id = self.get_current_user_id()
        if not user_id:
            logger.error("Could not determine current user")
            return []
        params = {'filter[contributor]': user_id}
        data = self._request("/workflows", params=params)
        if data:
            return data.get('data', [])
        return []

    def list_project_workflows(
        self,
        project_id: Optional[str] = None,
        class_filter: Optional[str] = None
    ) -> List[Dict]:
        """
        List workflows in a project (or all projects from config) with optional class filter.
        Returns a list of enriched workflow dicts.
        """
        # If project_id is None, use the default project IDs (e.g., from config)
        # For now, we'll define defaults.
        default_project_ids = ["30", "54"]
        project_ids = [project_id] if project_id else default_project_ids

        all_workflows = []
        for pid in project_ids:
            logger.info(f"Fetching project {pid}")
            project_data = self._request(f"/projects/{pid}")
            if not project_data:
                continue
            workflows = project_data.get('data', {}).get('relationships', {}).get('workflows', {}).get('data', [])
            for wf in workflows:
                enriched = self._enrich_workflow(wf['id'], class_filter)
                if enriched:
                    all_workflows.append(enriched)
        return all_workflows

    def _enrich_workflow(self, workflow_id: str, class_filter: Optional[str] = None) -> Optional[Dict]:
        """Get full metadata for a workflow, including creators/institutions."""
        data = self._request(f"/workflows/{workflow_id}?include=creators,creators.institutions")
        if not data:
            return None

        wf_data = data.get('data', {})
        included = data.get('included', [])
        attr = wf_data.get('attributes', {})
        meta = wf_data.get('meta', {})

        # Filter by class
        wf_class = attr.get('workflow_class', {}).get('title', 'Unknown')
        if class_filter and class_filter.lower() not in wf_class.lower():
            return None

        # Extract creators and affiliations
        creator_rels = wf_data.get('relationships', {}).get('creators', {}).get('data', [])
        creators = []
        affiliations = []
        for rel in creator_rels:
            person = next((x for x in included if x['id'] == rel['id'] and x['type'] == 'people'), None)
            if person:
                p_attr = person.get('attributes', {})
                name = f"{p_attr.get('first_name', '')} {p_attr.get('last_name', '')}".strip()
                creators.append(name)
                inst_rels = person.get('relationships', {}).get('institutions', {}).get('data', [])
                for i_rel in inst_rels:
                    inst = next((x for x in included if x['id'] == i_rel['id'] and x['type'] == 'institutions'), None)
                    if inst:
                        affiliations.append(inst.get('attributes', {}).get('title', ''))

        return {
            'id': workflow_id,
            'title': attr.get('title', 'N/A'),
            'version': attr.get('version', 'N/A'),
            'workflow_class': wf_class,
            'description': attr.get('description', ''),
            'created': meta.get('created', 'N/A'),
            'modified': meta.get('modified', 'N/A'),
            'creators': creators if creators else ['Unknown'],
            'affiliations': list(set(affiliations)) if affiliations else ['None'],
            'url': f"{self.base_url}/workflows/{workflow_id}",
        }

    def get_workflow_details(self, workflow_id: str) -> Optional[Dict]:
        """Get detailed metadata for a single workflow (same as enrich, but without filtering)."""
        return self._enrich_workflow(workflow_id, None)

    def list_related_items(self, workflow_id: str) -> Dict[str, List[Dict]]:
        """Get related items (data_files, sops, publications, people)."""
        params = {'include': 'data_files,sops,publications,people'}
        data = self._request(f"/workflows/{workflow_id}", params=params)
        if not data:
            return {}
        included = data.get('included', [])
        rels = data.get('data', {}).get('relationships', {})
        result = {}
        for key in ['data_files', 'sops', 'publications', 'people']:
            items = []
            for rel in rels.get(key, {}).get('data', []):
                item = next((x for x in included if x['id'] == rel['id'] and x['type'] == rel['type']), None)
                if item:
                    attr = item.get('attributes', {})
                    items.append({
                        'id': rel['id'],
                        'type': rel['type'],
                        'name': attr.get('title') or attr.get('name') or f"ID: {rel['id']}",
                    })
            result[key] = items
        return result

    def download_rocrate(self, workflow_id: str, output_dir: Optional[Path] = None) -> Optional[Path]:
        """Download RO-Crate zip for a workflow."""
        url = f"{self.base_url}/workflows/{workflow_id}/ro_crate"
        try:
            resp = self.session.get(url, stream=True, timeout=60)
            resp.raise_for_status()
            if output_dir is None:
                output_dir = Path.cwd()
            output_dir.mkdir(parents=True, exist_ok=True)
            zip_path = output_dir / f"workflow_{workflow_id}_rocrate.zip"
            with open(zip_path, 'wb') as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
            logger.info(f"Downloaded RO-Crate to {zip_path}")
            return zip_path
        except Exception as e:
            logger.error(f"Failed to download RO-Crate: {e}")
            return None
