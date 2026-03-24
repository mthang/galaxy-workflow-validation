#!/usr/bin/env python3
"""
Unified Workflow Agent - Properly handles both JSON and HTML outputs from Planemo
Waits specifically for tool_test_output.json, not tool_test_output.html
"""

import subprocess
import json
import sys
import os
from pathlib import Path
import re
from typing import List, Dict, Optional, Tuple, Any
import time
import argparse
from datetime import datetime

# Test with default profile (galaxy_profile)
#python workflow_agent_fixed_v7.py --entry "github.com/iwc-workflows/Assembly-decontamination-VGP9/main" --version "v1.3"


class UnifiedWorkflowAgent:
    def __init__(self, workspace_dir: str = "./workflow_workspace", galaxy_profile: str = "galaxy_profile"):
        self.workspace = Path(workspace_dir)
        self.workspace.mkdir(exist_ok=True)
        self.galaxy_profile = galaxy_profile
        self.downloaded_workflows = []
        
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
        Planemo will generate TWO files in the same directory:
        - tool_test_output.json (JSON format - what we want)
        - tool_test_output.html (HTML report - ignore)
        """
        workflow_dir = workflow_path.parent
        workflow_filename = workflow_path.name
        json_path = workflow_dir / "tool_test_output.json"
        html_path = workflow_dir / "tool_test_output.html"
        
        # Remove any existing output files
        if json_path.exists():
            json_path.unlink()
            print(f"   Removed existing {json_path.name}")
        if html_path.exists():
            html_path.unlink()
            print(f"   Removed existing {html_path.name}")
        
        cmd = [
            "planemo", "test",
            workflow_filename,
            "--profile", self.galaxy_profile,
            "--test_output_json", "tool_test_output.json"  # This creates both .json and .html
        ]
        
        print(f"\n🚀 Starting planemo test")
        print(f"   Directory: {workflow_dir}")
        print(f"   Planemo will create:")
        print(f"     - {json_path.name} (JSON data - for parsing)")
        print(f"     - {html_path.name} (HTML report - ignored)")
        
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
        Wait specifically for tool_test_output.json to be generated
        Ignores tool_test_output.html even if it appears first
        """
        json_path = workflow_dir / "tool_test_output.json"
        html_path = workflow_dir / "tool_test_output.html"
        start_time = time.time()
        timeout_seconds = timeout_minutes * 60
        
        print(f"\n⏳ Waiting for Planemo to generate tool_test_output.json...")
        print(f"   (HTML file may appear first - we're waiting for JSON)")
        
        json_detected = False
        html_detected = False
        
        while time.time() - start_time < timeout_seconds:
            elapsed = int(time.time() - start_time)
            
            # Check for HTML file (just for information)
            if not html_detected and html_path.exists():
                html_detected = True
                html_size = html_path.stat().st_size
                print(f"   📄 HTML report generated after {elapsed}s (size: {html_size} bytes)")
                print(f"   ⏳ Still waiting for JSON file...")
            
            # Check for JSON file - this is what we really want
            if json_path.exists():
                # Make sure it's not empty and is valid JSON
                try:
                    # Read first character to verify it's JSON (starts with {)
                    with open(json_path, 'r') as f:
                        first_char = f.read(1)
                    
                    if first_char == '{':
                        file_size = json_path.stat().st_size
                        print(f"   ✅ JSON file detected after {elapsed}s")
                        print(f"   📊 File: {json_path.name} (size: {file_size} bytes)")
                        
                        # Brief pause to ensure file is fully written
                        time.sleep(2)
                        return json_path
                    else:
                        # File exists but isn't JSON yet - might be still writing
                        print(f"   ⚠️  JSON file exists but content doesn't start with '{{' - waiting...")
                except Exception as e:
                    # File might be locked or not readable yet
                    pass
            
            # Print progress every 30 seconds
            if elapsed % 30 == 0 and elapsed > 0 and not json_detected:
                minutes = elapsed // 60
                seconds = elapsed % 60
                status = f"{minutes}m {seconds}s"
                if html_detected:
                    print(f"   Still waiting for JSON... ({status}) - HTML ready")
                else:
                    print(f"   Still waiting... ({status}) - no files yet")
            
            time.sleep(5)
        
        # Check one last time
        if json_path.exists():
            try:
                with open(json_path, 'r') as f:
                    first_char = f.read(1)
                if first_char == '{':
                    print(f"✅ JSON file found at timeout")
                    return json_path
            except:
                pass
        
        print(f"\n⚠️  Timeout after {timeout_minutes} minutes - JSON file not generated")
        if html_path.exists():
            print(f"   Note: HTML file was generated but JSON is missing")
            print(f"   This may indicate a test failure or Planemo configuration issue")
        
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
    
    def parse_missing_tools_from_json(self, json_path: Path) -> List[str]:
        """
        Parse tool_test_output.json to extract missing tools
        This file is generated by Planemo, we just read it
        """
        missing_tools = []
        
        if not json_path or not json_path.exists():
            print("❌ No JSON file to parse")
            return missing_tools
        
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
                return missing_tools
            
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
                                    missing_tools.append(tool_match.group(1))
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
        
        return missing_tools
    
    def test_galaxy_workflow(self, workflow_path: Path, timeout_minutes: int = 60) -> Tuple[List[str], Dict]:
        """
        Complete test workflow:
        1. Start planemo test
        2. Wait specifically for tool_test_output.json (not the HTML file)
        3. Read and parse the JSON file
        """
        workflow_dir = workflow_path.parent
        
        print(f"\n{'='*60}")
        print(f"🧪 TESTING: {workflow_path.name}")
        print(f"   Location: {workflow_dir}")
        print(f"{'='*60}")
        
        # Step 1: Start planemo test
        process = self.run_planemo_test(workflow_path)
        
        if not process:
            return [], {}
        
        # Step 2: Wait for JSON file (ignore HTML)
        json_path = self.wait_for_json_file(workflow_dir, timeout_minutes)
        
        # Step 3: Parse the JSON file that Planemo created
        if json_path:
            # Verify it's actually JSON
            if self.verify_json_file(json_path):
                missing_tools = self.parse_missing_tools_from_json(json_path)
                
                # Also load full test results
                test_results = {}
                try:
                    with open(json_path, 'r') as f:
                        test_results = json.load(f)
                except:
                    pass
                
                return missing_tools, test_results
            else:
                print("❌ JSON file is invalid")
                return [], {}
        else:
            print("❌ Planemo did not generate JSON file")
            return [], {}
    
    def process_workflow_with_versions(self, entry: str, max_versions: int = 3, 
                                       timeout_minutes: int = 60) -> List[Dict]:
        """
        Process workflow versions
        """
        print(f"\n{'='*70}")
        print(f"📦 Processing: {entry}")
        print(f"{'='*70}")
        
        # Get versions
        workflow_info = self.get_workflow_versions(entry)
        
        if not workflow_info["versions"]:
            print("❌ No versions found")
            return []
        
        reports = []
        versions_to_process = workflow_info["versions"][:max_versions]
        
        print(f"\n🔄 Processing {len(versions_to_process)} versions")
        
        for i, version in enumerate(versions_to_process, 1):
            print(f"\n{'='*60}")
            print(f"📋 [{i}/{len(versions_to_process)}] Version: {version}")
            print(f"{'='*60}")
            
            # Download version
            workflow_path = self.download_workflow(entry, version)
            
            if workflow_path and workflow_path.is_file() and workflow_path.suffix == '.ga':
                # Test the workflow
                missing_tools, test_results = self.test_galaxy_workflow(workflow_path, timeout_minutes)
                
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
                    "test_results": test_results,
                    "status": "tested"
                }
                
                # Check for JSON and HTML files
                json_path = workflow_path.parent / "tool_test_output.json"
                html_path = workflow_path.parent / "tool_test_output.html"
                
                if json_path.exists():
                    report["test_output_json"] = str(json_path)
                    report["test_output_json_size"] = json_path.stat().st_size
                
                if html_path.exists():
                    report["test_output_html"] = str(html_path)
                    report["test_output_html_size"] = html_path.stat().st_size
                
                reports.append(report)
            
            time.sleep(2)
        
        return reports
    
    def batch_process_by_pattern(self, pattern: str, max_workflows: int = 3, 
                                 versions_per_workflow: int = 2,
                                 timeout_minutes: int = 60) -> List[Dict]:
        """
        Search and process multiple workflows
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
                timeout_minutes=timeout_minutes
            )
            all_reports.extend(reports)
        
        return all_reports
    
    def generate_master_report(self, reports: List[Dict]) -> Dict:
        """
        Generate master report
        """
        master = {
            "generated": datetime.now().isoformat(),
            "galaxy_profile": self.galaxy_profile,
            "total_versions_processed": len(reports),
            "unique_workflows": len(set(r["entry"] for r in reports)),
            "workflows_with_missing_tools": 0,
            "all_missing_tools": [],
            "workflow_details": reports,
            "statistics": {
                "total_missing_tools": 0,
                "versions_by_workflow": {}
            }
        }
        
        all_tools = []
        version_count = {}
        
        for report in reports:
            entry = report["entry"]
            version_count[entry] = version_count.get(entry, 0) + 1
            
            if report.get("missing_tools"):
                master["workflows_with_missing_tools"] += 1
                all_tools.extend(report["missing_tools"])
                master["statistics"]["total_missing_tools"] += len(report["missing_tools"])
        
        master["all_missing_tools"] = sorted(list(set(all_tools)))
        master["unique_missing_tools_count"] = len(master["all_missing_tools"])
        master["statistics"]["versions_by_workflow"] = version_count
        
        return master
    
    def display_report(self, master_report: Dict):
        """
        Display master report
        """
        print("\n" + "="*90)
        print("📊 UNIFIED WORKFLOW AGENT - MASTER REPORT")
        print(f"   Generated: {master_report['generated']}")
        print(f"   Galaxy Profile: {master_report.get('galaxy_profile', 'N/A')}")
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
        
        print(f"\n📋 DETAILS:")
        for i, report in enumerate(master_report['workflow_details'], 1):
            short_name = report['entry'].split('/')[-1]
            print(f"\n   {i}. {short_name} (v{report['version']})")
            
            missing = len(report.get('missing_tools', []))
            if missing > 0:
                print(f"      Missing: {missing} tools")
                for j, tool in enumerate(report['missing_tools'][:2], 1):
                    print(f"        {j}. {tool}")
                if missing > 2:
                    print(f"        ... and {missing-2} more")
            else:
                print(f"      ✅ No missing tools")
            
            # Show output files
            if report.get('test_output_json'):
                print(f"      📊 JSON: {os.path.basename(report['test_output_json'])} "
                      f"({report.get('test_output_json_size', 0)} bytes)")
            if report.get('test_output_html'):
                print(f"      📄 HTML: {os.path.basename(report['test_output_html'])} "
                      f"({report.get('test_output_html_size', 0)} bytes)")
        
        print("\n" + "="*90)

def main():
    parser = argparse.ArgumentParser(description='Unified Workflow Agent')
    parser.add_argument('--pattern', '-p', help='Search pattern')
    parser.add_argument('--entry', '-e', help='Specific workflow entry')
    parser.add_argument('--version', '-v', help='Specific version')
    parser.add_argument('--profile', '-prof', default='galaxy_profile', 
                       help='Galaxy profile (default: galaxy_profile)')
    parser.add_argument('--timeout', '-t', type=int, default=60,
                       help='Timeout in minutes (default: 60)')
    parser.add_argument('--max-workflows', '-mw', type=int, default=3, 
                       help='Max workflows (default: 3)')
    parser.add_argument('--versions-per-workflow', '-vpw', type=int, default=2,
                       help='Versions per workflow (default: 2)')
    parser.add_argument('--workspace', '-w', default='./workflow_workspace',
                       help='Workspace directory')
    parser.add_argument('--output', '-out', default='workflow_agent_report.json',
                       help='Output file')
    
    args = parser.parse_args()
    
    # Check dependencies
    missing = []
    for cmd in ["dockstore", "planemo"]:
        if not subprocess.run(f"which {cmd}", shell=True, capture_output=True).returncode == 0:
            missing.append(cmd)
    
    if missing:
        print("❌ Missing dependencies:", ", ".join(missing))
        sys.exit(1)
    
    # Initialize agent
    agent = UnifiedWorkflowAgent(
        workspace_dir=args.workspace, 
        galaxy_profile=args.profile
    )
    
    print("🔧 UNIFIED WORKFLOW AGENT")
    print(f"   Profile: {args.profile}")
    print(f"   Timeout: {args.timeout} minutes")
    
    reports = []
    
    # Process based on arguments
    if args.entry and args.version:
        print(f"\n📌 Processing: {args.entry}:{args.version}")
        workflow_path = agent.download_workflow(args.entry, args.version)
        
        if workflow_path and workflow_path.is_file() and workflow_path.suffix == '.ga':
            missing_tools, test_results = agent.test_galaxy_workflow(workflow_path, args.timeout)
            
            workflow_info = agent.get_workflow_versions(args.entry)
            
            report = {
                "entry": args.entry,
                "version": args.version,
                "timestamp": datetime.now().isoformat(),
                "workflow_path": str(workflow_path),
                "workflow_info": workflow_info,
                "galaxy_profile": args.profile,
                "missing_tools": missing_tools,
                "test_results": test_results,
                "status": "tested"
            }
            
            json_path = workflow_path.parent / "tool_test_output.json"
            if json_path.exists():
                report["test_output_json"] = str(json_path)
            
            html_path = workflow_path.parent / "tool_test_output.html"
            if html_path.exists():
                report["test_output_html"] = str(html_path)
            
            reports.append(report)
    
    elif args.entry:
        reports = agent.process_workflow_with_versions(
            args.entry, 
            max_versions=args.versions_per_workflow,
            timeout_minutes=args.timeout
        )
    
    elif args.pattern:
        reports = agent.batch_process_by_pattern(
            args.pattern,
            max_workflows=args.max_workflows,
            versions_per_workflow=args.versions_per_workflow,
            timeout_minutes=args.timeout
        )
    
    else:
        print("\n🔍 Using example workflow")
        example = "github.com/iwc-workflows/Assembly-decontamination-VGP9/main"
        reports = agent.process_workflow_with_versions(
            example, 
            max_versions=2,
            timeout_minutes=args.timeout
        )
    
    if reports:
        master = agent.generate_master_report(reports)
        agent.display_report(master)
        
        with open(args.output, 'w') as f:
            json.dump(master, f, indent=2)
        print(f"\n💾 Report saved to: {args.output}")
    else:
        print("\n❌ No workflows processed")

if __name__ == "__main__":
    main()
