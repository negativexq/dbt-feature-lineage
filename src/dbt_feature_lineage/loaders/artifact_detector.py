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
        # The "not_generated" reason is fully self-explanatory via its fixed
        # UI headline (see ui.rendering._ARTIFACT_STATUS_MESSAGES) -- no
        # extra message needed, so we don't restate it here.
        return _load_static(resolved_path, reason="not_generated")

    if shutil.which("dbt") is None:
        # Same as above: nothing to add beyond the fixed headline.
        return _load_static(resolved_path, reason="dbt_cli_unavailable")

    profiles_dir = _resolve_profiles_dir(resolved_path)
    if profiles_dir is None:
        return _load_static(
            resolved_path,
            reason="no_profile",
            message="Checked the project directory, DBT_PROFILES_DIR, and ~/.dbt for profiles.yml.",
        )

    try:
        result = subprocess.run(
            [
                "dbt",
                "parse",
                "--project-dir",
                str(resolved_path),
                "--profiles-dir",
                str(profiles_dir),
                # dbt's own partial-parse cache (target/partial_parse.msgpack)
                # can silently miss a YAML-only edit -- a schema.yml
                # description/owner/test added with no .sql file touched --
                # and hand back the previous manifest unchanged. Since this
                # call is exactly the "did my doc/owner edit take?" path
                # (both the CLI's interactive re-parse prompt and the web
                # UI's "Generate artifacts"/"re-parse" button), a stale
                # result here is worse than the extra parse cost of always
                # doing a full one.
                "--no-partial-parse",
            ],
            capture_output=True,
            text=True,
            timeout=dbt_parse_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _load_static(
            resolved_path,
            reason="dbt_parse_failed",
            message=f"`dbt parse` timed out after {dbt_parse_timeout}s.",
        )

    if result.returncode != 0:
        return _load_static(
            resolved_path,
            reason="dbt_parse_failed",
            message=f"Exit code {result.returncode}: {result.stderr.strip()}",
        )

    if not manifest_file.exists():
        return _load_static(
            resolved_path,
            reason="dbt_parse_failed",
            message="`dbt parse` exited successfully but did not create target/manifest.json.",
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


def _load_static(project_dir: Path, reason: str, message: str = "") -> DbtProject:
    project = load_dbt_project(project_dir)
    project.artifact_status = ArtifactStatus(mode="static", reason=reason, message=message)
    return project


def _resolve_profiles_dir(project_dir: Path) -> Path | None:
    """Find the directory that has a profiles.yml `dbt parse` can use.

    dbt's default profiles-dir resolution (env var, then ~/.dbt) doesn't
    include the project directory itself, so we must pass `--profiles-dir`
    explicitly whenever the profile lives next to dbt_project.yml -- dbt
    would otherwise ignore it and fail (or worse, error out entirely if
    ~/.dbt doesn't exist in the running environment).
    """

    if (project_dir / "profiles.yml").exists():
        return project_dir

    profiles_dir_env = os.environ.get("DBT_PROFILES_DIR")
    if profiles_dir_env and (Path(profiles_dir_env) / "profiles.yml").exists():
        return Path(profiles_dir_env)

    if _home_profiles_path().exists():
        return _home_profiles_path().parent

    return None


def _home_profiles_path() -> Path:
    return Path.home() / ".dbt" / "profiles.yml"
