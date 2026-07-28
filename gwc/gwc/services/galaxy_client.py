"""Galaxy instance client for tool cache building."""

import json
import sys
from pathlib import Path
from typing import Tuple, Dict, Set

try:
    import urllib.request
    import urllib.error
except ImportError:
    pass

try:
    from bioblend.galaxy import GalaxyInstance
    BIOBLEND_AVAILABLE = True
except ImportError:
    BIOBLEND_AVAILABLE = False


class GalaxyClient:
    """Client for interacting with Galaxy instances."""

    @classmethod
    def read_planemo_profile(cls, profile_name: str) -> Tuple[str, str]:
        """Read Galaxy URL and API key from a Planemo profile."""
        path = Path.home() / ".planemo" / "profiles" / profile_name / "planemo_profile_options.json"

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

    @classmethod
    def build_tool_cache(cls, galaxy_url: str, galaxy_key: str) -> Dict[str, Set[str]]:
        """Fetch tools from Galaxy via BioBlend and build cache."""
        if not BIOBLEND_AVAILABLE:
            print("Error: BioBlend required for Galaxy tool checking.")
            print("Install with: pip install bioblend")
            sys.exit(1)

        print(f"\nConnecting to Galaxy at {galaxy_url}...")
        gi = GalaxyInstance(url=galaxy_url, key=galaxy_key)

        try:
            tools = gi.tools.get_tools()
        except Exception as e:
            print(f"Error: Could not retrieve tools from Galaxy: {e}")
            sys.exit(1)

        from ..core.tool_checker import ToolChecker
        cache = ToolChecker.build_cache(tools)
        print(f"  Found {len(tools)} tools installed ({len(cache)} unique ToolShed tools)")
        return cache

    @classmethod
    def build_public_tool_cache(cls, galaxy_url: str) -> Dict[str, Set[str]]:
        """Fetch tool list from public Galaxy API without authentication."""
        api_url = galaxy_url.rstrip("/") + "/api/tools?in_panel=false"
        print(f"\nFetching public tool panel from {api_url} ...")

        req = urllib.request.Request(api_url, headers={"Accept": "application/json"})

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                tools = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            print(f"Error: HTTP {e.code} fetching public tool list from {api_url}")
            print("  This instance may not expose its tool list publicly; "
                  "use a Planemo profile (keyed access) via --profile instead.")
            sys.exit(1)
        except Exception as e:
            print(f"Error: Could not retrieve public tool list: {e}")
            sys.exit(1)

        from ..core.tool_checker import ToolChecker
        cache = ToolChecker.build_cache(tools)
        print(f"  Found {len(tools)} tools installed ({len(cache)} unique ToolShed tools)")
        return cache
