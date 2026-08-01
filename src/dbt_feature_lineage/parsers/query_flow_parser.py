"""Logical SQL query-flow extraction."""

from __future__ import annotations

from sqlglot import exp

from dbt_feature_lineage.domain.models import DbtModelAnalysis, DbtOutputColumn
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

    output_columns: list[DbtOutputColumn] = []
    for projection in root_select.expressions:
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
