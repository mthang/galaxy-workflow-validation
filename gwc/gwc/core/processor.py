"""Workflow processing logic (shared between main and other modules)."""

from pathlib import Path
from typing import List, Dict, Optional, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import logging

from ..models.workflow_spec import WorkflowSpec
from ..services.workflow_registry import WorkflowRegistry
from ..core.workflow_analyzer import WorkflowAnalyzer
from ..utils.config_loader import load_config

logger = logging.getLogger(__name__)


def analyze_workflow(
    ga_path: Path,
    info: Dict[str, Any],
    version_label: str,
    tool_cache: Dict,
    skip_types: Optional[set] = None
) -> Dict[str, Any]:
    """
    Analyze a single workflow file.

    Args:
        ga_path: Path to the .ga file
        info: Dict with 'name', 'id', 'source', 'url'
        version_label: Version string to display
        tool_cache: Galaxy tool cache (may be empty if static mode)
        skip_types: Set of step types to skip in wiring checks

    Returns:
        Dict containing analysis results
    """
    from datetime import datetime

    analysis = WorkflowAnalyzer.analyze(ga_path, tool_cache, skip_types)

    return {
        "source": info.get("source", "unknown"),
        "workflow_name": info.get("name", ""),
        "workflow_id": info.get("id", ""),
        "workflow_url": info.get("url", ""),
        "version": version_label,
        "timestamp": datetime.now().isoformat(),
        **analysis
    }


