"""Builds the project-wide column lineage graph.

Single entry point: build_project_lineage(project) -> networkx.DiGraph.
Per docs/v0.3-plan.md's decision (Bölüm 6/10), there is no wrapper type --
node keys are domain.lineage.ColumnNode (frozen/hashable), edges carry
ColumnEdge fields as edge data.
"""

from __future__ import annotations

import hashlib

import networkx as nx
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.lineage import Node, lineage

from dbt_feature_lineage.domain.lineage import ColumnEdge, ColumnNode
from dbt_feature_lineage.domain.models import DbtProject, Layer
from dbt_feature_lineage.parsers.query_flow_parser import detect_transformation_type
from dbt_feature_lineage.services.schema_builder import ProjectSchema, build_project_schema

DEFAULT_DIALECT = "postgres"

# dbt adapter name -> sqlglot dialect name. All five map 1:1; an adapter
# outside this set (or static mode, which has no adapter_type at all)
# falls back to DEFAULT_DIALECT -- matching the pre-v0.3 hardcoded behavior.
_ADAPTER_TO_DIALECT: dict[str, str] = {
    "postgres": "postgres",
    "snowflake": "snowflake",
    "bigquery": "bigquery",
    "redshift": "redshift",
    "trino": "trino",
}


class CircularDependencyError(ValueError):
    """Raised when the project's ref() graph is not a DAG.

    Checked against DbtModel.ref_dependencies *before* calling sqlglot --
    exp.expand() (which `sources`-based stitching relies on) has no cycle
    guard of its own, so a circular ref() would otherwise recurse without
    bound (docs/v0.3-plan.md Risk 5).
    """


def resolve_dialect(project: DbtProject) -> str:
    """Map manifest metadata.adapter_type to a sqlglot dialect name."""

    adapter_type = project.metadata.get("adapter_type")
    if isinstance(adapter_type, str) and adapter_type in _ADAPTER_TO_DIALECT:
        return _ADAPTER_TO_DIALECT[adapter_type]
    return DEFAULT_DIALECT


def get_column_lineage(
    project_schema: ProjectSchema,
    model_name: str,
    column_name: str,
    dialect: str,
) -> Node:
    """Run a single sqlglot lineage() call for one model's output column."""

    raw_sql = project_schema.raw_sql_by_model[model_name]
    return lineage(
        column_name,
        raw_sql,
        schema=project_schema.schema,
        sources=project_schema.sources,
        dialect=dialect,
    )


def build_project_lineage(project: DbtProject) -> nx.DiGraph:
    """Build the full column lineage graph for a project.

    Calls get_column_lineage() once per (model, output column) pair and
    merges every result into one DiGraph. Pure/uncached -- see
    lineage_cache_key() for how a caller should cache this.

    A column whose SQL sqlglot itself rejects (e.g. a CTE referencing a
    column its own upstream CTE never actually selected -- a real bug this
    engine caught in examples/sample_banking_dbt during development) is
    skipped rather than aborting the whole build, but never silently: it's
    recorded in the returned graph's `graph["lineage_warnings"]`.
    """

    _guard_against_circular_dependencies(project)

    project_schema = build_project_schema(project)
    dialect = resolve_dialect(project)
    layers = {model.name: model.layer for model in project.models}

    graph: nx.DiGraph = nx.DiGraph()
    lineage_warnings: list[str] = []

    for model in project.models:
        for column_name in project_schema.columns_by_model.get(model.name, []):
            try:
                root = get_column_lineage(project_schema, model.name, column_name, dialect)
            except SqlglotError as exc:
                lineage_warnings.append(
                    f"Could not build lineage for '{model.name}.{column_name}': {exc}"
                )
                continue

            edges: list[ColumnEdge] = []
            root_node = _convert_node(root, model.name, project_schema, layers, edges)

            graph.add_node(root_node)
            for edge in edges:
                graph.add_edge(
                    edge.source,
                    edge.target,
                    transformation_type=edge.transformation_type,
                    expression_sql=edge.expression_sql,
                )

    graph.graph["lineage_warnings"] = lineage_warnings

    return graph


