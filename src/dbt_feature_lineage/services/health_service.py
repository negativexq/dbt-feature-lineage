"""Derives a per-model Healthy/Caution/Degraded/Unknown signal from the
last `dbt build`/`run`/`test` invocation -- the same kind of signal
dbt's own (paid, dbt Cloud-only) Explorer/Catalog ships, built here from
target/run_results.json, a file dbt already writes locally and for
free. No warehouse query, no dbt Cloud account: if the file exists,
there's a signal; if it doesn't, every model is honestly "unknown"
rather than a fabricated "healthy".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from dbt_feature_lineage.domain.models import DbtModel
from dbt_feature_lineage.loaders.run_results_loader import RunResultEntry

HealthStatus = Literal["healthy", "caution", "degraded", "unknown"]

# dbt's own status vocabulary, split by how bad it is. "error" covers both
# a model build blowing up and a test that couldn't even run; "fail" is a
# test assertion that ran and found real bad data; "warn" is a test
# configured non-blocking (warn_if) that still deserves a second look.
_DEGRADED_STATUSES = {"error", "fail"}
_CAUTION_STATUSES = {"warn", "skipped"}


@dataclass
class ModelHealth:
    model: str
    status: HealthStatus
    build_status: str | None
    failing_tests: int
    total_tests_run: int


def compute_model_health(
    models: list[DbtModel],
    run_results: dict[str, RunResultEntry] | None,
) -> list[ModelHealth]:
    if run_results is None:
        return [
            ModelHealth(
                model=m.name,
                status="unknown",
                build_status=None,
                failing_tests=0,
                total_tests_run=0,
            )
            for m in models
        ]

    health: list[ModelHealth] = []
    for model in models:
        build_result = run_results.get(model.unique_id) if model.unique_id else None
        test_results = [run_results[tid] for tid in model.test_unique_ids if tid in run_results]
        failing_tests = sum(1 for t in test_results if t.status in _DEGRADED_STATUSES)
        cautious_tests = sum(1 for t in test_results if t.status in _CAUTION_STATUSES)

        if build_result is None and not test_results:
            status: HealthStatus = "unknown"
        elif (build_result and build_result.status in _DEGRADED_STATUSES) or failing_tests:
            status = "degraded"
        elif (build_result and build_result.status in _CAUTION_STATUSES) or cautious_tests:
            status = "caution"
        else:
            status = "healthy"

        health.append(
            ModelHealth(
                model=model.name,
                status=status,
                build_status=build_result.status if build_result else None,
                failing_tests=failing_tests,
                total_tests_run=len(test_results),
            )
        )
    return health
