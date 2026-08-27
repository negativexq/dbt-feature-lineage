"""Cloning a dbt project straight from a git URL -- the alternative to
Select Project's directory-scan flow for anyone who doesn't already
have the repo checked out locally (which, for a tool meant to be
pointed at "the team's dbt project" rather than only "a project already
sitting on this machine", is most people). The result is just another
local path once cloning finishes: every downstream endpoint
(discover/project/model-dag/...) treats a cloned checkout exactly like
any other project directory, no separate code path.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

CLONE_TIMEOUT_SECONDS = 120
DEFAULT_CLONE_ROOT = Path.home() / ".dbt-feature-lineage" / "repos"

# git@host:owner/repo.git (scp-like syntax) has no scheme prefix at all,
# so it's matched separately rather than folded into the tuple below.
_ALLOWED_URL_PREFIXES = ("https://", "http://")
_SSH_SHORTHAND = re.compile(r"^[\w.-]+@[\w.-]+:.+")


class GitCloneError(RuntimeError):
    """Wraps git's own stderr -- surfaced to the user as-is (via the API's
    400 response) rather than a generic "clone failed", since git's
    error text ("Repository not found", "Could not resolve host",
    "Authentication failed") is usually the actual answer to "why?"."""


def _validate_url(url: str) -> None:
    if url.startswith(_ALLOWED_URL_PREFIXES) or _SSH_SHORTHAND.match(url):
        return
    raise GitCloneError(
        "Only an https://, http://, or git@host:owner/repo.git URL is accepted -- "
        "for a local checkout you already have, use the directory scan above instead."
    )


def _local_dir_name(url: str) -> str:
    """A filesystem-safe, stable name derived from the URL -- stable so
    cloning the same URL twice reuses (and updates) one checkout rather
    than piling up duplicates on every click."""

    last_segment = url.rstrip("/").rsplit("/", 1)[-1]
    if last_segment.endswith(".git"):
        last_segment = last_segment[: -len(".git")]
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", last_segment).strip("-") or "repo"
    digest = hashlib.sha1(url.encode()).hexdigest()[:8]
    return f"{slug}-{digest}"


def _run_git(args: list[str], cwd: Path) -> None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=CLONE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitCloneError(f"git {args[0]} timed out after {CLONE_TIMEOUT_SECONDS}s.") from exc

    if result.returncode != 0:
        raise GitCloneError(result.stderr.strip() or f"git {args[0]} failed with no error output.")


def clone_or_pull_repo(url: str, ref: str | None = None, clone_root: Path | None = None) -> Path:
    """Clone `url` into a stable local cache directory (~/.dbt-feature-lineage/repos
    by default), or fetch+reset it in place if it's already been cloned
    here before. Returns the local checkout path.

    Always shallow (--depth 1): this tool only ever reads the working
    tree's current SQL/YAML files (and an optional committed
    target/manifest.json) -- full git history is never used, so there's
    no reason to pay to fetch it. `git reset --hard` after fetching
    never touches target/ or dbt_packages/ (untracked, presumably
    .gitignore'd in the source repo) -- a manifest generated here by a
    previous "Generate artifacts" click survives a re-clone/pull.
    """

    _validate_url(url)
    root = clone_root or DEFAULT_CLONE_ROOT
    root.mkdir(parents=True, exist_ok=True)
    dest = root / _local_dir_name(url)

    if (dest / ".git").is_dir():
        _run_git(["fetch", "--depth", "1", "origin", ref or "HEAD"], cwd=dest)
        _run_git(["reset", "--hard", "FETCH_HEAD"], cwd=dest)
    else:
        args = ["clone", "--depth", "1"]
        if ref:
            args += ["--branch", ref]
        args += [url, str(dest)]
        _run_git(args, cwd=root)

    return dest
