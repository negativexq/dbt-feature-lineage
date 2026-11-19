"""Manifest-vs-static artifact detection and fallback orchestration.

Single entry point (`resolve_dbt_project`) that callers (CLI, Streamlit app)
use instead of calling the manifest or static loaders directly. It never
falls back silently: every static fallback carries an `ArtifactStatus`
explaining why the manifest wasn't used, for the caller to surface.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
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
    force_parse: bool = False,
) -> DbtProject:
    """Resolve a dbt project, preferring a manifest.json over the static SQL parser.

    Interactive confirmation ("should we run `dbt parse`?") is the caller's
    responsibility -- this function only acts on the already-decided
    `generate_artifacts` flag.
    """

    resolved_path = Path(project_path).expanduser().resolve()
    manifest_file = resolved_path / target_dir / "manifest.json"

    # force_parse is the explicit "re-parse" action: an existing manifest
    # may be stale (edited YAML/SQL since), so run dbt parse regardless.
    if manifest_file.exists() and not (generate_artifacts and force_parse):
        return _load_manifest_or_fall_back(resolved_path, target_dir, reason="found")

    if not generate_artifacts:
        # The "not_generated" reason is fully self-explanatory via its fixed
        # UI headline (see ui.rendering._ARTIFACT_STATUS_MESSAGES) -- no
        # extra message needed, so we don't restate it here.
        return _load_static(resolved_path, reason="not_generated")

    def fail(reason: str, message: str = "") -> DbtProject:
        # A forced re-parse that can't run or fails must not throw away the
        # manifest that was already there: keep using it, flagged stale.
        if manifest_file.exists():
            project = _load_manifest_or_fall_back(
                resolved_path, target_dir, reason="reparse_failed"
            )
            if project.artifact_status and project.artifact_status.mode == "manifest":
                project.artifact_status.message = message or _ARTIFACT_FAILURE_HINTS.get(reason, "")
            return project
        return _load_static(resolved_path, reason=reason, message=message)

    if shutil.which("dbt") is None:
        # Same as above: nothing to add beyond the fixed headline.
        return fail("dbt_cli_unavailable")

    profiles_dir = _resolve_profiles_dir(resolved_path)
    if profiles_dir is None:
        return fail(
            "no_profile",
            "Checked the project directory, DBT_PROFILES_DIR, and ~/.dbt for profiles.yml.",
        )

    started_at = time.time()
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
            env=_dbt_parse_env(),
        )
    except subprocess.TimeoutExpired:
        return fail("dbt_parse_failed", f"`dbt parse` timed out after {dbt_parse_timeout}s.")

    if result.returncode != 0:
        # dbt 2.0 exits non-zero for project-spec violations it only
        # *ignores* (an unknown YAML key, top-level `meta:` instead of
        # `config: meta:`) yet still writes a complete manifest.json. A
        # manifest written by *this* run is real lineage -- far better than
        # dropping to the static parser over a config-hygiene error -- so
        # use it and surface dbt's output as a warning instead.
        if _written_since(manifest_file, started_at):
            project = _load_manifest_or_fall_back(
                resolved_path, target_dir, reason="generated_with_errors"
            )
            if project.artifact_status.mode == "manifest":
                project.artifact_status.message = _dbt_output_excerpt(result)
            return project
        return fail(
            "dbt_parse_failed", f"Exit code {result.returncode}: {_dbt_output_excerpt(result)}"
        )

    if not manifest_file.exists():
        return _load_static(
            resolved_path,
            reason="dbt_parse_failed",
            message="`dbt parse` exited successfully but did not create target/manifest.json.",
        )

    return _load_manifest_or_fall_back(resolved_path, target_dir, reason="generated")


_ARTIFACT_FAILURE_HINTS = {
    "dbt_cli_unavailable": "`dbt` CLI not found on PATH.",
}


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

    dbt_version = project.metadata.get("dbt_version") if project.metadata else None
    project.artifact_status = ArtifactStatus(
        mode="manifest", reason=reason, dbt_version=dbt_version or None
    )
    return project


def _dbt_parse_env() -> dict[str, str]:
    """Environment for `dbt parse`.

    dbt 2.0 refuses to even *parse* a project whose profile uses an adapter
    it hasn't promoted to stable yet (postgres, among others) unless
    DBT_ALLOW_EXPERIMENTAL_ADAPTERS is set. Parsing never opens a warehouse
    connection, so opting in here is safe; an explicit user setting wins.
    dbt 1.x ignores the variable.
    """
    env = dict(os.environ)
    env.setdefault("DBT_ALLOW_EXPERIMENTAL_ADAPTERS", "true")
    # Plain-text output: the error excerpt is shown in the UI, not a TTY.
    env.setdefault("DBT_USE_COLORS", "false")
    env.setdefault("NO_COLOR", "1")
    return env


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _written_since(path: Path, started_at: float) -> bool:
    try:
        # 1s of slack for filesystems with coarse mtime resolution.
        return path.stat().st_mtime >= started_at - 1
    except OSError:
        return False


def _dbt_output_excerpt(result: subprocess.CompletedProcess[str], limit: int = 4000) -> str:
    """dbt's error text, from whichever stream it used.

    dbt 1.x writes errors to stdout; dbt 2.0 writes them to stderr.
    """
    text = "\n".join(
        _ANSI_ESCAPE.sub("", part).strip()
        for part in (result.stderr or "", result.stdout or "")
        if part.strip()
    )
    return text[-limit:] if len(text) > limit else text


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


_DBT_ISSUE = re.compile(
    r"\[(?P<severity>error|warning|warn)\]\s*\[(?P<kind>[^\]()]+?)\s*\((?P<code>dbt\d+)\)\]:\s*"
    r"(?P<message>.+?)(?:\n\s*-->\s*(?P<location>\S+?):(?P<line>\d+)(?::\d+)?)?(?=\n|$)",
    re.IGNORECASE,
)


def parse_dbt_issues(text: str) -> list[dict[str, str | int | None]]:
    """Structured issues from dbt 2.0's `[error] [Kind (dbtNNNN)]: msg --> file:line` output.

    dbt 1.x output has no stable structure and yields an empty list; callers
    then show the raw text instead.
    """
    issues: list[dict[str, str | int | None]] = []
    for match in _DBT_ISSUE.finditer(text or ""):
        location = match.group("location")
        issues.append(
            {
                "severity": "warning" if match.group("severity").lower() != "error" else "error",
                "kind": match.group("kind").strip(),
                "code": match.group("code"),
                "message": re.sub(
                    r"^While parsing config:\s*", "", match.group("message").strip()
                ),
                # dbt prints the path relative to the cwd it was launched
                # from; keep only the project-relative tail for display.
                "file": _project_relative(location) if location else None,
                "line": int(match.group("line")) if match.group("line") else None,
            }
        )
    return sorted(issues, key=lambda i: (str(i["file"] or ""), int(i["line"] or 0)))


def _project_relative(location: str) -> str:
    parts = Path(location).parts
    for anchor in ("models", "seeds", "snapshots", "macros", "tests", "analyses"):
        if anchor in parts:
            return str(Path(*parts[parts.index(anchor):]))
    return location
