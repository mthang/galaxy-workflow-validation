"""Reporting utilities for Galaxy Workflow Checker."""

import json
import csv
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

from ..utils.config_loader import get_galaxy_friendly_name


# ==================== Original Functions ====================

def galaxy_instance_name(url: str, config: dict = None) -> str:
    """Return a friendly name for a Galaxy URL, or the URL itself if unknown."""
    if config:
        return get_galaxy_friendly_name(config, url)
    host = url.rstrip("/").split("//")[-1].split("/")[0]
    names = {
        "usegalaxy.org.au": "Galaxy Australia",
        "genome.usegalaxy.org.au": "Galaxy Australia",
        "usegalaxy.org": "Galaxy Main",
        "usegalaxy.eu": "Galaxy Europe",
    }
    return names.get(host, url)


def generate_report(results: List[Dict], galaxy_url: str, profile: str) -> Dict:
    """Generate a summary report from analysis results."""
    missing_tools = sorted({
        t["id"] for r in results for t in r.get("tool_statuses", [])
        if t.get("status") == "missing"
    })
    mismatch_tools = sorted({
        t["id"] for r in results for t in r.get("tool_statuses", [])
        if t.get("status") == "version_mismatch"
    })

    return {
        "generated": datetime.now().isoformat(),
        "galaxy_url": galaxy_url,
        "profile": profile,
        "strict_version_matching": True,
        "total_versions_checked": len(results),
        "unique_workflows": len({r.get("workflow_id", "") for r in results if r.get("workflow_id")}),
        "versions_ready": sum(1 for r in results if r.get("workflow_status") == "ready"),
        "versions_version_mismatch": sum(
            1 for r in results if r.get("workflow_status") == "version_mismatch"
        ),
        "versions_missing_tool": sum(
            1 for r in results if r.get("workflow_status") == "missing_tool"
        ),
        "versions_structural_error": sum(
            1 for r in results if r.get("workflow_status") == "structural_error"
        ),
        "versions_wiring_issues_only": sum(
            1 for r in results if r.get("workflow_status") == "wiring_issues"
        ),
        "versions_no_toolshed_tools": sum(
            1 for r in results if r.get("workflow_status") == "no_toolshed_tools"
        ),
        "versions_with_wiring_warnings": sum(
            1 for r in results if r.get("wiring_issues")
        ),
        "unique_missing_tools": missing_tools,
        "unique_missing_tools_count": len(missing_tools),
        "unique_mismatched_tools": mismatch_tools,
        "unique_mismatched_tools_count": len(mismatch_tools),
        "results": results,
    }


