"""Search & retrieve API over a built column lineage graph.

Kept separate from lineage_service.py (which only builds the graph) and
from schema_builder.py (which only builds sqlglot's schema/sources) --
this module's job is exclusively "given an already-built graph, look
things up in it", the third distinct concern in the pipeline (see
docs/v0.4-plan.md Bölüm 2).
"""

from __future__ import annotations

import networkx as nx

from dbt_feature_lineage.domain.lineage import ColumnNode


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
