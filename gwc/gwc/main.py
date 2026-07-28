#!/usr/bin/env python3
"""
Galaxy Workflow Tool Checker - Main Entry Point

Commands:
  check   – Validate workflows against a Galaxy instance
  list    – List published workflows on a Galaxy instance
  hub     – Interact with WorkflowHub REST API (metadata, projects, RO‑Crate)
"""

import sys
import os
import json
import logging
import argparse
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime
import time

# Import internal modules
from .cli.parser import parse_args, parse_version_spec
from .utils.config_loader import load_config, get_skip_types
from .utils.reporting import (
    generate_report, write_text_report, display_summary,
    generate_html_report, export_tool_issues_to_csv,
    generate_installation_script, compare_workflows
)
from .services.galaxy_client import GalaxyClient
from .services.workflow_registry import WorkflowRegistry
from .core.processor import (
    process_workflow_spec,
    process_workflows_parallel,
    analyze_workflow
)
from .models.workflow_spec import WorkflowSpec
from .lister import GalaxyWorkflowLister
from .services.workflowhub_rest import WorkflowHubREST

# Setup logging
logger = logging.getLogger(__name__)


def setup_logging(level: int = logging.INFO, log_file: Optional[str] = None) -> None:
    """Configure logging with console and optional file handler."""
    handlers = [logging.StreamHandler()]
    if log_file:
        try:
            handlers.append(logging.FileHandler(log_file))
        except OSError as e:
            logger.warning(f"Could not create log file {log_file}: {e}")

    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers
    )


# -----------------------------------------------------------------------------
# LIST COMMAND HANDLER
# -----------------------------------------------------------------------------

def handle_list_command(args: argparse.Namespace) -> None:
    """Handle the 'list' subcommand: list published workflows on a Galaxy instance."""
    try:
        if args.galaxy_url:
            galaxy_url = args.galaxy_url
            api_key = args.api_key if hasattr(args, 'api_key') else None
        else:
            try:
                galaxy_url, api_key = GalaxyClient.read_planemo_profile(args.profile)
            except Exception as e:
                logger.error(f"Failed to read Planemo profile: {e}")
                logger.error("Please provide --galaxy-url or a valid Planemo profile.")
                sys.exit(1)

        lister = GalaxyWorkflowLister(galaxy_url, api_key)

        if args.search:
            workflows = lister.search_workflows(args.search)
            print(f"\nFound {len(workflows)} workflows matching '{args.search}':")
        elif args.tag:
            workflows = lister.list_workflows_by_tag(args.tag)
            print(f"\nFound {len(workflows)} workflows with tag '{args.tag}':")
        elif args.stats:
            stats = lister.get_workflow_statistics()
            print("\n" + "=" * 50)
            print("WORKFLOW STATISTICS")
            print("=" * 50)
            print(f"Total published workflows: {stats['total_published']}")
            print(f"Total steps: {stats['total_steps']}")
            print(f"Average tools per workflow: {stats.get('avg_tools_per_workflow', 0):.1f}")
            print(f"With subworkflows: {stats['workflows_with_subworkflows']}")
            print(f"Unique creators: {len(stats.get('unique_creators', []))}")
            if stats.get('oldest_workflow'):
                print(f"Oldest: {stats['oldest_workflow']['name']} ({stats['oldest_workflow']['created']})")
            if stats.get('newest_workflow'):
                print(f"Newest: {stats['newest_workflow']['name']} ({stats['newest_workflow']['created']})")
            print("\nTop tags:")
            for tag, count in list(stats.get('tags', {}).items())[:10]:
                print(f"  {tag}: {count}")
            return
        else:
            limit = None if args.limit == 0 else args.limit
            workflows = lister.list_published_workflows(limit=limit)
            if limit:
                print(f"\nFound {len(workflows)} published workflows (showing up to {limit}):")
            else:
                print(f"\nFound {len(workflows)} published workflows:")

        if args.output:
            if args.output.lower().endswith('.tsv'):
                lister.export_to_tsv(workflows, args.output)
            else:
                lister.export_to_csv(workflows, args.output)
            print(f"\nExported {len(workflows)} workflows to {args.output}")
        else:
            lister.display_workflows_table(workflows, args.limit)

    except Exception as e:
        logger.error(f"Error during workflow listing: {e}")
        if args.verbose:
            logger.exception(e)
        sys.exit(1)