def lineage_cache_key(project: DbtProject) -> tuple[str, str, str | None, int, str]:
    """A pure, content-sensitive cache key -- changes whenever any model's
    SQL changes, not just when a manifest file's mtime changes (unlike
    v0.2's _manifest_cache_key, this doesn't assume a backing file exists)."""

    fingerprint_source = "|".join(
        f"{model.name}:{model.raw_sql}" for model in sorted(project.models, key=lambda m: m.name)
    )
    model_fingerprint = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()
    artifact_reason = project.artifact_status.reason if project.artifact_status else None

    return (
        project.project_path,
        project.source,
        artifact_reason,
        len(project.models),
        model_fingerprint,
    )


def _guard_against_circular_dependencies(project: DbtProject) -> None:
    model_names = {model.name for model in project.models}
    dependency_graph: nx.DiGraph = nx.DiGraph()
    dependency_graph.add_nodes_from(model_names)

    for model in project.models:
        for dependency in model.ref_dependencies:
            if dependency.target_name in model_names:
                dependency_graph.add_edge(dependency.target_name, model.name)

    if not nx.is_directed_acyclic_graph(dependency_graph):
        cycle = next(iter(nx.simple_cycles(dependency_graph)))
        chain = " -> ".join([*cycle, cycle[0]])
        raise CircularDependencyError(f"Circular ref() dependency detected: {chain}")


def _convert_node(
    node: Node,
    owning_model: str,
    project_schema: ProjectSchema,
    layers: dict[str, Layer],
    edges: list[ColumnEdge],
) -> ColumnNode:
    """Convert a sqlglot lineage Node subtree into a ColumnNode, appending
    every cross-model/cross-column ColumnEdge discovered along the way.

    A node's "owning model" is whichever model's raw SQL text literally
    contains that expression -- propagated top-down via Node.source_name,
    which sqlglot sets on a node whenever its *children* were reached by
    expanding a `sources` entry (verified empirically: a node's own
    source_name names the model its downstream children live in, not
    itself).

    Node.source_name is always one of the literal keys from
    ProjectSchema.sources (bare/schema-qualified/database-qualified --
    whichever one exp.expand() happened to match), never a clean dbt
    model name by itself. Using it directly as a ColumnNode.model (as an
    earlier version of this function did) produced two different node
    identities for the same model depending on whether it was reached as
    the root of its own trace (clean name) or as an ancestor while tracing
    a different, downstream model (raw sources-key string, e.g.
    "analytics_intermediate.int_customer_activity" instead of
    "int_customer_activity") -- so it must be resolved through
    ProjectSchema.sources_key_to_model first.
    """

    if isinstance(node.expression, exp.Table):
        return _leaf_column_node(node, project_schema, layers)

    this_node = ColumnNode(
        model=owning_model,
        column=_clean_column_name(node.name),
        layer=layers.get(owning_model, "unknown"),
    )

    for child in node.downstream:
        child_model = _resolve_source_name(node.source_name, project_schema) or owning_model
        child_node = _convert_node(child, child_model, project_schema, layers, edges)

        if child_node != this_node:
            edges.append(
                ColumnEdge(
                    source=child_node,
                    target=this_node,
                    transformation_type=detect_transformation_type(
                        node.expression, this_node.column
                    ),
                    expression_sql=node.expression.sql(),
                )
            )

    return this_node


def _leaf_column_node(
    node: Node, project_schema: ProjectSchema, layers: dict[str, Layer]
) -> ColumnNode:
    table = node.expression
    assert isinstance(table, exp.Table)
    key = (table.db or None, table.name)

    if key in project_schema.physical_to_model:
        resolved_model = project_schema.physical_to_model[key]
        # None means a known dbt *source* (terminal) -- represent it by its
        # own physical identity, since it has no dbt model name of its own.
        model_name = resolved_model or _physical_name(table)
    else:
        # Orphan leaf: schema_builder never saw this physical table at all
        # (docs/v0.3-plan.md Risk 2/3) -- still represented, just unresolved.
        model_name = _physical_name(table)

    return ColumnNode(
        model=model_name,
        column=_clean_column_name(node.name),
        layer=layers.get(model_name, "unknown"),
    )


def _resolve_source_name(source_name: str, project_schema: ProjectSchema) -> str | None:
    if not source_name:
        return None
    # Falls back to the raw sources-key string itself if it's somehow not
    # in the map (shouldn't happen -- exp.expand() can only ever set
    # source_name to a key it found in `sources`) rather than raising.
    return project_schema.sources_key_to_model.get(source_name, source_name)


def _physical_name(table: exp.Table) -> str:
    return f"{table.db}.{table.name}" if table.db else table.name


def _clean_column_name(name: str) -> str:
    return name.rsplit(".", 1)[-1]
