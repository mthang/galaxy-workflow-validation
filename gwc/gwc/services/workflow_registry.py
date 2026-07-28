"""Unified workflow registry interface for WorkflowHub and Dockstore."""

import logging
from pathlib import Path
from typing import List, Dict, Optional, Any, Union

from .workflowhub import WorkflowHubClient
from .dockstore import DockstoreClient
from ..utils.config_loader import load_config

logger = logging.getLogger(__name__)


class WorkflowRegistry:
    """
    Unified interface for workflow registries (WorkflowHub and Dockstore).

    Handles searching, version listing, selection, and downloading of Galaxy workflows.
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize registry clients with given configuration.

        Args:
            config: Configuration dictionary. If None, load default config.
                   Expected keys: 'workflowhub' and 'dockstore' with 'trs_base' and 'base_url'.
        """
        if config is None:
            config = load_config(None)

        # Extract registry configs with fallbacks
        wh_config = config.get('workflowhub', {})
        ds_config = config.get('dockstore', {})

        self.workflowhub = WorkflowHubClient(
            trs_base=wh_config.get('trs_base', 'https://workflowhub.eu/ga4gh/trs/v2'),
            base_url=wh_config.get('base_url', 'https://workflowhub.eu')
        )

        self.dockstore = DockstoreClient(
            trs_base=ds_config.get('trs_base', 'https://dockstore.org/api/ga4gh/trs/v2'),
            base_url=ds_config.get('base_url', 'https://dockstore.org')
        )

        self.config = config

    # -------------------------------------------------------------------------
    # Search
    # -------------------------------------------------------------------------

    def search(self, registry: str, query: str, max_results: int = 10) -> List[Dict]:
        """
        Search for workflows in a specific registry.

        Args:
            registry: 'workflowhub' or 'dockstore'
            query: Search term
            max_results: Maximum number of results

        Returns:
            List of workflow metadata dicts
        """
        if registry == "workflowhub":
            return self.workflowhub.search(name=query, max_results=max_results)
        elif registry == "dockstore":
            return self.dockstore.search(query, max_results=max_results)
        else:
            logger.error(f"Unknown registry: {registry}")
            return []

    # -------------------------------------------------------------------------
    # Workflow info
    # -------------------------------------------------------------------------

    def get_workflow_info(self, registry: str, identifier: str) -> Optional[Dict]:
        """
        Get detailed workflow metadata from a registry.

        Args:
            registry: 'workflowhub' or 'dockstore'
            identifier: Workflow ID (for WorkflowHub) or entry path (for Dockstore)

        Returns:
            Workflow metadata dict, or None if not found
        """
        if registry == "workflowhub":
            return self.workflowhub.get_workflow(identifier)
        elif registry == "dockstore":
            # Dockstore doesn't have a direct get by ID; we can get versions
            # but we need the tool info via TRS. For now, just return a stub.
            return {"id": identifier, "entry": identifier, "name": identifier.split("/")[-1]}
        else:
            logger.error(f"Unknown registry: {registry}")
            return None

    # -------------------------------------------------------------------------
    # Versions
    # -------------------------------------------------------------------------

    def get_versions(self, registry: str, identifier: str) -> List:
        """
        Get available versions for a workflow.

        Args:
            registry: 'workflowhub' or 'dockstore'
            identifier: Workflow ID or entry path

        Returns:
            List of version objects (dict for WorkflowHub, str for Dockstore)
        """
        if registry == "workflowhub":
            wf = self.workflowhub.get_workflow(identifier)
            if wf:
                return self.workflowhub.get_galaxy_versions(wf)
            return []
        elif registry == "dockstore":
            return self.dockstore.get_versions(identifier)
        else:
            logger.error(f"Unknown registry: {registry}")
            return []

    # -------------------------------------------------------------------------
    # Version selection
    # -------------------------------------------------------------------------

    def select_versions(self, registry: str, versions: List, spec: str) -> List:
        """
        Select versions based on a specification string.
        - 'latest' → most recent real release
        - 'all' → all versions
        - integer N → N most recent real releases
        - specific version name(s) → exact matches only; no fallback

        Args:
            registry: 'workflowhub' or 'dockstore'
            versions: List of version objects (as returned by get_versions)
            spec: Version specifier ('latest', 'all', 'N', or comma-separated names)

        Returns:
            Filtered list of versions (empty if no match)
        """
        if registry == "workflowhub":
            return self._select_workflowhub_versions(versions, spec)
        elif registry == "dockstore":
            return self._select_dockstore_versions(versions, spec)
        else:
            logger.error(f"Unknown registry: {registry}")
            return []

    def _select_workflowhub_versions(self, versions: List[Dict], spec: str) -> List[Dict]:
        """
        Select WorkflowHub versions.
        - 'latest' → most recent real release (or all versions if none)
        - 'all' → all versions
        - integer N → N most recent real releases
        - specific version name(s) → exact matches only; if no match, return [] (no fallback)
        """
        def is_real_release(v: Dict) -> bool:
            name = v.get("name", "").lower()
            return "ignore" not in name

        if spec == "latest":
            releases = [v for v in versions if is_real_release(v)]
            candidates = releases if releases else versions
            return candidates[-1:] if candidates else []

        if spec == "all":
            return versions

        # Try integer (N most recent)
        try:
            n = int(spec)
            if n <= 0:
                logger.warning(f"Invalid version count {n}, using 'latest'")
                return self._select_workflowhub_versions(versions, "latest")
            releases = [v for v in versions if is_real_release(v)]
            candidates = releases if releases else versions
            return candidates[-n:] if len(candidates) >= n else candidates
        except ValueError:
            pass

        # Exact match for specific version names
        names = {v.strip() for v in spec.split(",")}
        matched = [
            v for v in versions
            if v.get("name", "").strip() in names
            or str(v.get("id", "")).strip() in names
        ]

        # DO NOT FALL BACK TO latest – return empty list if no exact match
        if not matched:
            logger.warning(f"No exact version matched '{spec}' – skipping workflow")
            return []

        return matched

    def _select_dockstore_versions(self, versions: List[str], spec: str) -> List[str]:
        """
        Select Dockstore versions with exact matching; no fallback for specific versions.
        - 'latest' → most recent real release (excluding branches like main/master)
        - 'all' → all versions
        - integer N → N most recent real releases
        - specific version name(s) → exact matches only; if no match, return []
        """
        branch_names = {"main", "master", "develop", "dev"}

        def release_versions(vs: List[str]) -> List[str]:
            return [v for v in vs if v.lower() not in branch_names]

        if spec == "latest":
            releases = release_versions(versions)
            candidates = releases if releases else versions
            return candidates[:1] if candidates else []

        if spec == "all":
            return versions

        # Try integer (N most recent)
        try:
            n = int(spec)
            if n <= 0:
                logger.warning(f"Invalid version count {n}, using 'latest'")
                return self._select_dockstore_versions(versions, "latest")
            releases = release_versions(versions)
            candidates = releases if releases else versions
            return candidates[:n] if len(candidates) >= n else candidates
        except ValueError:
            pass

        # Exact match for specific version names
        names = {v.strip() for v in spec.split(",")}
        matched = [v for v in versions if v.strip() in names]

        if not matched:
            logger.warning(f"No exact version matched '{spec}' – skipping workflow")
            return []

        return matched

    # -------------------------------------------------------------------------
    # Download
    # -------------------------------------------------------------------------

    def download_ga(
        self,
        registry: str,
        identifier: str,
        version: Union[str, Dict],
        workspace: Path,
        name: Optional[str] = None
    ) -> Optional[Path]:
        """
        Download a Galaxy workflow .ga file.

        Args:
            registry: 'workflowhub' or 'dockstore'
            identifier: Workflow ID or entry path
            version: Version identifier (str for Dockstore, dict for WorkflowHub)
            workspace: Directory to save the file
            name: Optional custom workflow name

        Returns:
            Path to downloaded .ga file, or None if failed.
        """
        if registry == "workflowhub":
            # version is a dict with 'id' key
            ver_id = version["id"] if isinstance(version, dict) else version
            return self.workflowhub.download_ga(identifier, ver_id, workspace, name)
        elif registry == "dockstore":
            # version is a string
            return self.dockstore.download_ga(identifier, version, workspace)
        else:
            logger.error(f"Unknown registry: {registry}")
            return None
