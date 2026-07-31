"""Model inspection service."""

from __future__ import annotations

from pathlib import Path

from dbt_feature_lineage.domain.models import DbtModelAnalysis, DbtProject
from dbt_feature_lineage.loaders.project_loader import load_dbt_project
from dbt_feature_lineage.parsers.query_flow_parser import analyze_query_flow


def inspect_model(project_path: str | Path, model_name: str) -> DbtModelAnalysis:
    """Inspect a single model inside a dbt project."""

    project = load_dbt_project(project_path)
    model = _find_model(project, model_name)
    analysis = analyze_query_flow(model.raw_sql)
    analysis.model_name = model.name
    analysis.file_path = model.file_path
    analysis.relative_path = model.relative_path
    analysis.layer = model.layer
    analysis.ref_dependencies = model.ref_dependencies
    analysis.source_dependencies = model.source_dependencies
    return analysis


def _find_model(project: DbtProject, model_name: str):
    for model in project.models:
        if model.name == model_name:
            return model
    raise ValueError(f"Model not found: {model_name}")