# -----------------------------------------------------------------------------
# HUB COMMAND HANDLER
# -----------------------------------------------------------------------------

def handle_hub_command(args: argparse.Namespace) -> None:
    """Handle the 'hub' subcommand: interact with WorkflowHub REST API."""
    try:
        config = load_config(args.config) if hasattr(args, 'config') and args.config else {}
        wh_rest_config = config.get('workflowhub_rest', {})
        base_url = wh_rest_config.get('base_url', 'https://workflowhub.eu')
        token_file = args.token_file or wh_rest_config.get('token_file')
        if token_file:
            token_file = Path(token_file).expanduser()

        client = WorkflowHubREST(base_url=base_url, token_file=token_file)

        if not client.token:
            logger.error("No authentication token found. Please set up a token file or provide --token-file.")
            sys.exit(1)

        from tabulate import tabulate
        import json

        if args.hub_action == 'list-mine':
            workflows = client.list_mine()
            if args.format == 'json':
                print(json.dumps(workflows, indent=2))
                return
            rows = [[wf['id'], wf['attributes'].get('title', 'No Title')] for wf in workflows]
            headers = ["ID", "Title"]
            if args.format == 'tsv':
                print("\t".join(headers))
                for row in rows:
                    print("\t".join(map(str, row)))
            else:
                print(tabulate(rows, headers=headers, tablefmt="grid"))

        elif args.hub_action == 'list-project':
            workflows = client.list_project_workflows(
                project_id=args.project_id,
                class_filter=args.workflow_class
            )
            if args.format == 'json':
                print(json.dumps(workflows, indent=2))
                return
            rows = []
            for w in workflows:
                rows.append([
                    w['title'], w['id'], w['version'], w['workflow_class'],
                    ", ".join(w['creators']), ", ".join(w['affiliations']),
                    w['created'][:10], w['modified'][:10]
                ])
            headers = ["Title", "ID", "Ver", "Class", "Creator", "Affiliation", "Created", "Modified"]
            if args.format == 'tsv':
                print("\t".join(headers))
                for row in rows:
                    print("\t".join(map(str, row)))
            else:
                print(tabulate(rows, headers=headers, tablefmt="grid"))

        elif args.hub_action == 'get':
            w = client.get_workflow_details(args.workflow_id)
            if not w:
                print("Workflow not found or error.", file=sys.stderr)
                return
            if args.format == 'json':
                print(json.dumps(w, indent=2))
                return
            rows = [[k, v] for k, v in w.items() if k not in ['url']]
            headers = ["Field", "Value"]
            if args.format == 'tsv':
                print("\t".join(headers))
                for row in rows:
                    print("\t".join(map(str, row)))
            else:
                print(tabulate(rows, headers=headers, tablefmt="grid"))
                print(f"URL: {w['url']}")

        elif args.hub_action == 'list-related':
            items = client.list_related_items(args.workflow_id)
            if not items:
                print("No related items found.")
                return
            if args.format == 'json':
                print(json.dumps(items, indent=2))
                return
            for category, item_list in items.items():
                print(f"\n{category.replace('_', ' ').title()}:")
                rows = [[it['name'], it['type']] for it in item_list]
                if rows:
                    print(tabulate(rows, headers=["Name", "Type"], tablefmt="grid"))

        elif args.hub_action == 'download-rocrate':
            out_dir = Path(args.output_dir) if args.output_dir else None
            zip_path = client.download_rocrate(args.workflow_id, out_dir)
            if zip_path:
                print(f"Downloaded to {zip_path}")
            else:
                print("Download failed.", file=sys.stderr)

        else:
            logger.error(f"Unknown hub action: {args.hub_action}")

    except Exception as e:
        logger.error(f"Error in hub command: {e}")
        if args.verbose:
            logger.exception(e)
        sys.exit(1)


