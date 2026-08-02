"""Search & retrieve API over a built column lineage graph.

Kept separate from lineage_service.py (which only builds the graph) and
from schema_builder.py (which only builds sqlglot's schema/sources) --
this module's job is exclusively "given an already-built graph, look
things up in it", the third distinct concern in the pipeline (see
docs/v0.4-plan.md Bölüm 2).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from dbt_feature_lineage.domain.lineage import ColumnNode
from dbt_feature_lineage.domain.models import DbtProject, Layer
from dbt_feature_lineage.services.schema_builder import build_project_schema


def build_search_index(graph: nx.DiGraph) -> dict[str, list[ColumnNode]]:
    """Group every ColumnNode in the graph by its bare column name.

    Exact match only -- substring/case-insensitive search belongs at the
    UI layer (matching the existing ui.rendering.filter_models/
    filter_output_columns convention), not baked into the index itself.
    """

    index: dict[str, list[ColumnNode]] = {}
    for node in graph.nodes:
        index.setdefault(node.column, []).append(node)

    for nodes in index.values():
        nodes.sort(key=lambda node: node.model)

    return index


def get_upstream_chain(graph: nx.DiGraph, target: ColumnNode) -> list[ColumnNode]:
    """The target plus every ancestor, in topological (source-first) order.

    Edges run source (upstream) -> target (downstream) (see
    lineage_service.build_project_lineage), so nx.ancestors(graph, target)
    is directly "everything upstream of target" -- no direction flip
    needed. The result is a flat, topologically-sorted list rather than a
    single linear path: a column fed by more than one upstream input
    (e.g. `coalesce(a.x, b.x)`) has a genuinely branching ancestor DAG, not
    one arrow-chain, and the caller (CLI/UI) is expected to render that
    accordingly (docs/v0.4-plan.md Bölüm 3).
    """

    ancestors = nx.ancestors(graph, target)
    subgraph = graph.subgraph({*ancestors, target})
    return list(nx.topological_sort(subgraph))


def get_downstream_chain(graph: nx.DiGraph, target: ColumnNode) -> list[ColumnNode]:
    """The target plus every descendant, in topological (source-first) order.

    Symmetric to get_upstream_chain: edges run source (upstream) -> target
    (downstream), so nx.descendants(graph, target) is directly "everything
    downstream of target" -- everything that (transitively) consumes it.
    Just like the upstream case, the result is a flat, topologically-sorted
    list rather than a single linear path: a column consumed by more than
    one downstream output has a genuinely branching descendant DAG.
    """

    descendants = nx.descendants(graph, target)
    subgraph = graph.subgraph({target, *descendants})
    return list(nx.topological_sort(subgraph))


@dataclass
class FeatureMatch:
    """One model's own metadata for a column name it produces -- Feature
    Explorer's (v0.7) row shape, not a lineage graph node. Deliberately
    not ColumnNode: ColumnNode's job is graph-node identity/hashability
    (frozen, used as an nx.DiGraph key); FeatureMatch never goes in a
    graph, it's a plain comparison-view row, so it carries the extra
    description/owner/tags/test_count fields ColumnNode has no reason to.
    """

    model: str
    column: str
    layer: Layer
    description: str | None = None
    owner: str | None = None
    tags: list[str] = field(default_factory=list)
    test_count: int = 0


def build_feature_index(project: DbtProject) -> dict[str, list[FeatureMatch]]:
    """Group every model's own output columns by column name, each
    carrying that model's own description/owner/tags/test_count.

    Built on build_project_schema().columns_by_model, NOT on a lineage
    graph (build_search_index()'s input) -- Feature Explorer never
    traces an edge, only "which models produce this column name and
    what's each one's own metadata", and columns_by_model is ~300x
    cheaper to obtain than a full build_project_lineage() lineage graph
    (measured on real fixtures, docs/v0.7-plan.md Bölüm 1). Static-mode
    projects simply get FeatureMatch rows with every metadata field at
    its default (None/[]/0) -- never omitted or fabricated.
    """

    project_schema = build_project_schema(project)
    models_by_name = {model.name: model for model in project.models}

    index: dict[str, list[FeatureMatch]] = {}
    for model_name, column_names in project_schema.columns_by_model.items():
        model = models_by_name.get(model_name)
        if model is None:
            continue
        # A model's own output column list isn't guaranteed duplicate-free
        # (schema_builder doesn't dedupe it) -- one FeatureMatch per
        # distinct name, not one per raw_sql occurrence.
        for column_name in set(column_names):
            index.setdefault(column_name, []).append(
                FeatureMatch(
                    model=model.name,
                    column=column_name,
                    layer=model.layer,
                    description=model.description,
                    owner=model.owner,
                    tags=model.tags,
                    test_count=model.test_count,
                )
            )

    for matches in index.values():
        matches.sort(key=lambda match: match.model)

    return index


@dataclass
class ModelImpact:
    """One model's share of a downstream impact summary: which of its
    own columns are (directly or transitively) fed by the traced target."""

    model: str
    columns: list[str] = field(default_factory=list)


@dataclass
class DownstreamImpactSummary:
    """Model-grouped view of a get_downstream_chain() result (v0.8).

    `direct` and `all_impacted` are not two disjoint sets -- `direct`
    (target's immediate successors, grouped by model) is always a
    subset of `all_impacted` (the whole chain minus the target itself,
    grouped by model); `direct` exists to call out "this will break
    immediately" separately from "this is transitively affected"
    (docs/v0.8-plan.md Bölüm 2). Both lists are sorted by descending
    column count (ties broken alphabetically by model name) -- the
    model with the most affected columns is the one most worth a
    reviewer's attention first.
    """

    affected_model_count: int
    affected_column_count: int
    direct: list[ModelImpact]
    all_impacted: list[ModelImpact]


def _group_by_model(nodes: list[ColumnNode]) -> list[ModelImpact]:
    grouped: dict[str, list[str]] = {}
    for node in nodes:
        grouped.setdefault(node.model, []).append(node.column)

    impacts = [ModelImpact(model=model, columns=columns) for model, columns in grouped.items()]
    impacts.sort(key=lambda impact: (-len(impact.columns), impact.model))
    return impacts


def summarize_downstream_impact(
    graph: nx.DiGraph, target: ColumnNode, chain: list[ColumnNode]
) -> DownstreamImpactSummary:
    """Group a get_downstream_chain(graph, target) result by model.

    Takes `chain` as an argument rather than recomputing it -- the
    caller (CLI/Column Lineage page) already has it from calling
    get_downstream_chain() for its own rendering, and re-deriving the
    same nx.descendants() traversal here would be pure waste (this
    function's own cost is negligible by comparison -- measured
    ~0.05ms even on the widest real fixture chain, docs/v0.8-plan.md
    Bölüm 4).

    `chain` always includes `target` itself (get_downstream_chain's own
    contract) -- excluded here since a column isn't its own downstream
    impact. Model names are deduplicated: the same model showing up
    under many different columns in the chain (a mart with a dozen
    columns all tracing back to one raw source, say) counts as ONE
    affected model, not one per column -- see FeatureMatch/build_feature_index's
    similar per-model grouping in this same module for the same reasoning.
    """

    downstream_nodes = [node for node in chain if node != target]
    direct_nodes = list(graph.successors(target))

    return DownstreamImpactSummary(
        affected_model_count=len({node.model for node in downstream_nodes}),
        affected_column_count=len(downstream_nodes),
        direct=_group_by_model(direct_nodes),
        all_impacted=_group_by_model(downstream_nodes),
    )
