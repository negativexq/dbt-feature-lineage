"""Builds a project-wide sqlglot schema for the column lineage engine.

sqlglot.lineage.lineage() only needs a schema to resolve `SELECT *` and
disambiguate same-named columns across joined tables (see
docs/v0.3-plan.md Bölüm 2) -- column *types* are never required, only
column *names*, so every column here is given the same placeholder type.

sqlglot's MappingSchema requires one consistent nesting depth across the
*entire* schema dict (verified empirically -- mixing "schema.table" and
"database.schema.table" keys raises a SchemaError). A single project is
always uniformly manifest mode or static mode, so this is naturally
satisfied: manifest mode nests two levels deep (schema -> table), static
mode is flat (bare model/source-placeholder name -> columns). A model or
source that can't be placed at its mode's depth is never silently
dropped -- see `ProjectSchema.schema_warnings`.

sqlglot.lineage.lineage() eagerly parses *every* value in `sources` on
every call (not just the ones actually referenced by the SQL being
traced), so raw_sql going into `sources`/`raw_sql_by_model` must always
be Jinja-preprocessed first via sql_parser.preprocess_dbt_sql() --
otherwise a single unresolved `{{ ref()/source() }}` anywhere in the
project (e.g. a manifest-mode model that `dbt parse` didn't compile,
per v0.2's finding that compiled_code isn't always populated) would
break lineage for every *other* model too. This is a no-op for SQL
that's already clean (compiled manifest SQL has no Jinja left).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dbt_feature_lineage.domain.models import DbtModel, DbtProject, DbtSource, DbtSourceTable
from dbt_feature_lineage.parsers.query_flow_parser import analyze_query_flow
from dbt_feature_lineage.parsers.sql_parser import preprocess_dbt_sql

_UNKNOWN_TYPE = "unknown"


@dataclass
class ProjectSchema:
    """sqlglot-ready schema/sources for a whole project.

    schema: sqlglot MappingSchema-shaped dict (see module docstring for
        nesting-depth rules).
    sources: flat dict of {table-reference-string: model SQL}, passed as
        sqlglot.lineage.lineage()'s `sources` kwarg to expand cross-model
        references in a single call. A model may appear under several
        plausible reference-string variants (bare name, schema-qualified,
        database-qualified) since sqlglot matches `sources` keys against
        the literal text of the table reference in the querying SQL, and
        different downstream models may reference the same table differently.
    physical_to_model: maps a (schema_or_None, table_or_model_name) key --
        the same shape used as a `schema` leaf -- back to the dbt model
        name that produced it. A value of None means the key resolved to a
        known dbt *source* (a terminal leaf, not a model to recurse into).
        A key that's simply absent means an unresolved/orphan leaf.
    schema_warnings: models or sources the builder could not place in
        `schema` -- e.g. columns couldn't be parsed, or (manifest mode)
        schema/alias metadata was missing. Lineage touching them may
        resolve incompletely or incorrectly; this must be surfaced to the
        caller, never dropped silently (docs/v0.3-plan.md Risk 1).
    raw_sql_by_model: model.name -> model.raw_sql, so callers (the lineage
        engine) don't need to re-walk `project.models` to find the SQL for
        a model they already know the name of.
    columns_by_model: model.name -> its output column names, reusing the
        same analyze_query_flow() pass already spent building `schema`
        instead of re-parsing the model's SQL again downstream.
    sources_key_to_model: maps every key registered in `sources` (bare
        name, schema-qualified, database-qualified) back to the same
        clean model.name. sqlglot's lineage.Node.source_name is always
        one of these `sources` keys verbatim (it's set from whichever key
        exp.expand() matched), never a dbt model name on its own -- so
        resolving a Node's owning model from its source_name must go
        through this map, not use source_name directly as the model name
        (see lineage_service._convert_node).
    """

    schema: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    physical_to_model: dict[tuple[str | None, str], str | None] = field(default_factory=dict)
    schema_warnings: list[str] = field(default_factory=list)
    raw_sql_by_model: dict[str, str] = field(default_factory=dict)
    columns_by_model: dict[str, list[str]] = field(default_factory=dict)
    sources_key_to_model: dict[str, str] = field(default_factory=dict)


def build_project_schema(project: DbtProject) -> ProjectSchema:
    """Build the sqlglot schema/sources/reverse-lookup for an entire project."""

    project_schema = ProjectSchema()
    is_manifest_mode = project.source == "manifest"

    for model in project.models:
        _add_model(project_schema, model, is_manifest_mode)

    for source in project.sources:
        for table in source.tables:
            _add_source_table(project_schema, source, table, is_manifest_mode)

    return project_schema


def _add_model(project_schema: ProjectSchema, model: DbtModel, is_manifest_mode: bool) -> None:
    preprocessed_sql, _ = preprocess_dbt_sql(model.raw_sql)
    project_schema.raw_sql_by_model[model.name] = preprocessed_sql
    columns = _model_columns(model, project_schema)

    if not is_manifest_mode:
        project_schema.schema[model.name] = columns
        project_schema.physical_to_model[(None, model.name)] = model.name
        project_schema.sources[model.name] = preprocessed_sql
        project_schema.sources_key_to_model[model.name] = model.name
        return

    if model.schema_name and model.alias:
        project_schema.schema.setdefault(model.schema_name, {})[model.alias] = columns
        project_schema.physical_to_model[(model.schema_name, model.alias)] = model.name
        _register_model_sources(project_schema, model, preprocessed_sql)
        return

    # Can't place this model at the manifest mode's consistent nesting
    # depth without corrupting it for every other model, so it's excluded
    # from `schema` -- but still registered in `sources` (a flat dict with
    # no depth constraint) so at least cross-model substitution still works.
    project_schema.schema_warnings.append(
        f"Model '{model.name}' is missing schema/alias metadata; excluded from "
        "the lineage schema (SELECT * against it, or ambiguous column "
        "references to it, may resolve incorrectly)."
    )
    project_schema.physical_to_model[(None, model.name)] = model.name
    project_schema.sources[model.name] = preprocessed_sql
    project_schema.sources_key_to_model[model.name] = model.name


def _model_columns(model: DbtModel, project_schema: ProjectSchema) -> dict[str, str]:
    analysis = analyze_query_flow(model.raw_sql)
    column_names = [column.output_name for column in analysis.output_columns]
    project_schema.columns_by_model[model.name] = column_names

    if not column_names:
        detail = "; ".join(analysis.parsing_warnings) or "SQL did not parse as a SELECT"
        project_schema.schema_warnings.append(
            f"No output columns could be determined for model '{model.name}' ({detail})."
        )

    return {name: _UNKNOWN_TYPE for name in column_names}


def _register_model_sources(
    project_schema: ProjectSchema, model: DbtModel, preprocessed_sql: str
) -> None:
    keys = [model.name, f"{model.schema_name}.{model.alias}"]
    if model.database:
        keys.append(f"{model.database}.{model.schema_name}.{model.alias}")

    for key in keys:
        project_schema.sources[key] = preprocessed_sql
        project_schema.sources_key_to_model[key] = model.name


def _add_source_table(
    project_schema: ProjectSchema,
    source: DbtSource,
    table: DbtSourceTable,
    is_manifest_mode: bool,
) -> None:
    columns = {column: _UNKNOWN_TYPE for column in table.columns}

    if not is_manifest_mode:
        # Matches sql_parser.preprocess_dbt_sql()'s {{ source(...) }} placeholder
        # exactly, so it lines up with how source() calls appear in the SQL
        # that's actually fed to sqlglot in static mode.
        table_key = f"{source.name}__{table.name}"
        project_schema.schema[table_key] = columns
        project_schema.physical_to_model[(None, table_key)] = None
        return

    table_key = table.identifier or table.name

    if not source.schema_name:
        project_schema.schema_warnings.append(
            f"Source '{source.name}.{table.name}' is missing schema metadata; "
            "excluded from the lineage schema."
        )
        return

    project_schema.schema.setdefault(source.schema_name, {})[table_key] = columns
    project_schema.physical_to_model[(source.schema_name, table_key)] = None