# -----------------------------------------------------------------------------
# CHECK COMMAND – HELPER FUNCTIONS
# -----------------------------------------------------------------------------

def read_workflow_specs_from_csv(csv_path: str) -> List[WorkflowSpec]:
    import csv
    specs = []
    try:
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            required = {'name', 'registry', 'registry_id', 'recommended_version'}
            if not required.issubset(reader.fieldnames):
                missing = required - set(reader.fieldnames)
                raise ValueError(f"CSV missing required columns: {missing}")

            for row_num, row in enumerate(reader, start=2):
                if not any(row.values()):
                    continue
                registry = row['registry'].strip().lower()
                if registry not in ('workflowhub', 'dockstore'):
                    logger.warning(f"Row {row_num}: invalid registry '{registry}', skipping")
                    continue
                if not row['name'].strip() or not row['registry_id'].strip() or not row['recommended_version'].strip():
                    logger.warning(f"Row {row_num}: empty fields, skipping")
                    continue
                specs.append(WorkflowSpec.from_csv_row(row))
    except FileNotFoundError:
        logger.error(f"CSV file not found: {csv_path}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error parsing CSV: {e}")
        sys.exit(1)
    return specs


def resolve_galaxy_and_cache(args: argparse.Namespace, use_cache: bool = True):
    if args.galaxy_url:
        galaxy_url = args.galaxy_url.rstrip("/")
        logger.info(f"Galaxy URL: {galaxy_url} (keyless public access)")
        tool_cache = GalaxyClient.build_public_tool_cache(galaxy_url) if use_cache else {}
        return galaxy_url, tool_cache, "none (keyless public access)"
    else:
        galaxy_url, galaxy_key = GalaxyClient.read_planemo_profile(args.profile)
        logger.info(f"Galaxy URL: {galaxy_url} (profile: {args.profile})")
        tool_cache = GalaxyClient.build_tool_cache(galaxy_url, galaxy_key) if use_cache else {}
        return galaxy_url, tool_cache, args.profile


def generate_and_export_reports(
    args: argparse.Namespace,
    results: List[Dict],
    galaxy_url: str,
    profile: str,
    workspace: Path
) -> None:
    report = generate_report(results, galaxy_url, profile)
    display_summary(report)

    formats = ['txt', 'json'] if args.format == 'all' else [args.format]

    for fmt in formats:
        if fmt == 'txt':
            txt_path = args.output + ".txt"
            write_text_report(report, txt_path)
            logger.info(f"Text report: {txt_path}")
        elif fmt == 'json':
            json_path = args.output + ".json"
            with open(json_path, "w") as f:
                json.dump(report, f, indent=2)
            logger.info(f"JSON report: {json_path}")
        elif fmt == 'html':
            html_path = args.output + ".html"
            generate_html_report(report, html_path)
            logger.info(f"HTML report: {html_path}")

    if args.export_tool_issues_csv:
        csv_path = args.output + "_tool_issues.csv"
        export_tool_issues_to_csv(report, csv_path)
        logger.info(f"Tool issues CSV: {csv_path}")

    if args.export_install_script:
        if report.get('unique_missing_tools'):
            script = generate_installation_script(report['unique_missing_tools'], galaxy_url)
            script_path = args.output + "_install_tools.sh"
            with open(script_path, "w") as f:
                f.write(script)
            os.chmod(script_path, 0o755)
            logger.info(f"Installation script: {script_path}")
        else:
            logger.info("No missing tools to install")

    if args.compare_workflows:
        comparison = compare_workflows(report['results'])
        comp_path = args.output + "_comparison.json"
        with open(comp_path, "w") as f:
            json.dump(comparison, f, indent=2)
        logger.info(f"Workflow comparison: {comp_path}")


