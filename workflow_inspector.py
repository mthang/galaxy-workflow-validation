#!/usr/bin/env python3
"""
Unified Workflow Agent - Uses --test_output_json to explicitly generate only JSON output
Supports "all" for --versions-per-workflow to test all versions
Integrates BioBlend to get detailed tool information from ToolShed
"""

import subprocess
import json
import sys
import os
from pathlib import Path
import re
from typing import List, Dict, Optional, Tuple, Any, Union
import time
import argparse
from datetime import datetime

# python workflow_inspector.py --entry "github.com/iwc-workflows/Assembly-decontamination-VGP9/main" --version v1.3


try:
    from bioblend import toolshed
    BIODLEND_AVAILABLE = True
except ImportError:
    BIODLEND_AVAILABLE = False
    print("⚠️  BioBlend not installed. Tool information will be limited.")
    print("   Install with: pip install bioblend")

class ToolShedInfo:
    """Class to fetch detailed information about tools from ToolShed"""
    
    def __init__(self, toolshed_url: str = "https://toolshed.g2.bx.psu.edu"):
        self.toolshed_url = toolshed_url
        self.ts = None
        if BIODLEND_AVAILABLE:
            try:
                self.ts = toolshed.ToolShedInstance(url=toolshed_url)
            except Exception as e:
                print(f"⚠️  Failed to connect to ToolShed: {e}")
    
    def parse_tool_url(self, tool_url: str) -> Dict[str, str]:
        """
        Parse a ToolShed URL to extract owner, repository, and version
        
        Example: toolshed.g2.bx.psu.edu/repos/richard-burhans/ncbi_fcs_adaptor/ncbi_fcs_adaptor/0.5.0+galaxy0
        Returns: {
            'owner': 'richard-burhans',
            'repository': 'ncbi_fcs_adaptor',
            'version': '0.5.0+galaxy0'
        }
        """
        parts = tool_url.split('/')
        
        # Format: domain/repos/{owner}/{repo_name}/{tool_name}/{version}
        if len(parts) >= 6 and parts[1] == 'repos':
            return {
                'owner': parts[2],
                'repository': parts[3],
                'tool_name': parts[4],
                'version': parts[5]
            }
        # Alternative format: domain/repos/{owner}/{repo_name}
        elif len(parts) >= 4 and parts[1] == 'repos':
            return {
                'owner': parts[2],
                'repository': parts[3],
                'tool_name': parts[3],
                'version': None
            }
        else:
            return {
                'owner': None,
                'repository': None,
                'tool_name': None,
                'version': None
            }
    
    def get_tool_details(self, tool_url: str) -> Dict[str, Any]:
        """
        Get detailed information about a tool from ToolShed
        
        Returns a dictionary with:
        - owner: Repository owner
        - repository: Repository name
        - version: Tool version from URL
        - latest_revision: Latest installable revision hash
        - revisions: All available revisions
        - repository_details: Full repository metadata
        """
        if not self.ts:
            return {'error': 'BioBlend not available or ToolShed connection failed'}
        
        parsed = self.parse_tool_url(tool_url)
        
        if not parsed['owner'] or not parsed['repository']:
            return {
                'error': f'Could not parse tool URL: {tool_url}',
                'parsed': parsed
            }
        
        result = {
            'tool_url': tool_url,
            'owner': parsed['owner'],
            'repository': parsed['repository'],
            'tool_name': parsed['tool_name'],
            'version': parsed['version'],
            'revisions': [],
            'latest_revision': None,
            'repository_details': None,
            'error': None
        }
        
        try:
            # Get all installable revisions for this repository
            revisions = self.ts.repositories.get_ordered_installable_revisions(
                parsed['repository'], 
                parsed['owner']
            )
            
            result['revisions'] = revisions
            if revisions:
                result['latest_revision'] = revisions[-1]  # Latest revision is last
            
            # Get repository details
            repositories = self.ts.repositories.get_repositories(
                name=parsed['repository'],
                owner=parsed['owner']
            )
            
            if repositories:
                result['repository_details'] = repositories[0]
                # Extract additional metadata
                repo = repositories[0]
                result['description'] = repo.get('description', '')
                result['long_description'] = repo.get('long_description', '')
                result['stars'] = repo.get('stars', 0)
                result['times_downloaded'] = repo.get('times_downloaded', 0)
                result['user_rating'] = repo.get('user_rating', None)
                
        except Exception as e:
            result['error'] = str(e)
        
        return result
    
    def get_tool_installation_command(self, tool_url: str) -> str:
        """
        Generate installation command for the tool
        """
        parsed = self.parse_tool_url(tool_url)
        
        if not parsed['owner'] or not parsed['repository']:
            return f"# Could not parse tool URL: {tool_url}"
        
        # Get the tool details to include revision
        details = self.get_tool_details(tool_url)
        revision = details.get('latest_revision', 'latest')
        
        if revision and revision != 'latest':
            return f"shed-tools install -g <galaxy_url> -a <api_key> --name {parsed['repository']} --owner {parsed['owner']} --revision {revision}"
        else:
            return f"shed-tools install -g <galaxy_url> -a <api_key> --name {parsed['repository']} --owner {parsed['owner']}"
    
    def batch_get_tool_details(self, tool_urls: List[str]) -> List[Dict[str, Any]]:
        """
        Get details for multiple tools
        """
        results = []
        for tool_url in tool_urls:
            results.append(self.get_tool_details(tool_url))
        return results

