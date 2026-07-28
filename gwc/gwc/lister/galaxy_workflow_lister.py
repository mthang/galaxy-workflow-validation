#!/usr/bin/env python3
"""
Galaxy Published Workflow Lister
Lists all published workflows from a Galaxy instance using pagination.
"""

import json
import urllib.request
import urllib.parse
import urllib.error
from typing import List, Dict, Optional, Any
import logging
import csv
from pathlib import Path

try:
    from bioblend.galaxy import GalaxyInstance
    BIOBLEND_AVAILABLE = True
except ImportError:
    BIOBLEND_AVAILABLE = False

logger = logging.getLogger(__name__)


class GalaxyWorkflowLister:
    """Class to list and retrieve published workflows from a Galaxy instance."""

    def __init__(self, galaxy_url: str, api_key: Optional[str] = None):
        """
        Initialize the lister with Galaxy instance URL and optional API key.

        Args:
            galaxy_url: Base URL of the Galaxy instance (e.g., https://usegalaxy.org.au)
            api_key: Optional API key for authenticated access
        """
        self.galaxy_url = galaxy_url.rstrip('/')
        self.api_key = api_key
        self.gi = None

        if api_key and BIOBLEND_AVAILABLE:
            self.gi = GalaxyInstance(url=galaxy_url, key=api_key)

    def list_published_workflows(self, limit: Optional[int] = None, offset: int = 0) -> List[Dict[str, Any]]:
        """
        List published workflows from the Galaxy instance.

        If limit is None, fetches ALL published workflows using pagination.
        If limit is a number, fetches at most that many.

        Args:
            limit: Maximum number of workflows to return (None = all)
            offset: Pagination offset (used for internal pagination)

        Returns:
            List of workflow dictionaries with workflow details
        """
        if self.gi:
            # Use BioBlend for authenticated access
            return self._list_published_workflows_bioblend(limit, offset)
        else:
            # Fall back to direct API calls
            return self._list_published_workflows_api(limit, offset)

    def _list_published_workflows_bioblend(self, limit: Optional[int], offset: int) -> List[Dict[str, Any]]:
        """Use BioBlend to fetch published workflows with pagination."""
        all_workflows = []
        page_size = 100
        current_offset = offset
        while True:
            try:
                workflows = self.gi.workflows.get_workflows(limit=page_size, offset=current_offset)
                if not workflows:
                    break
                # Filter for published
                published = [wf for wf in workflows if wf.get('published', False)]
                all_workflows.extend(published)
                current_offset += page_size
                if limit is not None and len(all_workflows) >= limit:
                    all_workflows = all_workflows[:limit]
                    break
                if len(workflows) < page_size:
                    break
            except Exception as e:
                logger.error(f"Error fetching workflows via BioBlend: {e}")
                break

        return self._enrich_workflow_data(all_workflows)

    def _list_published_workflows_api(self, limit: Optional[int], offset: int) -> List[Dict[str, Any]]:
        """Use direct API calls to fetch published workflows with pagination."""
        api_url = f"{self.galaxy_url}/api/workflows"
        all_workflows = []
        page_size = 100  # Number of workflows per API request
        current_offset = offset

        # Different API approaches; try them in order
        approaches = [
            self._fetch_published_approach1,
            self._fetch_published_approach2,
            self._fetch_published_approach3,
        ]

        for approach in approaches:
            workflows = approach(api_url, page_size, current_offset, limit)
            if workflows:
                all_workflows.extend(workflows)
                # If we have enough, stop fetching more
                if limit is not None and len(all_workflows) >= limit:
                    all_workflows = all_workflows[:limit]
                    break
                # Continue paginating if we need more
                while True:
                    if limit is not None and len(all_workflows) >= limit:
                        break
                    current_offset += page_size
                    more = approach(api_url, page_size, current_offset, limit)
                    if not more:
                        break
                    all_workflows.extend(more)
            if all_workflows:
                break  # Success with one approach, stop trying others

        return self._enrich_workflow_data(all_workflows)

    def _fetch_published_approach1(self, api_url: str, page_size: int, offset: int, limit: Optional[int]) -> List[Dict]:
        """Approach 1: Get all workflows and filter published."""
        try:
            params = {
                'limit': page_size,
                'offset': offset
            }
            url = f"{api_url}?{urllib.parse.urlencode(params)}"
            headers = {"Accept": "application/json"}
            if self.api_key:
                headers["x-api-key"] = self.api_key

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
                if isinstance(data, list):
                    return [wf for wf in data if wf.get('published', False)]
                elif isinstance(data, dict) and 'workflows' in data:
                    return [wf for wf in data['workflows'] if wf.get('published', False)]
        except Exception as e:
            logger.debug(f"Approach 1 failed: {e}")
        return []

    def _fetch_published_approach2(self, api_url: str, page_size: int, offset: int, limit: Optional[int]) -> List[Dict]:
        """Approach 2: published=true parameter."""
        try:
            url = f"{api_url}?published=true&limit={page_size}&offset={offset}"
            headers = {"Accept": "application/json"}
            if self.api_key:
                headers["x-api-key"] = self.api_key

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and 'workflows' in data:
                    return data['workflows']
        except Exception as e:
            logger.debug(f"Approach 2 failed: {e}")
        return []

    def _fetch_published_approach3(self, api_url: str, page_size: int, offset: int, limit: Optional[int]) -> List[Dict]:
        """Approach 3: list_published endpoint."""
        try:
            url = f"{self.galaxy_url}/api/workflows/list_published"
            if self.api_key:
                url += f"?key={self.api_key}"

            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
                if isinstance(data, list):
                    # This endpoint may return all, but we'll slice by offset/limit manually
                    if offset > 0:
                        data = data[offset:]
                    if limit is not None and len(data) > limit:
                        data = data[:limit]
                    return data
                elif isinstance(data, dict) and 'workflows' in data:
                    wfs = data['workflows']
                    if offset > 0:
                        wfs = wfs[offset:]
                    if limit is not None and len(wfs) > limit:
                        wfs = wfs[:limit]
                    return wfs
        except Exception as e:
            logger.debug(f"Approach 3 failed: {e}")
        return []

    def _enrich_workflow_data(self, workflows: List[Dict]) -> List[Dict[str, Any]]:
        """Enrich workflow data with additional details."""
        enriched = []
        for wf in workflows:
            wf_id = wf.get('id')
            if not wf_id:
                continue

            detailed = self._get_workflow_details(wf_id)
            creators = self._extract_creators(detailed) if detailed else self._extract_creators(wf)
            description = self._extract_description(detailed) if detailed else self._extract_description(wf)
            last_updated = self._get_last_updated(detailed) if detailed else wf.get('update_time')

            enriched_wf = {
                'id': wf_id,
                'name': wf.get('name', 'Unnamed workflow'),
                'description': description,
                'creators': creators,
                'published': wf.get('published', False),
                'url': f"{self.galaxy_url}/workflows/{wf_id}",
                'view_url': f"{self.galaxy_url}/workflows/list_published?workflow_id={wf_id}",
                'created': wf.get('create_time'),
                'updated': wf.get('update_time'),
                'last_updated': last_updated,
                'deleted': wf.get('deleted', False),
                'tags': wf.get('tags', []),
                'tool_count': len(detailed.get('steps', {})) if detailed else 0,
                'steps': detailed.get('steps', {}) if detailed else {},
                'has_subworkflows': self._check_for_subworkflows(detailed) if detailed else False,
                'owner': wf.get('owner', 'Unknown'),
                'annotation': wf.get('annotation', ''),
            }
            enriched.append(enriched_wf)

        return enriched

    # --- Helper methods (unchanged from original) ---

    def _extract_creators(self, workflow: Dict) -> List[str]:
        creators = []
        creator_fields = ['creator', 'creators', 'author', 'authors', 'owner']
        for field in creator_fields:
            value = workflow.get(field)
            if value:
                if isinstance(value, list):
                    creators.extend([str(c) for c in value if c])
                elif isinstance(value, str):
                    if ',' in value:
                        creators.extend([c.strip() for c in value.split(',') if c.strip()])
                    elif ';' in value:
                        creators.extend([c.strip() for c in value.split(';') if c.strip()])
                    else:
                        creators.append(value)
                break
        # Check annotations
        annotations = workflow.get('annotations', {})
        if isinstance(annotations, dict):
            for field in ['creator', 'author', 'authors', 'creators']:
                value = annotations.get(field)
                if value:
                    if isinstance(value, list):
                        creators.extend([str(c) for c in value if c])
                    elif isinstance(value, str):
                        if ',' in value:
                            creators.extend([c.strip() for c in value.split(',') if c.strip()])
                        elif ';' in value:
                            creators.extend([c.strip() for c in value.split(';') if c.strip()])
                        else:
                            creators.append(value)
                    break
        seen = set()
        unique = []
        for c in creators:
            if c and c not in seen:
                seen.add(c)
                unique.append(c)
        return unique if unique else ['Unknown']

    def _extract_description(self, workflow: Dict) -> str:
        for field in ['description', 'annotation', 'summary']:
            value = workflow.get(field)
            if value and value != workflow.get('name'):
                return str(value)
        annotations = workflow.get('annotations', {})
        if isinstance(annotations, dict):
            for field in ['description', 'summary', 'abstract', 'comment']:
                value = annotations.get(field)
                if value:
                    return str(value)
        return workflow.get('name', 'No description available')

    def _get_last_updated(self, workflow: Dict) -> Optional[str]:
        for field in ['update_time', 'last_updated', 'updated', 'timestamp']:
            if workflow.get(field):
                return workflow.get(field)
        return workflow.get('create_time')

    def _get_workflow_details(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        if self.gi:
            try:
                return self.gi.workflows.show_workflow(workflow_id)
            except Exception as e:
                logger.debug(f"Error getting workflow details: {e}")
                return None
        url = f"{self.galaxy_url}/api/workflows/{workflow_id}"
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode())
        except Exception as e:
            logger.debug(f"Error getting workflow details: {e}")
            return None

    def _check_for_subworkflows(self, workflow: Dict) -> bool:
        steps = workflow.get('steps', {})
        for step in steps.values():
            if isinstance(step, dict) and step.get('type') == 'subworkflow':
                return True
        return False

    # --- Public methods for filtering and export ---

    def list_workflows_by_tag(self, tag: str) -> List[Dict[str, Any]]:
        workflows = self.list_published_workflows(limit=None)  # fetch all
        return [wf for wf in workflows if tag in wf.get('tags', [])]

    def search_workflows(self, query: str) -> List[Dict[str, Any]]:
        workflows = self.list_published_workflows(limit=None)
        q = query.lower()
        return [
            wf for wf in workflows
            if q in wf.get('name', '').lower()
            or q in wf.get('id', '').lower()
            or q in wf.get('description', '').lower()
        ]

    def get_workflow_statistics(self) -> Dict[str, Any]:
        workflows = self.list_published_workflows(limit=None)
        stats = {
            'total_published': len(workflows),
            'total_steps': sum(wf.get('tool_count', 0) for wf in workflows),
            'workflows_with_subworkflows': sum(1 for wf in workflows if wf.get('has_subworkflows', False)),
            'oldest_workflow': None,
            'newest_workflow': None,
            'tags': {},
            'unique_creators': set(),
            'avg_tools_per_workflow': 0,
        }
        for wf in workflows:
            for tag in wf.get('tags', []):
                stats['tags'][tag] = stats['tags'].get(tag, 0) + 1
            for creator in wf.get('creators', []):
                stats['unique_creators'].add(creator)
        stats['tags'] = dict(sorted(stats['tags'].items(), key=lambda x: x[1], reverse=True))
        stats['unique_creators'] = sorted(stats['unique_creators'])
        if workflows:
            stats['avg_tools_per_workflow'] = stats['total_steps'] / len(workflows)
            sorted_by_date = sorted(
                [wf for wf in workflows if wf.get('created')],
                key=lambda x: x.get('created', '')
            )
            if sorted_by_date:
                stats['oldest_workflow'] = {
                    'name': sorted_by_date[0]['name'],
                    'created': sorted_by_date[0]['created']
                }
                stats['newest_workflow'] = {
                    'name': sorted_by_date[-1]['name'],
                    'created': sorted_by_date[-1]['created']
                }
        return stats

    def export_to_tsv(self, workflows: List[Dict], output_path: str):
        if not workflows:
            logger.warning("No workflows to export")
            return
        fieldnames = [
            'id', 'name', 'description', 'creators', 'published',
            'url', 'view_url', 'created', 'last_updated',
            'tool_count', 'has_subworkflows', 'owner', 'tags'
        ]
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter='\t')
            writer.writeheader()
            for wf in workflows:
                row = self._prepare_export_row(wf, fieldnames)
                writer.writerow(row)
        logger.info(f"Exported {len(workflows)} workflows to {output_path} (TSV)")

    def export_to_csv(self, workflows: List[Dict], output_path: str):
        if not workflows:
            logger.warning("No workflows to export")
            return
        fieldnames = [
            'id', 'name', 'description', 'creators', 'published',
            'url', 'view_url', 'created', 'updated', 'last_updated',
            'deleted', 'tool_count', 'has_subworkflows', 'owner', 'tags'
        ]
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for wf in workflows:
                row = self._prepare_export_row(wf, fieldnames)
                writer.writerow(row)
        logger.info(f"Exported {len(workflows)} workflows to {output_path} (CSV)")

    def _prepare_export_row(self, workflow: Dict, fieldnames: List[str]) -> Dict:
        row = {}
        for key in fieldnames:
            value = workflow.get(key, '')
            if key == 'creators' and isinstance(value, list):
                value = '; '.join(value) if value else ''
            elif key == 'tags' and isinstance(value, list):
                value = ', '.join(value) if value else ''
            elif key in ['published', 'deleted', 'has_subworkflows'] and isinstance(value, bool):
                value = 'Yes' if value else 'No'
            row[key] = value
        return row

    def display_workflows_table(self, workflows: List[Dict], limit: Optional[int] = None):
        if not workflows:
            print("No workflows to display")
            return
        if limit and len(workflows) > limit:
            workflows = workflows[:limit]
        max_id = max(len(str(wf.get('id', '')))[:20] for wf in workflows)
        max_name = max(len(str(wf.get('name', '')))[:40] for wf in workflows)
        max_desc = max(len(str(wf.get('description', '')))[:30] for wf in workflows)
        max_creator = max(len('; '.join(wf.get('creators', []))[:25]) for wf in workflows)
        max_id = max(max_id, 10)
        max_name = max(max_name, 20)
        max_desc = max(max_desc, 15)
        max_creator = max(max_creator, 15)
        header = (f"{'ID':<{max_id}}  {'Name':<{max_name}}  {'Description':<{max_desc}}  "
                  f"{'Creators':<{max_creator}}  {'Tools':>5}  {'Updated':<20}")
        print("\n" + "=" * (len(header) + 5))
        print(header)
        print("=" * (len(header) + 5))
        for wf in workflows:
            wf_id = str(wf.get('id', ''))[:max_id]
            wf_name = str(wf.get('name', ''))[:max_name]
            wf_desc = str(wf.get('description', ''))[:max_desc]
            wf_creators = '; '.join(wf.get('creators', []))[:max_creator]
            wf_tools = wf.get('tool_count', 0)
            wf_updated = str(wf.get('last_updated') or wf.get('created') or '')[:20]
            print(f"{wf_id:<{max_id}}  {wf_name:<{max_name}}  {wf_desc:<{max_desc}}  "
                  f"{wf_creators:<{max_creator}}  {wf_tools:>5}  {wf_updated:<20}")

    def get_workflow_ids(self) -> List[str]:
        workflows = self.list_published_workflows(limit=None)
        return [wf.get('id') for wf in workflows if wf.get('id')]

    def get_workflow_names(self) -> List[Dict[str, str]]:
        workflows = self.list_published_workflows(limit=None)
        return [{'id': wf.get('id'), 'name': wf.get('name', 'Unnamed')}
                for wf in workflows if wf.get('id')]
