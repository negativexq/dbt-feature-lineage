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

    A model-level ref() cycle is handled the same way (see
    resolve_circular_ref_dependencies): the models involved are excluded
    from lineage entirely, and their entries are pruned from
    `project_schema.sources` too -- otherwise a *third*, non-cyclic model
    that merely references one of them would still hand sqlglot's
    exp.expand() a `sources` chain that loops back on itself (verified:
    exp.expand() has no cycle guard of its own and recurses without bound,
    RecursionError, not a clean failure -- docs/v0.3-plan.md Risk 5).
    """

    excluded_models, circular_warnings = resolve_circular_ref_dependencies(project)

    project_schema = build_project_schema(project)
    _exclude_models_from_sources(project_schema, excluded_models)
    dialect = resolve_dialect(project)
    layers = {model.name: model.layer for model in project.models}

    graph: nx.DiGraph = nx.DiGraph()
    lineage_warnings: list[str] = list(circular_warnings)

    for model in project.models:
        if model.name in excluded_models:
            continue
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

    _break_cycles(graph, lineage_warnings)
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


def _break_cycles(graph: nx.DiGraph, lineage_warnings: list[str]) -> None:
    """Drop the minimum edges needed to make `graph` acyclic, in place.

    resolve_circular_ref_dependencies() only checks model-level ref()
    dependencies -- it can't see a column-level cycle that only exists
    because ColumnNode identity is (model, column, layer), not "this exact
    position in the parse tree": a CTE-scoped column that happens to share
    a bare name with another output column of the same model (e.g. both
    named "amount") gets merged into the same graph node even though
    sqlglot's own per-column Node tree never had a cycle, and if that
    shared name is referenced from more than one place the *merged* graph
    can come out cyclic even though every individual sqlglot lineage()
    call that built it was perfectly acyclic. get_upstream_chain/
    get_downstream_chain both require a DAG (nx.topological_sort), so
    rather than let that raise NetworkXUnfeasible and crash the CLI/UI,
    each cycle found is broken by dropping its last edge and reported via
    lineage_warnings -- same "skip and report, never crash or stay
    silent" contract as the SqlglotError handling above.
    """

    while not nx.is_directed_acyclic_graph(graph):
        cycle_edges = nx.find_cycle(graph)
        cycle_nodes = [source for source, _target in cycle_edges]
        cycle_nodes.append(cycle_edges[-1][1])
        path = " -> ".join(f"{node.model}.{node.column}" for node in cycle_nodes)

        source, target = cycle_edges[-1][0], cycle_edges[-1][1]
        graph.remove_edge(source, target)

        lineage_warnings.append(
            f"Circular column lineage detected and truncated ({path}): likely two "
            "differently-scoped columns sharing the same output name within one "
            "model (e.g. a CTE-internal column and a final SELECT column both "
            "named the same thing)."
        )


def resolve_circular_ref_dependencies(project: DbtProject) -> tuple[set[str], list[str]]:
    """Find model-level ref() cycles and report them without raising.

    A real dbt project's ref() graph is always a DAG in practice (dbt
    itself refuses to compile a cyclic one), so this is realistically only
    reachable in static mode -- dependency_parser.py's regex-based ref()
    extraction never goes through dbt's own compile-time validation. Used
    by both build_project_lineage() (column-level) and
    model_dag_service.build_model_dag() (model-level), so it lives here
    rather than duplicated in each -- "the one place that already computes
    this exact model-name graph" beats a second implementation, per
    v0.4-plan.md's `column_search.py` split (avoid two things that only
    look distinct from a granularity difference).

    Returns (excluded_model_names, warnings): every model name that's part
    of at least one cycle, plus one human-readable warning per cycle
    found. A model in the returned set must be treated as opaque/unbuildable
    by the caller -- for build_project_lineage specifically, that means
    excluding it from lineage AND from `sources` (see
    _exclude_models_from_sources), not just skipping it as a trace target.
    """

    model_names = {model.name for model in project.models}
    dependency_graph: nx.DiGraph = nx.DiGraph()
    dependency_graph.add_nodes_from(model_names)

    for model in project.models:
        for dependency in model.ref_dependencies:
            if dependency.target_name in model_names:
                dependency_graph.add_edge(dependency.target_name, model.name)

    excluded_models: set[str] = set()
    warnings: list[str] = []

    while not nx.is_directed_acyclic_graph(dependency_graph):
        cycle = next(iter(nx.simple_cycles(dependency_graph)))
        chain = " -> ".join([*cycle, cycle[0]])
        warnings.append(f"Circular ref() dependency detected and excluded: {chain}")
        excluded_models.update(cycle)
        dependency_graph.remove_nodes_from(cycle)

    return excluded_models, warnings


def _exclude_models_from_sources(project_schema: ProjectSchema, excluded_models: set[str]) -> None:
    """Remove every `sources` entry that resolves back to an excluded model.

    Leaves `project_schema.schema`/`physical_to_model` untouched -- those
    only drive column-name resolution (SELECT * disambiguation), not
    recursive substitution, so an excluded model can still be correctly
    identified as the owner of a leaf node when some other, non-cyclic
    model references it. Only `sources` (what exp.expand() recursively
    inlines) needs pruning to stop the cycle from propagating outward.
    """

    stale_keys = [
        key
        for key, model_name in project_schema.sources_key_to_model.items()
        if model_name in excluded_models
    ]
    for key in stale_keys:
        project_schema.sources.pop(key, None)
        project_schema.sources_key_to_model.pop(key, None)


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
