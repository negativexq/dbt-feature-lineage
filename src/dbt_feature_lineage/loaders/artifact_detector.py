"""Manifest-vs-static artifact detection and fallback orchestration.

Single entry point (`resolve_dbt_project`) that callers (CLI, Streamlit app)
use instead of calling the manifest or static loaders directly. It never
falls back silently: every static fallback carries an `ArtifactStatus`
explaining why the manifest wasn't used, for the caller to surface.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from dbt_feature_lineage.domain.models import ArtifactStatus, DbtProject
from dbt_feature_lineage.loaders.manifest_loader import (
    ManifestNotFoundError,
    ManifestParseError,
    UnsupportedManifestSchemaVersionError,
    load_dbt_project_from_manifest,
)
from dbt_feature_lineage.loaders.project_loader import load_dbt_project

DEFAULT_DBT_PARSE_TIMEOUT_SECONDS = 120


def resolve_dbt_project(
    project_path: str | Path,
    generate_artifacts: bool = False,
    target_dir: str = "target",
    dbt_parse_timeout: int = DEFAULT_DBT_PARSE_TIMEOUT_SECONDS,
) -> DbtProject:
    """Resolve a dbt project, preferring a manifest.json over the static SQL parser.

    Interactive confirmation ("should we run `dbt parse`?") is the caller's
    responsibility -- this function only acts on the already-decided
    `generate_artifacts` flag.
    """

    resolved_path = Path(project_path).expanduser().resolve()
    manifest_file = resolved_path / target_dir / "manifest.json"

    if manifest_file.exists():
        return _load_manifest_or_fall_back(resolved_path, target_dir, reason="found")

    if not generate_artifacts:
        return _load_static(
            resolved_path, reason="not_generated", message="target/manifest.json not found."
        )

    if shutil.which("dbt") is None:
        return _load_static(
            resolved_path,
            reason="dbt_cli_unavailable",
            message="`dbt` executable not found on PATH.",
        )

    if not _dbt_profile_available(resolved_path):
        return _load_static(
            resolved_path,
            reason="no_profile",
            message=(
                "No profiles.yml found for the project (project dir, DBT_PROFILES_DIR, ~/.dbt)."
            ),
        )

    try:
        result = subprocess.run(
            ["dbt", "parse", "--project-dir", str(resolved_path)],
            capture_output=True,
            text=True,
            timeout=dbt_parse_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return _load_static(
            resolved_path, reason="dbt_parse_failed", message=f"`dbt parse` timed out: {exc}"
        )

    if result.returncode != 0:
        return _load_static(
            resolved_path,
            reason="dbt_parse_failed",
            message=f"`dbt parse` exited with {result.returncode}: {result.stderr.strip()}",
        )

    if not manifest_file.exists():
        return _load_static(
            resolved_path,
            reason="dbt_parse_failed",
            message="`dbt parse` succeeded but did not produce target/manifest.json.",
        )

    return _load_manifest_or_fall_back(resolved_path, target_dir, reason="generated")


def _load_manifest_or_fall_back(
    project_dir: Path, target_dir: str, reason: str
) -> DbtProject:
    try:
        project = load_dbt_project_from_manifest(project_dir, target_dir=target_dir)
    except (ManifestNotFoundError, ManifestParseError) as exc:
        return _load_static(project_dir, reason="manifest_parse_failed", message=str(exc))
    except UnsupportedManifestSchemaVersionError as exc:
        return _load_static(
            project_dir, reason="unsupported_manifest_schema_version", message=str(exc)
        )

    project.artifact_status = ArtifactStatus(mode="manifest", reason=reason)
    return project


def _load_static(project_dir: Path, reason: str, message: str) -> DbtProject:
    project = load_dbt_project(project_dir)
    project.artifact_status = ArtifactStatus(mode="static", reason=reason, message=message)
    return project


def _dbt_profile_available(project_dir: Path) -> bool:
    if (project_dir / "profiles.yml").exists():
        return True

    profiles_dir_env = os.environ.get("DBT_PROFILES_DIR")
    if profiles_dir_env and (Path(profiles_dir_env) / "profiles.yml").exists():
        return True

    return _home_profiles_path().exists()


def _home_profiles_path() -> Path:
    return Path.home() / ".dbt" / "profiles.yml"