def write_text_report(report: Dict, path: str, config: dict = None):
    """Write a plain-text aligned table report."""
    lines = []
    lines.append("Galaxy Workflow Tool Checker (strict version matching)")
    lines.append(f"Generated : {report['generated']}")
    lines.append(f"Galaxy    : {report['galaxy_url']}")
    lines.append(f"Profile   : {report['profile']}")
    lines.append("")
    lines.append("Summary")
    lines.append("-" * 40)
    lines.append(f"Versions checked              : {report['total_versions_checked']}")
    lines.append(f"Unique workflows              : {report['unique_workflows']}")
    lines.append(f"Ready to run (all exact)      : {report['versions_ready']}")
    lines.append(f"Structural errors             : {report['versions_structural_error']}")
    lines.append(f"Wiring warnings only          : {report['versions_wiring_issues_only']}")
    lines.append(f"No ToolShed tools found       : {report['versions_no_toolshed_tools']}")
    lines.append(f"Blocked by version mismatch   : {report['versions_version_mismatch']}")
    lines.append(f"Blocked by missing tool       : {report['versions_missing_tool']}")
    lines.append(f"(Any wiring warnings)         : {report['versions_with_wiring_warnings']}")
    lines.append(f"Unique mismatched tools       : {report['unique_mismatched_tools_count']}")
    lines.append(f"Unique missing tools          : {report['unique_missing_tools_count']}")
    lines.append("")

    results = report["results"]
    if not results:
        lines.append("No results.")
    else:
        col_name = max((len(str(r.get("workflow_name", ""))) for r in results), default=20)
        col_name = max(col_name, len("Workflow"))
        col_src = max((len(str(r.get("source", ""))) for r in results), default=10)
        col_src = max(col_src, len("Source"))
        col_ver = max((len(str(r.get("version", ""))) for r in results), default=9)
        col_ver = max(col_ver, len("Version"))
        col_status = max((len(r.get("workflow_status", "")) for r in results), default=10)
        col_status = max(col_status, len("Status"))

        lines.append("Results")
        header = (f"{'Workflow':<{col_name}}  {'Source':<{col_src}}  "
                  f"{'Version':<{col_ver}}  "
                  f"{'Status':<{col_status}}  "
                  f"{'Tools':>5}  {'Exact':>5}  {'Mismatch':>8}  {'Missing':>7}  "
                  f"{'Wire':>4}  URL")
        lines.append("-" * (len(header) + 5))
        lines.append(header)
        lines.append("-" * (len(header) + 5))

        for r in results:
            lines.append(
                f"{str(r.get('workflow_name', '')):<{col_name}}  "
                f"{str(r.get('source', '')):<{col_src}}  "
                f"{str(r.get('version', '')):<{col_ver}}  "
                f"{r.get('workflow_status', ''):<{col_status}}  "
                f"{r.get('total_tools', 0):>5}  "
                f"{r.get('n_exact', 0):>5}  "
                f"{r.get('n_version_mismatch', 0):>8}  "
                f"{r.get('n_missing', 0):>7}  "
                f"{r.get('n_wiring_issues', 0):>4}  "
                f"{r.get('workflow_url', '')}"
            )

        lines.append("")

        # Per-workflow detail for non-ready versions
        non_ready = [r for r in results if r.get("workflow_status") != "ready"]
        if non_ready:
            lines.append("Blocker / issue detail")
            lines.append("-" * 40)
            galaxy_name = galaxy_instance_name(report.get("galaxy_url", ""), config)

            for r in non_ready:
                lines.append(f"{r.get('workflow_name', '')} ({r.get('source', '')}, {r.get('version', '')}) "
                             f"[{r.get('workflow_status', '')}]")

                # Structural issues
                for issue in r.get("structural_issues", []):
                    lines.append(f"  STRUCTURAL  [{issue['severity']}] {issue['message']}")

                # No ToolShed tools found
                if r.get("workflow_status") == "no_toolshed_tools":
                    lines.append("  INFO  No ToolShed tools found — workflow may use only "
                                 "built-in Galaxy tools, or tool_id fields may be missing.")

                # Tool issues
                for t in r.get("tool_statuses", []):
                    src_tag = f" [{t.get('source', 'parent')}]" if t.get("source", "parent") != "parent" else ""

                    if t.get("status") == "version_mismatch":
                        avail = ", ".join(t.get("available_versions", []))
                        direction = t.get("version_direction", "")

                        if direction == "installed older":
                            dir_note = f"only older versions available on {galaxy_name}"
                        elif direction == "installed newer":
                            dir_note = f"only newer versions available on {galaxy_name}"
                        elif direction == "mixed":
                            dir_note = f"older and newer versions available on {galaxy_name}, but not this exact version"
                        else:
                            dir_note = f"exact version not available on {galaxy_name}"

                        lines.append(f"  MISMATCH{src_tag}  {t['base']}")
                        lines.append(f"    {galaxy_name} doesn't have the tool version specified in the workflow")
                        lines.append(f"    Workflow wants : {t['version']}")
                        lines.append(f"    {galaxy_name} has  : {avail} ({dir_note})")
                        lines.append("")

                    elif t.get("status") == "missing":
                        lines.append(f"  MISSING{src_tag}   {t['id']}")
                        lines.append("")

                # Wiring issues
                for w in r.get("wiring_issues", []):
                    src_tag = f" [{w.get('source', 'parent')}]" if w.get("source", "parent") != "parent" else ""
                    lines.append(f"  WIRING{src_tag}    [{w['severity']}] {w['message']}")

                lines.append("")

        if report.get("unique_mismatched_tools"):
            lines.append("All unique mismatched tool IDs (version not installed)")
            lines.append("-" * 40)
            for i, t in enumerate(report["unique_mismatched_tools"], 1):
                lines.append(f"  {i:>3}. {t}")
            lines.append("")

        if report.get("unique_missing_tools"):
            lines.append("All unique missing tool IDs (base not installed)")
            lines.append("-" * 40)
            for i, t in enumerate(report["unique_missing_tools"], 1):
                lines.append(f"  {i:>3}. {t}")
            lines.append("")

        lines.append(
            "Note: wiring issues are reported as WARN — without querying the\n"
            "Galaxy tool XML the checker cannot confirm whether unconnected\n"
            "inputs are required or optional."
        )
        lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def display_summary(report: Dict):
    """Print a brief summary to stdout."""
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY (strict version matching)")
    print(f"  Versions checked              : {report['total_versions_checked']}")
    print(f"  Unique workflows              : {report['unique_workflows']}")
    print(f"  Ready to run (all exact)      : {report['versions_ready']}")
    print(f"  Structural errors             : {report['versions_structural_error']}")
    print(f"  Wiring warnings only          : {report['versions_wiring_issues_only']}")
    print(f"  No ToolShed tools found       : {report['versions_no_toolshed_tools']}")
    print(f"  Blocked by version mismatch   : {report['versions_version_mismatch']}")
    print(f"  Blocked by missing tool       : {report['versions_missing_tool']}")
    print(f"  (Any wiring warnings)         : {report['versions_with_wiring_warnings']}")
    print(f"  Unique mismatched tools       : {report['unique_mismatched_tools_count']}")
    print(f"  Unique missing tools          : {report['unique_missing_tools_count']}")
    print("=" * 60)


