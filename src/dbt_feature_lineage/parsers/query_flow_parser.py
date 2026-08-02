"""Logical SQL query-flow extraction."""

from __future__ import annotations

import re

from sqlglot import exp

from dbt_feature_lineage.domain.models import DbtModelAnalysis, DbtOutputColumn, QueryFlowStep
from dbt_feature_lineage.parsers.sql_parser import (
    SqlParseResult,
    parse_sql_with_fallback,
    restore_placeholders,
)


def analyze_query_flow(raw_sql: str) -> DbtModelAnalysis:
    """Analyze a SQL model and extract logical query-flow details."""

    parse_result = parse_sql_with_fallback(raw_sql)
    if parse_result.expression is None:
        return DbtModelAnalysis(
            model_name="",
            file_path="",
            relative_path="",
            layer="unknown",
            raw_sql=raw_sql,
            parsing_warnings=parse_result.parsing_warnings,
        )

    expression = parse_result.expression
    cte_names = [cte.alias_or_name for cte in expression.find_all(exp.CTE) if cte.alias_or_name]
    table_aliases = _extract_table_aliases(expression, parse_result)
    joins = list(expression.find_all(exp.Join))
    join_types = [_normalize_join_type(join) for join in joins]
    group_by_columns = _extract_group_by_columns(expression, parse_result)
    aggregate_functions = _extract_aggregate_functions(expression)
    window_functions = _extract_window_functions(expression, parse_result)
    output_columns = _extract_output_columns(expression, parse_result)

    return DbtModelAnalysis(
        model_name="",
        file_path="",
        relative_path="",
        layer="unknown",
        raw_sql=raw_sql,
        cte_names=cte_names,
        table_aliases=table_aliases,
        join_count=len(joins),
        join_types=join_types,
        has_where_clause=expression.find(exp.Where) is not None,
        group_by_columns=group_by_columns,
        aggregate_functions=aggregate_functions,
        window_functions=window_functions,
        output_columns=output_columns,
        parsing_warnings=parse_result.parsing_warnings,
    )


