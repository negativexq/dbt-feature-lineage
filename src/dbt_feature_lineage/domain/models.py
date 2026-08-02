"""Pydantic models for dbt project discovery."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Layer = Literal["staging", "intermediate", "marts", "unknown"]
DependencyType = Literal["ref", "source"]
TransformationType = Literal[
    "direct",
    "rename",
    "cast",
    "aggregate",
    "calculated",
    "conditional",
    "window",
    "constant",
    "unknown",
]


class DbtDependency(BaseModel):
    """A dbt dependency extracted from SQL."""

    dependency_type: DependencyType
    target_name: str
    source_name: str | None = None


class DbtModel(BaseModel):
    """A dbt model discovered from a SQL file."""

    name: str
    file_path: str
    relative_path: str
    layer: Layer
    raw_sql: str
    ref_dependencies: list[DbtDependency] = Field(default_factory=list)
    source_dependencies: list[DbtDependency] = Field(default_factory=list)
    unique_id: str | None = None
    materialization: str | None = None
    compiled: bool = False
    database: str | None = None
    schema_name: str | None = Field(default=None, alias="schema")
    alias: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    owner: str | None = None
    test_count: int = 0
    model_group: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class DbtSourceTable(BaseModel):
    """A source table defined in dbt YAML."""

    name: str
    identifier: str | None = None
    description: str | None = None
    columns: list[str] = Field(default_factory=list)


class DbtSource(BaseModel):
    """A dbt source definition."""

    name: str
    database: str | None = None
    schema_name: str | None = Field(default=None, alias="schema")
    description: str | None = None
    tables: list[DbtSourceTable] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)


class ArtifactStatus(BaseModel):
    """Outcome of the manifest-vs-static artifact resolution for a project load."""

    mode: Literal["manifest", "static"]
    reason: str
    message: str = ""
    dbt_version: str | None = None


class DbtProject(BaseModel):
    """A discovered dbt project."""

    name: str
    project_path: str
    dbt_project_file: str
    model_paths: list[str]
    yaml_files: list[str] = Field(default_factory=list)
    models: list[DbtModel] = Field(default_factory=list)
    sources: list[DbtSource] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: Literal["manifest", "static"] = "static"
    artifact_status: ArtifactStatus | None = None

    model_config = ConfigDict()


class DbtOutputColumn(BaseModel):
    """A parsed output column from a model select statement."""

    output_name: str
    original_sql_expression: str
    transformation_type: TransformationType
    referenced_input_columns: list[str] = Field(default_factory=list)


class DbtModelAnalysis(BaseModel):
    """Inspection details for a dbt model."""

    model_name: str
    file_path: str
    relative_path: str
    layer: Layer
    raw_sql: str
    ref_dependencies: list[DbtDependency] = Field(default_factory=list)
    source_dependencies: list[DbtDependency] = Field(default_factory=list)
    cte_names: list[str] = Field(default_factory=list)
    table_aliases: dict[str, str] = Field(default_factory=dict)
    join_count: int = 0
    join_types: list[str] = Field(default_factory=list)
    has_where_clause: bool = False
    group_by_columns: list[str] = Field(default_factory=list)
    aggregate_functions: list[str] = Field(default_factory=list)
    window_functions: list[str] = Field(default_factory=list)
    output_columns: list[DbtOutputColumn] = Field(default_factory=list)
    parsing_warnings: list[str] = Field(default_factory=list)
