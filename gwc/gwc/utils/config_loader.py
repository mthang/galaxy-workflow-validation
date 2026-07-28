"""Configuration loading utilities."""

import yaml
from pathlib import Path
from typing import Dict, Any, Optional


DEFAULT_CONFIG = {
    "workflowhub": {
        "trs_base": "https://workflowhub.eu/ga4gh/trs/v2",
        "base_url": "https://workflowhub.eu"
    },
    "dockstore": {
        "base_url": "https://dockstore.org",
        "trs_base": "https://dockstore.org/api/ga4gh/trs/v2"
    },
    "galaxy_instances": {
        "friendly_names": {
            "usegalaxy.org.au": "Galaxy Australia",
            "genome.usegalaxy.org.au": "Galaxy Australia",
            "usegalaxy.org": "Galaxy Main",
            "usegalaxy.eu": "Galaxy Europe"
        }
    },
    "defaults": {
        "profile_name": "galaxy_profile",
        "workspace_dir": "./workflow_workspace",
        "output_base": "workflow_check_report",
        "max_workflows": 10,
        "version_selection": "latest",
        "max_workers": 5
    },
    "skip_step_types": [
        "data_input",
        "data_collection_input",
        "parameter_input",
        "pause"
    ]
}


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load configuration from YAML file, merging with defaults.
    If file not found, return defaults.
    """
    config = DEFAULT_CONFIG.copy()

    if config_path is None:
        # Look for default locations
        possible_paths = [
            Path("config.yaml"),
            Path("config.yml"),
            Path.home() / ".gwc" / "config.yaml",
            Path(__file__).parent.parent / "config.yaml"
        ]
        for path in possible_paths:
            if path.exists():
                config_path = str(path)
                break

    if config_path and Path(config_path).exists():
        try:
            with open(config_path, 'r') as f:
                user_config = yaml.safe_load(f)
            if user_config:
                # Deep merge (simple update for top-level keys)
                for key, value in user_config.items():
                    if isinstance(value, dict) and key in config and isinstance(config[key], dict):
                        config[key].update(value)
                    else:
                        config[key] = value
        except Exception as e:
            print(f"Warning: Could not load config {config_path}: {e}")

    return config


def get_galaxy_friendly_name(config: Dict, url: str) -> str:
    """Get friendly name for a Galaxy URL."""
    names = config.get('galaxy_instances', {}).get('friendly_names', {})
    host = url.rstrip("/").split("//")[-1].split("/")[0]
    return names.get(host, url)


def get_skip_types(config: Dict) -> set:
    """Get skip types for wiring checker."""
    return set(config.get('skip_step_types', DEFAULT_CONFIG['skip_step_types']))