def create_spec_from_workflow_arg(workflow: str, version: str) -> Optional[WorkflowSpec]:
    """
    Convert a positional workflow argument to a WorkflowSpec.
    Detects type: numeric -> WorkflowHub; contains '/' -> Dockstore; ends with '.ga' -> local file.
    """
    if not workflow:
        return None

    # If it looks like a file path (contains '.ga' or starts with './', '/')
    if workflow.endswith('.ga') or workflow.startswith(('./', '/')) or '.' in workflow and '/' in workflow:
        # It's a local file, but we don't create a spec for local files; we handle them separately.
        # For now, we'll treat as local file only if the file exists.
        if Path(workflow).exists():
            return None  # will be handled by local_file logic
        # Otherwise, could be Dockstore path: e.g., github.com/iwc-workflows/Assembly/main
        # Dockstore paths contain '/', but not a file extension.
        if '/' in workflow and not workflow.endswith('.ga'):
            # Dockstore
            return WorkflowSpec(
                name=workflow.split('/')[-1],
                registry='dockstore',
                registry_id=workflow,
                version=version
            )

    # Numeric -> WorkflowHub
    if workflow.isdigit():
        return WorkflowSpec(
            name=workflow,
            registry='workflowhub',
            registry_id=workflow,
            version=version
        )

    # Try Dockstore by default if it contains '/'
    if '/' in workflow:
        return WorkflowSpec(
            name=workflow.split('/')[-1],
            registry='dockstore',
            registry_id=workflow,
            version=version
        )

    # Otherwise, assume WorkflowHub (numeric or string ID)
    return WorkflowSpec(
        name=workflow,
        registry='workflowhub',
        registry_id=workflow,
        version=version
    )


# -----------------------------------------------------------------------------
# CHECK COMMAND HANDLER
# -----------------------------------------------------------------------------

