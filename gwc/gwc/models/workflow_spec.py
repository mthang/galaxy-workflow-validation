"""Workflow specification models."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class WorkflowSpec:
    """Represents a workflow to check, parsed from CSV or CLI args."""
    name: str
    registry: str  # 'workflowhub' or 'dockstore'
    registry_id: str
    version: str

    def __post_init__(self):
        self.registry = self.registry.lower()

    @classmethod
    def from_csv_row(cls, row: dict) -> 'WorkflowSpec':
        """Parse from CSV row with columns: name, registry, registry_id, recommended_version."""
        return cls(
            name=row['name'].strip(),
            registry=row['registry'].strip(),
            registry_id=row['registry_id'].strip(),
            version=row['recommended_version'].strip()
        )

    @classmethod
    def from_cli(cls, registry: str, identifier: str, version: str, name: Optional[str] = None) -> 'WorkflowSpec':
        """Create from CLI arguments."""
        return cls(
            name=name or identifier.split('/')[-1],
            registry=registry,
            registry_id=identifier,
            version=version
        )

    def __repr__(self) -> str:
        return f"WorkflowSpec(name='{self.name}', registry={self.registry}, id={self.registry_id}, version={self.version})"