def _extract_table_aliases(
    expression: exp.Expression, parse_result: SqlParseResult
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for table in expression.find_all(exp.Table):
        if table.alias:
            relation_name = restore_placeholders(table.name, parse_result.placeholder_mapping)
            aliases[table.alias] = relation_name
    return aliases


def _normalize_join_type(join: exp.Join) -> str:
    parts: list[str] = []
    for arg_name in ("side", "kind", "method"):
        arg_value = join.args.get(arg_name)
        if arg_value is None:
            continue
        parts.append(str(arg_value).upper())
    return " ".join(parts) or "INNER"


def _extract_group_by_columns(
    expression: exp.Expression, parse_result: SqlParseResult
) -> list[str]:
    columns: list[str] = []
    for group in expression.find_all(exp.Group):
        for group_expression in group.expressions:
            rendered = restore_placeholders(
                group_expression.sql(dialect="postgres"),
                parse_result.placeholder_mapping,
            )
            if rendered not in columns:
                columns.append(rendered)
    return columns


def _extract_aggregate_functions(expression: exp.Expression) -> list[str]:
    functions: list[str] = []
    for aggregate in expression.find_all(exp.AggFunc):
        function_name = aggregate.key.upper()
        if function_name not in functions:
            functions.append(function_name)
    return functions


def _extract_window_functions(
    expression: exp.Expression, parse_result: SqlParseResult
) -> list[str]:
    functions: list[str] = []
    for window in expression.find_all(exp.Window):
        rendered = restore_placeholders(
            window.sql(dialect="postgres"),
            parse_result.placeholder_mapping,
        )
        if rendered not in functions:
            functions.append(rendered)
    return functions


def _extract_output_columns(
    expression: exp.Expression, parse_result: SqlParseResult
) -> list[DbtOutputColumn]:
    root_select = _find_root_select(expression)
    if root_select is None:
        return []
    return _output_columns_for_projections(root_select.expressions, parse_result)


def _output_columns_for_projections(
    projections: list[exp.Expression], parse_result: SqlParseResult
) -> list[DbtOutputColumn]:
    output_columns: list[DbtOutputColumn] = []
    for projection in projections:
        alias = projection.alias_or_name or restore_placeholders(
            projection.sql(dialect="postgres"), parse_result.placeholder_mapping
        )
        expression_node = projection.this if isinstance(projection, exp.Alias) else projection
        rendered_expression = restore_placeholders(
            expression_node.sql(dialect="postgres"), parse_result.placeholder_mapping
        )
        output_columns.append(
            DbtOutputColumn(
                output_name=alias,
                original_sql_expression=rendered_expression,
                transformation_type=detect_transformation_type(expression_node, alias),
                referenced_input_columns=_extract_referenced_columns(expression_node),
            )
        )
    return output_columns


def _find_root_select(expression: exp.Expression) -> exp.Select | None:
    root_select = expression if isinstance(expression, exp.Select) else expression.find(exp.Select)
    if root_select is None:
        return None

    resolved_select = _resolve_select_star_from_cte(root_select, expression)
    return resolved_select


def _resolve_select_star_from_cte(
    root_select: exp.Select, expression: exp.Expression
) -> exp.Select:
    if not _is_select_star(root_select):
        return root_select

    from_expression = root_select.args.get("from_") or root_select.args.get("from")
    if from_expression is None or not isinstance(from_expression.this, exp.Table):
        return root_select

    target_name = from_expression.this.name
    for cte in expression.find_all(exp.CTE):
        if cte.alias_or_name == target_name and isinstance(cte.this, exp.Select):
            return _resolve_select_star_from_cte(cte.this, expression)
    return root_select


def _is_select_star(select_expression: exp.Select) -> bool:
    return bool(select_expression.expressions) and all(
        isinstance(projection, exp.Star) for projection in select_expression.expressions
    )


def detect_transformation_type(
    expression_node: exp.Expression, output_name: str
) -> str:
    if isinstance(expression_node, exp.Literal):
        return "constant"
    if expression_node.find(exp.Window) is not None:
        return "window"
    if expression_node.find(exp.Case) is not None or isinstance(expression_node, exp.Case):
        return "conditional"
    if isinstance(expression_node, exp.Cast):
        return "cast"
    if expression_node.find(exp.AggFunc) is not None or isinstance(expression_node, exp.AggFunc):
        return "aggregate"
    if isinstance(expression_node, exp.Column):
        return "rename" if output_name != expression_node.name else "direct"
    if any(
        expression_node.find(binary_type) is not None
        for binary_type in (exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod)
    ):
        return "calculated"
    if isinstance(expression_node, exp.Func):
        return "calculated"
    return "unknown"


def _extract_referenced_columns(expression_node: exp.Expression) -> list[str]:
    referenced_columns: list[str] = []
    for column in expression_node.find_all(exp.Column):
        rendered = f"{column.table}.{column.name}" if column.table else column.name
        if rendered not in referenced_columns:
            referenced_columns.append(rendered)
    return referenced_columns


# ---------------------------------------------------------------------------
# build_query_flow_steps() -- per-CTE flow steps (v0.6, docs/v0.6-plan.md
# Bölüm 3). Deliberately separate from analyze_query_flow()/DbtModelAnalysis
# above: those stay flat/model-wide (CLI `inspect`, Model Explorer's
# existing Query Flow tab keep reading them, unchanged). This is only
# consumed by the new Query Flow diagram.
# ---------------------------------------------------------------------------

_SOURCE_CALL_PATTERN = re.compile(
    r"""\{\{\s*source\(\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]\s*\)\s*\}\}"""
)
_REF_CALL_PATTERN = re.compile(r"""\{\{\s*ref\(\s*['"]([^'"]+)['"]\s*\)\s*\}\}""")


def build_query_flow_steps(raw_sql: str, model_name: str = "") -> list[QueryFlowStep]:
    """Break a model's SQL into an ordered list of QueryFlowStep nodes:
    one per source relation (a ref()'d model or source() table), one per
    CTE, a `final_select` step for the outermost SELECT, and a closing
    `output` step. Returns `[]` when the SQL doesn't parse (same
    tolerant-fallback contract as analyze_query_flow()).

    Each step only carries information that belongs to *itself* --
    reusing the same _extract_* helpers analyze_query_flow() uses, but
    called on that one step's own exp.Select subtree instead of the whole
    expression, which is what actually makes this "per-step" rather than
    the flat, whole-model lists DbtModelAnalysis holds (Bölüm 1's finding).
    """

    parse_result = parse_sql_with_fallback(raw_sql)
    expression = parse_result.expression
    if expression is None:
        return []

    cte_nodes = [cte for cte in expression.find_all(exp.CTE) if cte.alias_or_name]
    cte_names = {cte.alias_or_name for cte in cte_nodes}
    source_steps_by_id: dict[str, str] = {}

    cte_steps: list[QueryFlowStep] = []
    for cte in cte_nodes:
        cte_name = cte.alias_or_name
        cte_select = cte.this if isinstance(cte.this, exp.Select) else None
        upstream_ids = _collect_upstream_step_ids(
            cte.this, cte_names, parse_result.placeholder_mapping, source_steps_by_id
        )
        if cte_select is None:
            cte_steps.append(
                QueryFlowStep(
                    step_id=f"cte:{cte_name}",
                    step_type="cte",
                    name=cte_name,
                    upstream_step_ids=upstream_ids,
                )
            )
            continue
        cte_steps.append(
            QueryFlowStep(
                step_id=f"cte:{cte_name}",
                step_type="cte",
                name=cte_name,
                upstream_step_ids=upstream_ids,
                join_types=_own_join_types(cte_select),
                has_where_clause=cte_select.args.get("where") is not None,
                group_by_columns=_extract_group_by_columns(cte_select, parse_result),
                aggregate_functions=_extract_aggregate_functions(cte_select),
                window_functions=_extract_window_functions(cte_select, parse_result),
                output_columns=_output_columns_for_projections(
                    cte_select.expressions, parse_result
                ),
            )
        )

    root_select = expression if isinstance(expression, exp.Select) else expression.find(exp.Select)
    final_select_step: QueryFlowStep
    if root_select is not None:
        own_root = _strip_with(root_select)
        final_upstream_ids = _collect_upstream_step_ids(
            own_root, cte_names, parse_result.placeholder_mapping, source_steps_by_id
        )
        final_select_step = QueryFlowStep(
            step_id="final_select",
            step_type="final_select",
            name="final_select",
            upstream_step_ids=final_upstream_ids,
            join_types=_own_join_types(own_root),
            has_where_clause=own_root.args.get("where") is not None,
            group_by_columns=_extract_group_by_columns(own_root, parse_result),
            aggregate_functions=_extract_aggregate_functions(own_root),
            window_functions=_extract_window_functions(own_root, parse_result),
            # Output columns intentionally use the *unstripped* expression --
            # _extract_output_columns()'s star-resolution needs to see the
            # CTEs to walk "select * from final" down to final's real
            # columns, exactly like analyze_query_flow() already does.
            output_columns=_extract_output_columns(expression, parse_result),
        )
    else:
        final_select_step = QueryFlowStep(
            step_id="final_select", step_type="final_select", name="final_select"
        )

    output_step = QueryFlowStep(
        step_id="output",
        step_type="output",
        name=model_name,
        upstream_step_ids=["final_select"],
        output_columns=final_select_step.output_columns,
    )

    source_steps = [
        QueryFlowStep(step_id=step_id, step_type="source", name=name)
        for step_id, name in source_steps_by_id.items()
    ]
    return [*source_steps, *cte_steps, final_select_step, output_step]


def _own_join_types(select_node: exp.Select) -> list[str]:
    return [_normalize_join_type(join) for join in select_node.args.get("joins") or []]


def _strip_with(select_node: exp.Select) -> exp.Select:
    """Return `select_node` with its own WITH clause detached, so the
    recursive _extract_* helpers (find_all-based) don't bleed into CTE
    bodies when called on the outermost SELECT -- a CTE's own subtree
    (cte.this) never has this problem since sibling CTEs aren't its
    descendants, only the outer SELECT carries all of them as a `with` arg.
    """

    # This sqlglot version stores the WITH clause under the "with_" arg key
    # (same "_"-suffixed quirk as "from_" -- see _resolve_select_star_from_cte
    # above, which already falls back to "from_" or "from" for that reason).
    with_key = "with_" if select_node.args.get("with_") is not None else "with"
    if select_node.args.get(with_key) is None:
        return select_node
    stripped = select_node.copy()
    stripped.set(with_key, None)
    return stripped


def _collect_upstream_step_ids(
    node: exp.Expression,
    cte_names: set[str],
    placeholder_mapping: dict[str, str],
    source_steps_by_id: dict[str, str],
) -> list[str]:
    upstream_ids: list[str] = []
    for table in node.find_all(exp.Table):
        raw_name = table.name
        if raw_name in cte_names:
            step_id = f"cte:{raw_name}"
        else:
            relation_name = _resolve_relation_name(raw_name, placeholder_mapping)
            step_id = f"source:{relation_name}"
            source_steps_by_id.setdefault(step_id, relation_name)
        if step_id not in upstream_ids:
            upstream_ids.append(step_id)
    return upstream_ids


def _resolve_relation_name(raw_name: str, placeholder_mapping: dict[str, str]) -> str:
    original = placeholder_mapping.get(raw_name)
    if original is None:
        return raw_name
    source_match = _SOURCE_CALL_PATTERN.match(original)
    if source_match:
        return f"{source_match.group(1)}.{source_match.group(2)}"
    ref_match = _REF_CALL_PATTERN.match(original)
    if ref_match:
        return ref_match.group(1)
    return raw_name