def handle_check_command(args: argparse.Namespace) -> None:
    """Handle the 'check' subcommand: validate workflows."""
    config = load_config(args.config) if args.config else {}
    skip_types = get_skip_types(config)

    workspace = Path(args.workspace)
    workspace.mkdir(exist_ok=True)

    # Determine version (support both --version and legacy --versions)
    version = getattr(args, 'version', None) or getattr(args, 'versions', 'latest')

    # ----------------------------------------------------------------------
    # CSV mode
    # ----------------------------------------------------------------------
    if args.csv:
        specs = read_workflow_specs_from_csv(args.csv)
        if not specs:
            logger.error("No valid workflow specifications found in CSV.")
            sys.exit(1)
        galaxy_url, tool_cache, profile = resolve_galaxy_and_cache(args, use_cache=not args.no_cache)
        if args.parallel:
            results = process_workflows_parallel(
                specs, workspace, tool_cache, args.max_workers, skip_types, config
            )
        else:
            results = []
            for spec in specs:
                result = process_workflow_spec(spec, workspace, tool_cache, skip_types, config) or []
                results.extend(result)
        if results:
            generate_and_export_reports(args, results, galaxy_url, profile, workspace)
        else:
            logger.warning("No results to report")
        return

    # ----------------------------------------------------------------------
    # Local file mode
    # ----------------------------------------------------------------------
    if args.local_file:
        ga_path = Path(args.local_file)
        if args.static_only:
            tool_cache = {}
            galaxy_url = "local"
            profile = "static"
        else:
            galaxy_url, tool_cache, profile = resolve_galaxy_and_cache(args, use_cache=not args.no_cache)
        info = {"name": ga_path.stem, "id": str(ga_path), "source": "local", "url": "local"}
        result = analyze_workflow(ga_path, info, args.version_label, tool_cache, skip_types)
        if result:
            results = [result]
            generate_and_export_reports(args, results, galaxy_url, profile, workspace)
        else:
            logger.warning("No results from local file analysis")
        return

    # ----------------------------------------------------------------------
    # Positional workflow argument
    # ----------------------------------------------------------------------
    if args.workflow:
        spec = create_spec_from_workflow_arg(args.workflow, version)
        if spec:
            # If it's a local file, the spec creation returns None and we treat as local file.
            # But create_spec_from_workflow_arg returns None for existing .ga files, so handle here.
            # Actually, create_spec will return a spec for Dockstore/WorkflowHub, but for local files it returns None.
            # We need to differentiate.
            if Path(args.workflow).exists() and args.workflow.endswith('.ga'):
                # Treat as local file
                args.local_file = args.workflow
                handle_check_command(args)  # re-call with local_file set
                return
            else:
                # It's a registry workflow
                galaxy_url, tool_cache, profile = resolve_galaxy_and_cache(args, use_cache=not args.no_cache)
                result = process_workflow_spec(spec, workspace, tool_cache, skip_types, config)
                if result:
                    results = result
                    generate_and_export_reports(args, results, galaxy_url, profile, workspace)
                else:
                    logger.warning("No results from workflow")
                return
        else:
            # Not a valid spec
            logger.error(f"Unrecognized workflow identifier: {args.workflow}")
            sys.exit(1)

    # ----------------------------------------------------------------------
    # Registry search / ID / entry modes
    # ----------------------------------------------------------------------
    registry = WorkflowRegistry(config)
    workflow_specs = []

    if args.search:
        if args.source in ("workflowhub", "both"):
            found = registry.search("workflowhub", args.search, args.max_workflows)
            for wf in found:
                workflow_specs.append(WorkflowSpec(
                    name=wf.get('name', ''),
                    registry='workflowhub',
                    registry_id=wf['id'],
                    version=version
                ))
        if args.source in ("dockstore", "both"):
            found = registry.search("dockstore", args.search, args.max_workflows)
            for wf in found:
                workflow_specs.append(WorkflowSpec(
                    name=wf.get('name', ''),
                    registry='dockstore',
                    registry_id=wf['entry'],
                    version=version
                ))

    if args.id:
        for id_spec in args.id:
            wf_id, v = parse_version_spec(id_spec, version)
            workflow_specs.append(WorkflowSpec(
                name=wf_id,
                registry='workflowhub',
                registry_id=wf_id,
                version=v
            ))

    if args.entry:
        for entry_spec in args.entry:
            entry, v = parse_version_spec(entry_spec, version)
            workflow_specs.append(WorkflowSpec(
                name=entry.split('/')[-1],
                registry='dockstore',
                registry_id=entry,
                version=v
            ))

    if not workflow_specs:
        logger.error("No workflows specified. Use --search, --id, --entry, --csv, --local-file, or provide a workflow ID/path.")
        sys.exit(1)

    galaxy_url, tool_cache, profile = resolve_galaxy_and_cache(args, use_cache=not args.no_cache)

    if args.parallel:
        results = process_workflows_parallel(
            workflow_specs, workspace, tool_cache, args.max_workers, skip_types, config
        )
    else:
        results = []
        for spec in workflow_specs:
            result = process_workflow_spec(spec, workspace, tool_cache, skip_types, config) or []
            results.extend(result)

    if results:
        generate_and_export_reports(args, results, galaxy_url, profile, workspace)
    else:
        logger.warning("No results to report")


# -----------------------------------------------------------------------------
# MAIN DISPATCHER
# -----------------------------------------------------------------------------

def main() -> None:
    args = parse_args()
    config = load_config(args.config) if hasattr(args, 'config') and args.config else {}

    log_level = logging.DEBUG if args.verbose else logging.INFO
    log_file = getattr(args, 'log_file', None)
    setup_logging(level=log_level, log_file=log_file)

    if args.command == 'list':
        handle_list_command(args)
    elif args.command == 'hub':
        handle_hub_command(args)
    elif args.command == 'check':
        handle_check_command(args)
    else:
        print("Please specify a command: check, list, or hub.")
        print("Use --help for more information.")
        sys.exit(1)


if __name__ == "__main__":
    main()
