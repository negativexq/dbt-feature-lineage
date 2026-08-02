"""Builds the project-wide model-level DAG (v0.5).

Single entry point: build_model_dag(project) -> networkx.DiGraph. Nodes
are plain model-name strings -- not domain.lineage.ColumnNode, this graph
has no column granularity -- carrying layer/materialization/description/
tags/test_count/owner/column_count as node attributes. Edges are
unlabeled ref() relationships (upstream -> downstream), same direction
convention as lineage_service.build_project_lineage().

Deliberately does NOT build on lineage_service.build_project_lineage():
that runs one sqlglot.lineage() call per output column per model (~15s
cold on the 12-model example project, per docs/v0.4-plan.md Bölüm 6) to
trace column-level ancestry -- overkill for a graph whose edges already
come straight from DbtModel.ref_dependencies (populated in both static
and manifest mode -- see docs/v0.5-plan.md Bölüm 1). The only thing here
that needs schema_builder at all is column_count, and
build_project_schema() alone (one analyze_query_flow() pass per model, no
sqlglot.lineage() calls) is a fraction of that cost.
"""

from __future__ import annotations

import networkx as nx

from dbt_feature_lineage.domain.models import DbtProject
from dbt_feature_lineage.services.lineage_service import resolve_circular_ref_dependencies
from dbt_feature_lineage.services.schema_builder import build_project_schema


def build_model_dag(project: DbtProject) -> nx.DiGraph:
    """Build the project-wide model-level DAG.

    A model-level ref() cycle (see resolve_circular_ref_dependencies --
    realistically only reachable in static mode, since dbt itself refuses
    to compile a cyclic project) is reported via
    `graph.graph["model_dag_warnings"]` and every model involved is
    excluded from the graph entirely, rather than raising -- this is a
    project-wide exploration view, not a single lineage trace, so one
    cycle shouldn't take down the whole page. schema_warnings from
    build_project_schema() (e.g. a model missing schema/alias metadata)
    are folded into the same warnings list, for the same reason
    lineage_service surfaces them via lineage_warnings.
    """

    excluded_models, circular_warnings = resolve_circular_ref_dependencies(project)
    project_schema = build_project_schema(project)

    graph: nx.DiGraph = nx.DiGraph()
    model_names = {model.name for model in project.models}

    for model in project.models:
        if model.name in excluded_models:
            continue
        graph.add_node(
            model.name,
            layer=model.layer,
            materialization=model.materialization,
            description=model.description,
            tags=model.tags,
            test_count=model.test_count,
            owner=model.owner,
            column_count=len(project_schema.columns_by_model.get(model.name, [])),
        )

    for model in project.models:
        if model.name in excluded_models:
            continue
        for dependency in model.ref_dependencies:
            target = dependency.target_name
            if target in model_names and target not in excluded_models:
                graph.add_edge(target, model.name)

    graph.graph["model_dag_warnings"] = [*circular_warnings, *project_schema.schema_warnings]

    return graph
