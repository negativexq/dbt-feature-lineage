"""Pydantic models for dbt project discovery."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Layer = Literal["staging", "intermediate", "marts", "unknown"]
DependencyType = Literal["ref", "source"]


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

    model_config = ConfigDict()