def create_version_not_found_result(
    registry: str,
    identifier: str,
    version_spec: str,
    name: Optional[str] = None,
    url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a placeholder result for a version that was requested but not found.

    Args:
        registry: 'workflowhub' or 'dockstore'
        identifier: Workflow ID or entry path
        version_spec: The version string that was requested
        name: Workflow name (optional)
        url: Workflow URL (optional)

    Returns:
        A result dict with status 'version_not_found'
    """
    return {
        "source": registry,
        "workflow_name": name or identifier,
        "workflow_id": identifier,
        "workflow_url": url or "",
        "version": version_spec,
        "timestamp": "N/A",
        "total_tools": 0,
        "n_exact": 0,
        "n_version_mismatch": 0,
        "n_missing": 0,
        "n_wiring_issues": 0,
        "n_structural_issues": 0,
        "workflow_status": "version_not_found",
        "ready_to_run": False,
        "structural_issues": [],
        "wiring_issues": [],
        "tool_statuses": [],
        "ga_path": None
    }


def process_workflow_spec(
    spec: WorkflowSpec,
    workspace: Path,
    tool_cache: Dict,
    skip_types: Optional[set] = None,
    config: Optional[Dict] = None
) -> List[Dict]:
    """
    Process a single workflow specification.

    Returns:
        List of result dicts (one per version checked). Always returns a list
        (empty if registry is unknown).
    """
    if config is None:
        config = load_config(None)

    registry = WorkflowRegistry(config)

    if spec.registry == "workflowhub":
        wf = registry.get_workflow_info("workflowhub", spec.registry_id)
        if not wf:
            logger.warning(f"WorkflowHub workflow '{spec.registry_id}' not found")
            # Return placeholder for the workflow itself
            return [create_version_not_found_result(
                registry="workflowhub",
                identifier=spec.registry_id,
                version_spec=spec.version,
                name=spec.name
            )]
        return process_workflowhub_workflow(wf, spec.version, registry, workspace, tool_cache, skip_types)

    elif spec.registry == "dockstore":
        return process_dockstore_workflow(spec.registry_id, spec.version, registry, workspace, tool_cache, skip_types)

    else:
        logger.error(f"Unknown registry: {spec.registry}")
        return []


def process_workflowhub_workflow(
    workflow: Dict,
    version_spec: str,
    registry: WorkflowRegistry,
    workspace: Path,
    tool_cache: Dict,
    skip_types: Optional[set] = None
) -> List[Dict]:
    """
    Process a WorkflowHub workflow (multiple versions).
    Returns a list of result dicts (one per version).
    If the requested version spec does not match any available version,
    a placeholder result with status 'version_not_found' is returned.
    """
    wf_id = workflow["id"]
    wf_name = workflow.get("name", f"workflow_{wf_id}")
    wf_url = workflow.get("url", f"{registry.workflowhub.base_url}/workflows/{wf_id}")

    all_versions = registry.get_versions("workflowhub", wf_id)
    chosen = registry.select_versions("workflowhub", all_versions, version_spec)

    # If no versions match the spec, return a placeholder result
    if not chosen:
        logger.warning(f"No version matched '{version_spec}' for workflow '{wf_name}'")
        return [create_version_not_found_result(
            registry="workflowhub",
            identifier=wf_id,
            version_spec=version_spec,
            name=wf_name,
            url=wf_url
        )]

    results = []
    for ver in chosen:
        ver_id = ver["id"]
        ver_label = ver.get("name", str(ver_id))
        ga_path = registry.download_ga("workflowhub", wf_id, ver_id, workspace, wf_name)
        if ga_path:
            info = {"name": wf_name, "id": wf_id, "url": wf_url, "source": "workflowhub"}
            results.append(analyze_workflow(ga_path, info, ver_label, tool_cache, skip_types))
        else:
            # Download failed – still add a placeholder? Maybe skip? We'll add a failing entry.
            results.append(create_version_not_found_result(
                registry="workflowhub",
                identifier=wf_id,
                version_spec=ver_label,
                name=wf_name,
                url=wf_url
            ))

    return results


def process_dockstore_workflow(
    entry: str,
    version_spec: str,
    registry: WorkflowRegistry,
    workspace: Path,
    tool_cache: Dict,
    skip_types: Optional[set] = None
) -> List[Dict]:
    """
    Process a Dockstore workflow (multiple versions).
    Returns a list of result dicts (one per version).
    If the requested version spec does not match any available version,
    a placeholder result with status 'version_not_found' is returned.
    """
    wf_name = entry.split("/")[-1]
    wf_url = f"{registry.dockstore.base_url}/workflows/{entry}"

    all_versions = registry.get_versions("dockstore", entry)
    chosen = registry.select_versions("dockstore", all_versions, version_spec)

    if not chosen:
        logger.warning(f"No version matched '{version_spec}' for Dockstore workflow '{entry}'")
        return [create_version_not_found_result(
            registry="dockstore",
            identifier=entry,
            version_spec=version_spec,
            name=wf_name,
            url=wf_url
        )]

    results = []
    for version in chosen:
        ga_path = registry.download_ga("dockstore", entry, version, workspace)
        if ga_path:
            info = {"name": wf_name, "id": entry, "url": wf_url, "source": "dockstore"}
            results.append(analyze_workflow(ga_path, info, version, tool_cache, skip_types))
        else:
            results.append(create_version_not_found_result(
                registry="dockstore",
                identifier=entry,
                version_spec=version,
                name=wf_name,
                url=wf_url
            ))

    return results


def process_workflows_parallel(
    specs: List[WorkflowSpec],
    workspace: Path,
    tool_cache: Dict,
    max_workers: int,
    skip_types: Optional[set] = None,
    config: Optional[Dict] = None
) -> List[Dict]:
    """
    Process multiple workflow specifications in parallel.
    Returns a list of all results (flattened).
    """
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_workflow_spec, spec, workspace, tool_cache, skip_types, config): spec
            for spec in specs
        }
        for future in as_completed(futures):
            spec = futures[future]
            try:
                res = future.result()
                if res:
                    results.extend(res)
                else:
                    logger.warning(f"No results for workflow: {spec.name}")
            except Exception as e:
                logger.error(f"Error processing workflow {spec.name}: {e}")
                # Add a placeholder for the error
                results.append(create_version_not_found_result(
                    registry=spec.registry,
                    identifier=spec.registry_id,
                    version_spec=spec.version,
                    name=spec.name
                ))
    return results