# ==================== New Functions from the Script ====================

def generate_html_report(report: Dict, output_path: str):
    """Generate an HTML report from the report data."""
    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Galaxy Workflow Tool Checker Report</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            h1, h2 {{ color: #2c3e50; }}
            .summary {{ background: #ecf0f1; padding: 15px; border-radius: 5px; }}
            .ready {{ color: green; }}
            .error {{ color: red; }}
            .warning {{ color: orange; }}
            table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background: #3498db; color: white; }}
            tr:nth-child(even) {{ background: #f2f2f2; }}
            .tool-missing {{ background: #ffcccc; }}
            .tool-mismatch {{ background: #ffffcc; }}
            .tool-exact {{ background: #ccffcc; }}
        </style>
    </head>
    <body>
        <h1>Galaxy Workflow Tool Checker Report</h1>
        <div class="summary">
            <p><strong>Generated:</strong> {generated}</p>
            <p><strong>Galaxy URL:</strong> {galaxy_url}</p>
            <p><strong>Profile:</strong> {profile}</p>
            <p><strong>Total versions checked:</strong> {total_versions_checked}</p>
            <p><strong>Ready to run:</strong> <span class="ready">{versions_ready}</span></p>
            <p><strong>Version mismatches:</strong> <span class="warning">{versions_version_mismatch}</span></p>
            <p><strong>Missing tools:</strong> <span class="error">{versions_missing_tool}</span></p>
        </div>
        <h2>Detailed Results</h2>
        <table>
            <tr>
                <th>Workflow</th>
                <th>Source</th>
                <th>Version</th>
                <th>Status</th>
                <th>Tools</th>
                <th>Exact</th>
                <th>Mismatch</th>
                <th>Missing</th>
                <th>Wiring</th>
            </tr>
            {rows}
        </table>
        <h2>Missing Tools Summary</h2>
        <ul>
            {missing_tools}
        </ul>
        <h2>Version Mismatch Summary</h2>
        <ul>
            {mismatch_tools}
        </ul>
    </body>
    </html>
    """

    rows = []
    for r in report.get('results', []):
        status_class = {
            'ready': 'ready',
            'version_mismatch': 'warning',
            'missing_tool': 'error',
            'structural_error': 'error',
            'wiring_issues': 'warning',
            'no_toolshed_tools': 'warning'
        }.get(r.get('workflow_status', ''), '')
        rows.append(f"""
            <tr>
                <td>{r.get('workflow_name', '')}</td>
                <td>{r.get('source', '')}</td>
                <td>{r.get('version', '')}</td>
                <td class="{status_class}">{r.get('workflow_status', '')}</td>
                <td>{r.get('total_tools', 0)}</td>
                <td>{r.get('n_exact', 0)}</td>
                <td>{r.get('n_version_mismatch', 0)}</td>
                <td>{r.get('n_missing', 0)}</td>
                <td>{r.get('n_wiring_issues', 0)}</td>
            </tr>
        """)

    missing_tools = '\n'.join(f'<li>{t}</li>' for t in report.get('unique_missing_tools', []))
    mismatch_tools = '\n'.join(f'<li>{t}</li>' for t in report.get('unique_mismatched_tools', []))

    html = html_template.format(
        generated=report.get('generated', ''),
        galaxy_url=report.get('galaxy_url', ''),
        profile=report.get('profile', ''),
        total_versions_checked=report.get('total_versions_checked', 0),
        versions_ready=report.get('versions_ready', 0),
        versions_version_mismatch=report.get('versions_version_mismatch', 0),
        versions_missing_tool=report.get('versions_missing_tool', 0),
        rows='\n'.join(rows),
        missing_tools=missing_tools or '<li>No missing tools</li>',
        mismatch_tools=mismatch_tools or '<li>No version mismatches</li>'
    )

    with open(output_path, 'w') as f:
        f.write(html)


def export_tool_issues_to_csv(report: Dict, output_path: str):
    """Export tool issues (missing and mismatched) to CSV."""
    fieldnames = ['workflow', 'source', 'version', 'tool_id', 'status', 'available_versions']
    rows = []

    for r in report.get('results', []):
        for t in r.get('tool_statuses', []):
            if t.get('status') in ('missing', 'version_mismatch'):
                rows.append({
                    'workflow': r.get('workflow_name', ''),
                    'source': r.get('source', ''),
                    'version': r.get('version', ''),
                    'tool_id': t.get('id', ''),
                    'status': t.get('status', ''),
                    'available_versions': ', '.join(t.get('available_versions', []))
                })

    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def generate_installation_script(tool_ids: List[str], galaxy_url: str) -> str:
    """Generate a shell script to install missing tools via bioconda or Galaxy."""
    script = f"""#!/bin/bash
# Galaxy tool installation script
# Generated for Galaxy instance: {galaxy_url}
# Install missing tools using bioconda (recommended) or manually via Galaxy.

echo "Installing missing tools for Galaxy instance: {galaxy_url}"

# Option 1: Use bioconda (if Galaxy uses bioconda channels)
# conda install -c bioconda -c conda-forge \\
"""
    for tool in tool_ids:
        # Extract tool name from tool ID (last part)
        tool_name = tool.split('/')[-1] if '/' in tool else tool
        script += f"    {tool_name} \\\n"
    script += "    # Add more tools as needed\n"

    script += f"""
# Option 2: Use Galaxy's tool installation via API (requires admin rights)
# Use planemo or galaxy-tool-install to install from ToolShed
# Example: planemo tool_install --galaxy_url {galaxy_url} --api_key <key> --tool_id {tool_ids[0] if tool_ids else '...'}

echo "Script complete. Please review and install tools manually if bioconda is not available."
"""
    return script


def compare_workflows(results: List[Dict]) -> Dict:
    """Compare tool requirements across workflows."""
    comparison = {
        'total_workflows': len(results),
        'tool_usage': {},
        'workflows_by_tool': {}
    }

    all_tools = set()
    for r in results:
        wf_name = r.get('workflow_name', '')
        for t in r.get('tool_statuses', []):
            tool_id = t.get('id', '')
            if tool_id:
                all_tools.add(tool_id)
                comparison['tool_usage'][tool_id] = comparison['tool_usage'].get(tool_id, 0) + 1
                comparison['workflows_by_tool'].setdefault(tool_id, []).append(wf_name)

    # Sort by usage
    comparison['tool_usage'] = dict(sorted(comparison['tool_usage'].items(), key=lambda x: x[1], reverse=True))
    return comparison
