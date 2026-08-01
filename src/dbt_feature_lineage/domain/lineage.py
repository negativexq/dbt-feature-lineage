"""Domain types for column-level lineage graphs.

Kept separate from domain/models.py: that module represents the "project
discovery" domain (filesystem scan, YAML, dependency regexes), while this
one represents the lineage graph itself -- node-identity/hashability and
graph-library (networkx) concerns that don't belong alongside it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from dbt_feature_lineage.domain.models import Layer, TransformationType


class ColumnNode(BaseModel):
    """A single column produced by a dbt model; a lineage graph node key."""

    model: str
    column: str
    layer: Layer

    model_config = ConfigDict(frozen=True)


class ColumnEdge(BaseModel):
    """A directed lineage edge from an upstream column to a downstream one."""

    source: ColumnNode
    target: ColumnNode
    transformation_type: TransformationType
    expression_sql: str
