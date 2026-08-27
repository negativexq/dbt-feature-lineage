"""Loading dbt's optional target/run_results.json -- the record of what
happened the last time `dbt build`/`run`/`test` actually executed, as
opposed to manifest.json's static "what does the project look like"
snapshot. Deliberately its own tiny loader, not folded into
manifest_loader.py: a project can have a manifest with no run_results
(never actually run against a warehouse) or a stale run_results next to
a fresh manifest (models added since the last run), and callers need to
tell "no data" apart from "ran and passed" -- conflating the two files
would lose that distinction.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple


class RunResultEntry(NamedTuple):
    """One node's outcome from the last `dbt build`/`run`/`test`
    invocation that touched it -- status is dbt's own vocabulary
    (pass/fail/warn/error/skipped for tests; success/error/skipped for
    model builds), read as-is rather than normalized, since
    health_service.py is the one place that needs to interpret it."""

    status: str
    execution_time: float | None


def run_results_mtime(resolved_path: Path, target_dir: str = "target") -> float:
    """0.0 (never a real mtime) when the file doesn't exist -- same
    "absence is a valid, cacheable state" convention as
    api/cache.py's manifest_mtime()."""

    run_results_file = resolved_path / target_dir / "run_results.json"
    return run_results_file.stat().st_mtime if run_results_file.exists() else 0.0


def load_run_results(
    project_path: str | Path, target_dir: str = "target"
) -> tuple[dict[str, RunResultEntry], str | None] | None:
    """Returns (unique_id -> RunResultEntry, generated_at) or None if
    target/run_results.json doesn't exist. Never raises on a malformed
    file -- a health signal that silently degrades to "unknown" on a
    corrupt artifact is a far better failure mode than a 500 on every
    page that shows it, and this file is dbt's own generated output,
    not user-authored config worth surfacing a parse error for.
    """

    resolved_path = Path(project_path).expanduser().resolve()
    run_results_file = resolved_path / target_dir / "run_results.json"
    if not run_results_file.exists():
        return None

    try:
        data = json.loads(run_results_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    results: dict[str, RunResultEntry] = {}
    for entry in data.get("results", []):
        unique_id = entry.get("unique_id")
        status = entry.get("status")
        if not unique_id or not status:
            continue
        results[unique_id] = RunResultEntry(
            status=status,
            execution_time=entry.get("execution_time"),
        )

    generated_at = data.get("metadata", {}).get("generated_at")
    return results, generated_at