class UnifiedWorkflowAgent:
    def __init__(self, workspace_dir: str = "./workflow_workspace", galaxy_profile: str = "galaxy_profile", 
                 toolshed_url: str = "https://toolshed.g2.bx.psu.edu"):
        self.workspace = Path(workspace_dir)
        self.workspace.mkdir(exist_ok=True)
        self.galaxy_profile = galaxy_profile
        self.downloaded_workflows = []
        self.toolshed_info = ToolShedInfo(toolshed_url) if BIODLEND_AVAILABLE else None
        
    def query_dockstore(self, pattern: str = None, organization: str = None, 
                        workflow_type: str = None) -> List[Dict]:
        """
        Query Dockstore for workflows using proper CLI syntax
        """
        print(f"\n🔍 Querying Dockstore for workflows...")
        
        workflows = []
        
        try:
            # Build the search pattern
            search_parts = []
            if pattern:
                search_parts.append(pattern)
            if organization:
                search_parts.append(f"organization:{organization}")
            if workflow_type:
                search_parts.append(f"descriptorType:{workflow_type.upper()}")
            
            search_pattern = " AND ".join(search_parts) if search_parts else "*"
            
            cmd = ["dockstore", "workflow", "search", "--pattern", search_pattern]
            print(f"   Running: {' '.join(cmd)}")
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for line in lines[1:]:
                    if line.strip() and not line.startswith('---'):
                        parts = line.split()
                        if parts:
                            workflow_path = parts[0].strip('*').strip()
                            if workflow_path and '/' in workflow_path:
                                workflows.append({
                                    "entry": workflow_path,
                                    "name": workflow_path.split('/')[-1] if '/' in workflow_path else workflow_path,
                                })
                print(f"✅ Found {len(workflows)} workflows")
            else:
                print(f"⚠️  Query failed: {result.stderr}")
                
        except FileNotFoundError:
            print("❌ Dockstore CLI not found")
            
        return workflows
    
    def get_workflow_versions(self, entry: str) -> Dict:
        """
        Get workflow versions using dockstore workflow info
        """
        print(f"\n📋 Fetching versions for: {entry}")
        
        workflow_info = {
            "entry": entry,
            "versions": [],
            "author": None,
            "date_uploaded": None,
            "git_repo": None,
        }
        
        try:
            cmd = ["dockstore", "workflow", "info", "--entry", entry]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                output = result.stdout
                
                # Parse versions
                versions_match = re.search(r'WORKFLOW VERSIONS\s*\n\s*([^\n]+)', output, re.IGNORECASE)
                if versions_match:
                    versions_line = versions_match.group(1)
                    versions = re.split(r',|\s+', versions_line)
                    workflow_info["versions"] = [v.strip() for v in versions if v.strip()]
                
                # Parse author
                author_match = re.search(r'AUTHOR:\s*(.+)', output)
                if author_match:
                    workflow_info["author"] = author_match.group(1).strip()
                
                print(f"✅ Found {len(workflow_info['versions'])} versions")
                if workflow_info["versions"]:
                    print(f"   Versions: {', '.join(workflow_info['versions'][:5])}...")
                
            else:
                print(f"⚠️  Failed to get workflow info")
                
        except Exception as e:
            print(f"❌ Error: {e}")
        
        return workflow_info
    
    def download_workflow(self, entry: str, version: str = None) -> Optional[Path]:
        """
        Download a specific workflow from Dockstore
        """
        if version:
            full_entry = f"{entry}:{version}"
            version_str = version
        else:
            full_entry = entry
            version_str = "default"
        
        print(f"\n⬇️  Downloading: {full_entry}")
        
        # Create version-specific subfolder
        safe_entry = entry.replace("/", "_").replace(":", "_").replace(".", "_")
        workflow_dir = self.workspace / safe_entry / version_str
        workflow_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            cmd = [
                "dockstore", "workflow", "download",
                "--entry", full_entry,
                "--descriptor", "all",
                "--output-dir", str(workflow_dir)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=workflow_dir)
            
            if result.returncode == 0:
                # Find .ga file
                ga_files = list(workflow_dir.glob("*.ga"))
                if ga_files:
                    print(f"✅ Downloaded: {ga_files[0]}")
                    return ga_files[0]
                else:
                    print(f"⚠️  No .ga file found in {workflow_dir}")
                    return workflow_dir
            else:
                print(f"❌ Download failed: {result.stderr}")
                return None
                
        except Exception as e:
            print(f"❌ Error: {e}")
            return None
    
    def run_planemo_test(self, workflow_path: Path) -> subprocess.Popen:
        """
        Start planemo test in the background
        Uses --test_output_json to explicitly generate only JSON output
        """
        workflow_dir = workflow_path.parent
        workflow_filename = workflow_path.name
        json_path = workflow_dir / "tool_test_output.json"
        
        # Remove any existing JSON file
        if json_path.exists():
            json_path.unlink()
            print(f"   Removed existing {json_path.name}")
        
        # Use --test_output_json to generate only JSON (no HTML)
        cmd = [
            "planemo", "test",
            workflow_filename,
            "--profile", self.galaxy_profile,
            "--test_output_json", "tool_test_output.json"  # Explicitly JSON only
        ]
        
        print(f"\n🚀 Starting planemo test (JSON output only)")
        print(f"   Directory: {workflow_dir}")
        print(f"   Planemo will create: {json_path.name}")
        print(f"   Command: {' '.join(cmd)}")
        
        try:
            # Start process but don't wait
            process = subprocess.Popen(
                cmd,
                cwd=str(workflow_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            return process
            
        except Exception as e:
            print(f"❌ Failed to start planemo: {e}")
            return None
    
    def wait_for_json_file(self, workflow_dir: Path, timeout_minutes: int = 60) -> Optional[Path]:
        """
        Wait for tool_test_output.json to be generated by Planemo
        With --test_output_json, this should be the only output file
        """
        json_path = workflow_dir / "tool_test_output.json"
        start_time = time.time()
        timeout_seconds = timeout_minutes * 60
        
        print(f"\n⏳ Waiting for Planemo to generate tool_test_output.json...")
        
        while time.time() - start_time < timeout_seconds:
            elapsed = int(time.time() - start_time)
            
            # Check for JSON file
            if json_path.exists():
                # Make sure it's not empty and is valid JSON
                try:
                    # Check file size - should be > 0
                    file_size = json_path.stat().st_size
                    if file_size == 0:
                        print(f"   ⚠️  JSON file exists but is empty - waiting...")
                        time.sleep(2)
                        continue
                    
                    # Read first character to verify it's JSON (starts with {)
                    with open(json_path, 'r') as f:
                        first_char = f.read(1)
                    
                    if first_char == '{':
                        print(f"\n✅ JSON file detected after {elapsed} seconds")
                        print(f"   📊 File: {json_path.name} (size: {file_size} bytes)")
                        
                        # Brief pause to ensure file is fully written
                        time.sleep(2)
                        return json_path
                    else:
                        # File exists but isn't JSON yet - might be still writing
                        print(f"   ⚠️  File exists but content doesn't start with '{{' - waiting...")
                except Exception as e:
                    # File might be locked or not readable yet
                    pass
            
            # Print progress every 30 seconds
            if elapsed % 30 == 0 and elapsed > 0:
                minutes = elapsed // 60
                seconds = elapsed % 60
                print(f"   Still waiting... ({minutes}m {seconds}s)")
            
            time.sleep(5)
        
        print(f"\n⚠️  Timeout after {timeout_minutes} minutes - JSON file not generated")
        return None
    
    def verify_json_file(self, json_path: Path) -> bool:
        """
        Verify that the file is valid JSON
        """
        try:
            with open(json_path, 'r') as f:
                content = f.read()
            
            # Check if it's valid JSON
            json.loads(content)
            return True
        except json.JSONDecodeError as e:
            print(f"   ❌ Invalid JSON: {e}")
            return False
        except Exception as e:
            print(f"   ❌ Error reading file: {e}")
            return False
    
    def parse_missing_tools_from_json(self, json_path: Path, fetch_tool_details: bool = True) -> Tuple[List[str], List[Dict]]:
        """
        Parse tool_test_output.json to extract missing tools
        Also fetch detailed information from ToolShed if BioBlend is available
        
        Returns:
            - List of missing tool URLs
            - List of detailed tool information (if available)
        """
        missing_tools = []
        tool_details = []
        
        if not json_path or not json_path.exists():
            print("❌ No JSON file to parse")
            return missing_tools, tool_details
        
        print(f"\n📖 Reading Planemo's tool_test_output.json...")
        
        try:
            # Read and verify the JSON file
            with open(json_path, 'r') as f:
                content = f.read()
            
            # Verify it's valid JSON
            try:
                test_output = json.loads(content)
                print(f"✅ Successfully parsed JSON file")
            except json.JSONDecodeError as e:
                print(f"❌ Invalid JSON: {e}")
                print(f"   File may be corrupted or incomplete")
                print(f"   First 200 chars: {content[:200]}")
                return missing_tools, tool_details
            
            # Extract missing tools from the JSON structure
            tests = test_output.get('tests', [])
            print(f"   Found {len(tests)} test entries in JSON")
            
            for test_idx, test in enumerate(tests):
                # Look for execution_problem field
                data = test.get('data', {})
                execution_problem = data.get('execution_problem')
                
                if execution_problem:
                    print(f"   Test {test_idx + 1}: Found execution_problem")
                    
                    # Parse the specific error message format
                    if "the following required tools are not installed:" in execution_problem:
                        # Extract the tools part
                        tools_part = execution_problem.split("not installed:")[-1].strip()
                        # Remove trailing quote/parenthesis
                        tools_part = re.sub(r'[")]$', '', tools_part)
                        
                        # Split by comma and extract each tool
                        for tool_entry in tools_part.split(','):
                            tool_entry = tool_entry.strip()
                            if tool_entry:
                                # Extract just the tool ID (before the version)
                                tool_match = re.search(r'(toolshed\.g2\.bx\.psu\.edu[^\s\(]+)', tool_entry)
                                if tool_match:
                                    tool_id = tool_match.group(1)
                                    missing_tools.append(tool_id)
                                    print(f"      Found missing tool: {tool_id}")
                    
                    # Also try to parse JSON within the error message
                    json_match = re.search(r'({.*})', execution_problem)
                    if json_match:
                        try:
                            error_json = json.loads(json_match.group(1))
                            err_msg = error_json.get('err_msg', '')
                            if "not installed" in err_msg:
                                tool_match = re.search(r'(toolshed\.g2\.bx\.psu\.edu[^\s]+)', err_msg)
                                if tool_match:
                                    tool_id = tool_match.group(1)
                                    if tool_id not in missing_tools:
                                        missing_tools.append(tool_id)
                                        print(f"      Found missing tool: {tool_id}")
                        except:
                            pass
            
            # Remove duplicates
            missing_tools = sorted(list(set(missing_tools)))
            
            # Print summary
            if missing_tools:
                print(f"\n❌ Found {len(missing_tools)} missing tools:")
                for i, tool in enumerate(missing_tools, 1):
                    print(f"   {i}. {tool}")
            else:
                print(f"\n✅ No missing tools found")
            
            # Fetch detailed information from ToolShed if requested
            if fetch_tool_details and missing_tools and self.toolshed_info:
                print(f"\n🔍 Fetching detailed information from ToolShed...")
                for i, tool_url in enumerate(missing_tools, 1):
                    print(f"   {i}. Querying: {tool_url}")
                    details = self.toolshed_info.get_tool_details(tool_url)
                    tool_details.append(details)
                    
                    # Print a summary of the details
                    if details.get('error'):
                        print(f"      ⚠️  Error: {details['error']}")
                    else:
                        print(f"      ✅ Owner: {details['owner']}")
                        print(f"      📦 Repository: {details['repository']}")
                        if details.get('latest_revision'):
                            print(f"      🔖 Latest Revision: {details['latest_revision'][:12]}...")
                        if details.get('description'):
                            desc = details['description'][:60]
                            print(f"      📝 Description: {desc}...")
                        if details.get('stars'):
                            print(f"      ⭐ Stars: {details['stars']}")
                print(f"\n✅ Tool information retrieved for {len(missing_tools)} tools")
            
            # Also display test summary
            summary = test_output.get('summary', {})
            if summary:
                print(f"\n📊 Test Summary:")
                print(f"   Total: {summary.get('total', 0)}")
                print(f"   Passed: {summary.get('passed', 0)}")
                print(f"   Failed: {summary.get('failed', 0)}")
                print(f"   Skipped: {summary.get('skipped', 0)}")
            
        except Exception as e:
            print(f"❌ Error parsing JSON: {e}")
        
        return missing_tools, tool_details
    
    def test_galaxy_workflow(self, workflow_path: Path, timeout_minutes: int = 60, 
                            fetch_tool_details: bool = True) -> Tuple[List[str], List[Dict], Dict]:
        """
        Complete test workflow using --test_output_json
        Returns: (missing_tools, tool_details, test_results)
        """
        workflow_dir = workflow_path.parent
        
        print(f"\n{'='*60}")
        print(f"🧪 TESTING: {workflow_path.name}")
        print(f"   Location: {workflow_dir}")
        print(f"{'='*60}")
        
        # Step 1: Start planemo test with --test_output_json
        process = self.run_planemo_test(workflow_path)
        
        if not process:
            return [], [], {}
        
        # Step 2: Wait for JSON file
        json_path = self.wait_for_json_file(workflow_dir, timeout_minutes)
        
        # Step 3: Parse the JSON file
        if json_path:
            # Verify it's actually JSON
            if self.verify_json_file(json_path):
                missing_tools, tool_details = self.parse_missing_tools_from_json(
                    json_path, fetch_tool_details
                )
                
                # Also load full test results
                test_results = {}
                try:
                    with open(json_path, 'r') as f:
                        test_results = json.load(f)
                except:
                    pass
                
                return missing_tools, tool_details, test_results
            else:
                print("❌ JSON file is invalid")
                return [], [], {}
        else:
            print("❌ Planemo did not generate JSON file")
            return [], [], []
    
    def process_workflow_with_versions(self, entry: str, max_versions: Union[int, str] = 3, 
                                       timeout_minutes: int = 60, 
                                       fetch_tool_details: bool = True) -> List[Dict]:
        """
        Process workflow versions
        
        Args:
            entry: Dockstore workflow entry
            max_versions: Either an integer (max number of versions to test) 
                         or "all" to test all versions
            timeout_minutes: Timeout per test in minutes
            fetch_tool_details: Whether to fetch detailed tool info from ToolShed
        """
        print(f"\n{'='*70}")
        print(f"📦 Processing: {entry}")
        print(f"{'='*70}")
        
        # Get versions
        workflow_info = self.get_workflow_versions(entry)
        
        if not workflow_info["versions"]:
            print("❌ No versions found")
            return []
        
        # Determine which versions to process
        if max_versions == "all":
            versions_to_process = workflow_info["versions"]
            print(f"\n🔄 Processing ALL {len(versions_to_process)} versions")
        else:
            versions_to_process = workflow_info["versions"][:max_versions]
            print(f"\n🔄 Processing {len(versions_to_process)} of {len(workflow_info['versions'])} versions")
        
        reports = []
        
        for i, version in enumerate(versions_to_process, 1):
            print(f"\n{'='*60}")
            print(f"📋 [{i}/{len(versions_to_process)}] Version: {version}")
            print(f"{'='*60}")
            
            # Download version
            workflow_path = self.download_workflow(entry, version)
            
            if workflow_path and workflow_path.is_file() and workflow_path.suffix == '.ga':
                # Test the workflow
                missing_tools, tool_details, test_results = self.test_galaxy_workflow(
                    workflow_path, timeout_minutes, fetch_tool_details
                )
                
                # Create report
                report = {
                    "entry": entry,
                    "version": version,
                    "timestamp": datetime.now().isoformat(),
                    "workflow_path": str(workflow_path),
                    "workflow_directory": str(workflow_path.parent),
                    "workflow_info": workflow_info,
                    "galaxy_profile": self.galaxy_profile,
                    "missing_tools": missing_tools,
                    "tool_details": tool_details,  # Now includes ToolShed information
                    "test_results": test_results,
                    "status": "tested"
                }
                
                # Check for JSON file
                json_path = workflow_path.parent / "tool_test_output.json"
                if json_path.exists():
                    report["test_output_json"] = str(json_path)
                    report["test_output_json_size"] = json_path.stat().st_size
                
                reports.append(report)
            else:
                print(f"⚠️  Skipping version {version} - no .ga file found")
            
            # Small delay between downloads
            if i < len(versions_to_process):
                time.sleep(2)
        
        return reports
    
    def batch_process_by_pattern(self, pattern: str, max_workflows: int = 3, 
                                 versions_per_workflow: Union[int, str] = 2,
                                 timeout_minutes: int = 60,
                                 fetch_tool_details: bool = True) -> List[Dict]:
        """
        Search and process multiple workflows
        
        Args:
            pattern: Search pattern
            max_workflows: Maximum number of workflows to process
            versions_per_workflow: Either integer or "all" for versions per workflow
            timeout_minutes: Timeout per test in minutes
            fetch_tool_details: Whether to fetch detailed tool info from ToolShed
        """
        print(f"\n🔎 Searching for: '{pattern}'")
        
        workflows = self.query_dockstore(pattern=pattern)[:max_workflows]
        
        if not workflows:
            print("❌ No workflows found")
            return []
        
        print(f"✅ Found {len(workflows)} workflows")
        
        all_reports = []
        
        for i, workflow in enumerate(workflows, 1):
            print(f"\n{'='*70}")
            print(f"📌 [{i}/{len(workflows)}] Workflow: {workflow['entry']}")
            print(f"{'='*70}")
            
            reports = self.process_workflow_with_versions(
                workflow['entry'], 
                max_versions=versions_per_workflow,
                timeout_minutes=timeout_minutes,
                fetch_tool_details=fetch_tool_details
            )
            all_reports.extend(reports)
        
        return all_reports
    
    def generate_master_report(self, reports: List[Dict]) -> Dict:
        """
        Generate master report with enhanced tool information
        """
        master = {
            "generated": datetime.now().isoformat(),
            "galaxy_profile": self.galaxy_profile,
            "bioblend_available": BIODLEND_AVAILABLE,
            "total_versions_processed": len(reports),
            "unique_workflows": len(set(r["entry"] for r in reports)),
            "workflows_with_missing_tools": 0,
            "all_missing_tools": [],
            "all_tool_details": [],
            "workflow_details": reports,
            "statistics": {
                "total_missing_tools": 0,
                "versions_by_workflow": {}
            }
        }
        
        all_tools = []
        all_details = []
        version_count = {}
        
        for report in reports:
            entry = report["entry"]
            version_count[entry] = version_count.get(entry, 0) + 1
            
            if report.get("missing_tools"):
                master["workflows_with_missing_tools"] += 1
                all_tools.extend(report["missing_tools"])
                master["statistics"]["total_missing_tools"] += len(report["missing_tools"])
                
                # Collect tool details
                if report.get("tool_details"):
                    all_details.extend(report["tool_details"])
        
        master["all_missing_tools"] = sorted(list(set(all_tools)))
        master["unique_missing_tools_count"] = len(master["all_missing_tools"])
        master["all_tool_details"] = all_details
        master["statistics"]["versions_by_workflow"] = version_count
        
        return master
    
    def display_report(self, master_report: Dict):
        """
        Display master report with enhanced tool information
        """
        print("\n" + "="*90)
        print("📊 UNIFIED WORKFLOW AGENT - MASTER REPORT")
        print(f"   Generated: {master_report['generated']}")
        print(f"   Galaxy Profile: {master_report.get('galaxy_profile', 'N/A')}")
        print(f"   BioBlend: {'✅ Available' if master_report.get('bioblend_available') else '❌ Not available'}")
        print("="*90)
        
        print(f"\n📈 SUMMARY:")
        print(f"   Versions processed: {master_report['total_versions_processed']}")
        print(f"   Unique workflows: {master_report['unique_workflows']}")
        print(f"   Workflows with missing tools: {master_report['workflows_with_missing_tools']}")
        print(f"   Unique missing tools: {master_report['unique_missing_tools_count']}")
        print(f"   Total missing tool instances: {master_report['statistics']['total_missing_tools']}")
        
        if master_report['all_missing_tools']:
            print(f"\n❌ ALL MISSING TOOLS:")
            for i, tool in enumerate(master_report['all_missing_tools'], 1):
                print(f"   {i}. {tool}")
            
            # Show detailed tool information if available
            if master_report['all_tool_details']:
                print(f"\n🔧 DETAILED TOOL INFORMATION:")
                for i, details in enumerate(master_report['all_tool_details'], 1):
                    print(f"\n   {i}. {details.get('tool_url', 'Unknown')}")
                    if details.get('error'):
                        print(f"      ⚠️  Error: {details['error']}")
                    else:
                        print(f"      Owner: {details.get('owner', 'N/A')}")
                        print(f"      Repository: {details.get('repository', 'N/A')}")
                        if details.get('latest_revision'):
                            print(f"      Latest Revision: {details['latest_revision']}")
                        if details.get('description'):
                            print(f"      Description: {details['description'][:100]}...")
                        if details.get('stars'):
                            print(f"      Stars: {details['stars']}")
                        if details.get('times_downloaded'):
                            print(f"      Downloads: {details['times_downloaded']}")
        
        print(f"\n📋 DETAILS BY VERSION:")
        for i, report in enumerate(master_report['workflow_details'], 1):
            short_name = report['entry'].split('/')[-1]
            print(f"\n   {i}. {short_name} (v{report['version']})")
            
            missing = len(report.get('missing_tools', []))
            if missing > 0:
                print(f"      Missing: {missing} tools")
                # Show tool details for this version
                if report.get('tool_details'):
                    for j, tool_detail in enumerate(report['tool_details'][:2], 1):
                        tool_name = tool_detail.get('repository', 'Unknown')
                        revision = tool_detail.get('latest_revision', 'N/A')
                        print(f"        {j}. {tool_name} (revision: {revision[:12]}...)")
                    if missing > 2:
                        print(f"        ... and {missing-2} more")
            else:
                print(f"      ✅ No missing tools")
            
            # Show JSON file info
            if report.get('test_output_json'):
                print(f"      📊 JSON: {os.path.basename(report['test_output_json'])} "
                      f"({report.get('test_output_json_size', 0)} bytes)")
        
        print("\n" + "="*90)

def generate_versioned_output_filename(base_output: str, version: str = None, 
                                       workflow_name: str = None) -> str:
    """
    Generate a version-specific output filename
    
    Examples:
        - workflow_agent_report_v1.3.json
        - workflow_agent_report_Assembly-decontamination_v1.3.json
        - workflow_agent_report_all_versions.json (for "all")
        - workflow_agent_report.json (if no version)
    """
    if not version:
        return base_output
    
    # Remove .json extension if present
    if base_output.endswith('.json'):
        base = base_output[:-5]
    else:
        base = base_output
    
    # Create version-specific filename
    if version == "all":
        versioned_output = f"{base}_all_versions.json"
    elif workflow_name:
        # Sanitize workflow name for filename
        safe_name = workflow_name.replace('/', '_').replace(' ', '_')
        versioned_output = f"{base}_{safe_name}_v{version}.json"
    else:
        versioned_output = f"{base}_v{version}.json"
    
    return versioned_output

def parse_versions_per_workflow(value: str) -> Union[int, str]:
    """
    Parse the versions-per-workflow argument
    Returns either an integer or the string "all"
    """
    if value.lower() == "all":
        return "all"
    try:
        return int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid value for --versions-per-workflow: '{value}'. Must be an integer or 'all'")

def main():
    parser = argparse.ArgumentParser(description='Unified Workflow Agent - Uses --test_output_json with BioBlend integration')
    parser.add_argument('--pattern', '-p', help='Search pattern')
    parser.add_argument('--entry', '-e', help='Specific workflow entry')
    parser.add_argument('--version', '-v', help='Specific version')
    parser.add_argument('--profile', '-prof', default='galaxy_profile', 
                       help='Galaxy profile (default: galaxy_profile)')
    parser.add_argument('--timeout', '-t', type=int, default=60,
                       help='Timeout in minutes (default: 60)')
    parser.add_argument('--max-workflows', '-mw', type=int, default=3, 
                       help='Max workflows (default: 3)')
    parser.add_argument('--versions-per-workflow', '-vpw', type=parse_versions_per_workflow, default=2,
                       help='Versions per workflow (use "all" for all versions, or integer for max count)')
    parser.add_argument('--workspace', '-w', default='./workflow_workspace',
                       help='Workspace directory')
    parser.add_argument('--output', '-out', default='workflow_agent_report.json',
                       help='Base output file (will be versioned if version specified)')
    parser.add_argument('--no-tool-details', action='store_true',
                       help='Skip fetching detailed tool information from ToolShed')
    parser.add_argument('--toolshed-url', default='https://toolshed.g2.bx.psu.edu',
                       help='ToolShed URL (default: https://toolshed.g2.bx.psu.edu)')
    
    args = parser.parse_args()
    
    # Check dependencies
    missing = []
    for cmd in ["dockstore", "planemo"]:
        if not subprocess.run(f"which {cmd}", shell=True, capture_output=True).returncode == 0:
            missing.append(cmd)
    
    if missing:
        print("❌ Missing dependencies:", ", ".join(missing))
        sys.exit(1)
    
    # Initialize agent with BioBlend if available
    agent = UnifiedWorkflowAgent(
        workspace_dir=args.workspace, 
        galaxy_profile=args.profile,
        toolshed_url=args.toolshed_url
    )
    
    print("🔧 UNIFIED WORKFLOW AGENT (with BioBlend integration)")
    print(f"   Profile: {args.profile}")
    print(f"   Timeout: {args.timeout} minutes")
    print(f"   Using: --test_output_json (JSON only, no HTML)")
    print(f"   ToolShed: {args.toolshed_url}")
    
    if BIODLEND_AVAILABLE and not args.no_tool_details:
        print(f"   BioBlend: ✅ Available - will fetch tool details")
    elif not BIODLEND_AVAILABLE:
        print(f"   BioBlend: ❌ Not installed - tool details limited")
    else:
        print(f"   BioBlend: ✅ Available but disabled (--no-tool-details)")
    
    if args.versions_per_workflow == "all":
        print(f"   Versions per workflow: ALL")
    else:
        print(f"   Versions per workflow: {args.versions_per_workflow}")
    
    reports = []
    processed_versions = []  # Track versions processed for output filenames
    
    # Determine if we should fetch tool details
    fetch_tool_details = BIODLEND_AVAILABLE and not args.no_tool_details
    
    # Process based on arguments
    if args.entry and args.version:
        print(f"\n📌 Processing: {args.entry}:{args.version}")
        workflow_path = agent.download_workflow(args.entry, args.version)
        
        if workflow_path and workflow_path.is_file() and workflow_path.suffix == '.ga':
            missing_tools, tool_details, test_results = agent.test_galaxy_workflow(
                workflow_path, args.timeout, fetch_tool_details
            )
            
            workflow_info = agent.get_workflow_versions(args.entry)
            
            report = {
                "entry": args.entry,
                "version": args.version,
                "timestamp": datetime.now().isoformat(),
                "workflow_path": str(workflow_path),
                "workflow_info": workflow_info,
                "galaxy_profile": args.profile,
                "missing_tools": missing_tools,
                "tool_details": tool_details,
                "test_results": test_results,
                "status": "tested"
            }
            
            json_path = workflow_path.parent / "tool_test_output.json"
            if json_path.exists():
                report["test_output_json"] = str(json_path)
            
            reports.append(report)
            processed_versions.append({
                "version": args.version,
                "workflow_name": workflow_info.get('entry', args.entry).split('/')[-1]
            })
    
    elif args.entry:
        reports = agent.process_workflow_with_versions(
            args.entry, 
            max_versions=args.versions_per_workflow,
            timeout_minutes=args.timeout,
            fetch_tool_details=fetch_tool_details
        )
        
        # Track versions for output filenames
        for report in reports:
            if report.get('version'):
                workflow_name = report.get('entry', args.entry).split('/')[-1]
                processed_versions.append({
                    "version": report['version'],
                    "workflow_name": workflow_name
                })
    
    elif args.pattern:
        reports = agent.batch_process_by_pattern(
            args.pattern,
            max_workflows=args.max_workflows,
            versions_per_workflow=args.versions_per_workflow,
            timeout_minutes=args.timeout,
            fetch_tool_details=fetch_tool_details
        )
        
        # Track versions for output filenames
        for report in reports:
            if report.get('version'):
                workflow_name = report.get('entry', '').split('/')[-1] if report.get('entry') else 'workflow'
                processed_versions.append({
                    "version": report['version'],
                    "workflow_name": workflow_name
                })
    
    else:
        print("\n🔍 Using example workflow")
        example = "github.com/iwc-workflows/Assembly-decontamination-VGP9/main"
        reports = agent.process_workflow_with_versions(
            example, 
            max_versions=args.versions_per_workflow,
            timeout_minutes=args.timeout,
            fetch_tool_details=fetch_tool_details
        )
        
        # Track versions for output filenames
        for report in reports:
            if report.get('version'):
                workflow_name = report.get('entry', example).split('/')[-1]
                processed_versions.append({
                    "version": report['version'],
                    "workflow_name": workflow_name
                })
    
    # Generate version-specific output files
    if reports:
        # Generate master report
        master = agent.generate_master_report(reports)
        agent.display_report(master)
        
        # Save version-specific files
        saved_files = []
        
        # Check if we processed "all" versions
        is_all_versions = (args.versions_per_workflow == "all")
        
        if len(reports) == 1 and processed_versions:
            # Single version - create one versioned file
            version_info = processed_versions[0]
            output_filename = generate_versioned_output_filename(
                args.output, 
                version_info['version'],
                version_info['workflow_name']
            )
            with open(output_filename, 'w') as f:
                json.dump(master, f, indent=2)
            saved_files.append(output_filename)
            print(f"\n💾 Version-specific report saved to: {output_filename}")
        
        elif len(reports) > 1 and processed_versions:
            # Multiple versions - create both master and individual version files
            
            # Determine master filename
            if is_all_versions:
                master_filename = generate_versioned_output_filename(
                    args.output,
                    "all",
                    processed_versions[0]['workflow_name'] if processed_versions else None
                )
            else:
                versions_str = '_'.join([v['version'].replace('.', '_') for v in processed_versions[:5]])
                if len(processed_versions) > 5:
                    versions_str += f"_plus_{len(processed_versions)-5}_more"
                
                master_filename = generate_versioned_output_filename(
                    args.output,
                    versions_str,
                    processed_versions[0]['workflow_name'] if processed_versions else None
                )
            
            with open(master_filename, 'w') as f:
                json.dump(master, f, indent=2)
            saved_files.append(master_filename)
            print(f"\n💾 Master report saved to: {master_filename}")
            
            # Also save individual reports for each version
            for i, report in enumerate(reports):
                version = report.get('version', f'version_{i+1}')
                workflow_name = report.get('entry', '').split('/')[-1] if report.get('entry') else 'workflow'
                
                version_filename = generate_versioned_output_filename(
                    args.output,
                    version,
                    workflow_name
                )
                
                # Create individual version report
                version_report = {
                    "generated": datetime.now().isoformat(),
                    "galaxy_profile": args.profile,
                    "bioblend_available": BIODLEND_AVAILABLE,
                    "version_info": {
                        "workflow": report.get('entry'),
                        "version": version,
                        "workflow_name": workflow_name
                    },
                    "missing_tools": report.get('missing_tools', []),
                    "tool_details": report.get('tool_details', []),
                    "test_results": report.get('test_results', {}),
                    "workflow_info": report.get('workflow_info', {}),
                    "status": report.get('status', 'unknown')
                }
                
                with open(version_filename, 'w') as f:
                    json.dump(version_report, f, indent=2)
                saved_files.append(version_filename)
                
                # Only print first few to avoid clutter
                if i < 5:
                    print(f"   Individual version report: {version_filename}")
                elif i == 5:
                    print(f"   ... and {len(reports) - 5} more reports")
            
            if len(reports) > 5:
                print(f"   Total: {len(reports)} individual version reports generated")
        else:
            # Fallback - save master report with default name
            with open(args.output, 'w') as f:
                json.dump(master, f, indent=2)
            saved_files.append(args.output)
            print(f"\n💾 Report saved to: {args.output}")
        
        print(f"\n📁 Generated {len(saved_files)} report file(s):")
        for f in saved_files[:10]:  # Show first 10
            print(f"   - {f}")
        if len(saved_files) > 10:
            print(f"   ... and {len(saved_files) - 10} more")
    else:
        print("\n❌ No workflows processed")

if __name__ == "__main__":
    main()