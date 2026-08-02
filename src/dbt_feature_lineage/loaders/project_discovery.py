"""Discovering dbt projects under a root directory -- powers
pages/select_project.py's project picker.

Kept separate from project_loader.py: that module loads ONE already-known
project path; this one's job is finding candidate project paths in the
first place, a distinct concern (filesystem-tree search vs. single-project
parsing).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dbt_feature_lineage.parsers.yaml_parser import parse_project_metadata

# Directories that are either never a project a user would want to pick
# (build/dependency output) or just noisy to descend into. Skipped
# in addition to any dot-prefixed (hidden) directory.
_SKIP_DIR_NAMES = frozenset({"target", "dbt_packages", "logs", "__pycache__", "node_modules"})


@dataclass(frozen=True)
class DiscoveredProject:
    """One dbt project found while scanning a root directory."""

    name: str
    path: str
    relative_path: str


def discover_dbt_projects(root: str | Path, max_depth: int = 4) -> list[DiscoveredProject]:
    """Recursively find dbt projects (directories containing
    dbt_project.yml) under `root`, up to `max_depth` levels deep.

    Once a project is found, its own subdirectories are never scanned
    further -- a project's target/, dbt_packages/, etc. can themselves
    contain a dbt_project.yml (an installed package, or generated build
    state), neither of which is a project a user would want to pick from
    this list. Hidden directories and a small set of known-noisy
    directory names (see _SKIP_DIR_NAMES) are skipped for the same
    reason, and to keep a deep/wide root from taking unreasonably long to
    scan -- `max_depth` is the other half of that same guard, bounding
    how far down an otherwise-unfiltered directory tree gets walked.

    Results are sorted by relative_path for a stable, predictable
    selectbox ordering.
    """

    resolved_root = Path(root).expanduser().resolve()
    found: list[DiscoveredProject] = []
    _scan(resolved_root, resolved_root, max_depth, found)
    return sorted(found, key=lambda project: project.relative_path)


def _scan(
    current: Path, root: Path, remaining_depth: int, found: list[DiscoveredProject]
) -> None:
    if not current.is_dir():
        return

    dbt_project_file = current / "dbt_project.yml"
    if dbt_project_file.exists():
        found.append(_to_discovered_project(current, root, dbt_project_file))
        return

    if remaining_depth <= 0:
        return

    try:
        children = sorted(current.iterdir())
    except PermissionError:
        return

    for child in children:
        if not child.is_dir():
            continue
        if child.name.startswith(".") or child.name in _SKIP_DIR_NAMES:
            continue
        _scan(child, root, remaining_depth - 1, found)


def _to_discovered_project(
    project_dir: Path, root: Path, dbt_project_file: Path
) -> DiscoveredProject:
    name = project_dir.name
    try:
        metadata = parse_project_metadata(dbt_project_file)
        name = metadata.get("name") or name
    except Exception:
        # A malformed dbt_project.yml shouldn't stop this project from
        # being listed at all -- fall back to the directory name, same
        # as when there's no `name:` key to read in the first place.
        pass

    relative_path = project_dir.relative_to(root)
    relative_path_str = str(relative_path) if str(relative_path) != "." else project_dir.name
    return DiscoveredProject(name=name, path=str(project_dir), relative_path=relative_path_str)
