"""SQL preprocessing and parsing helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlglot import exp, parse_one
from sqlglot.errors import ParseError


@dataclass
class SqlParseResult:
    """A parsed SQL result with dbt placeholder mappings."""

    original_sql: str
    preprocessed_sql: str
    expression: exp.Expression | None
    placeholder_mapping: dict[str, str] = field(default_factory=dict)
    parsing_warnings: list[str] = field(default_factory=list)


def preprocess_dbt_sql(raw_sql: str) -> tuple[str, dict[str, str]]:
    """Replace Jinja ref() and source() calls with parseable placeholders."""

    placeholder_mapping: dict[str, str] = {}
    source_jinja_pattern = re.compile(
        r"""\{\{\s*source\(\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]\s*\)\s*\}\}"""
    )
    ref_jinja_pattern = re.compile(r"""\{\{\s*ref\(\s*['"]([^'"]+)['"]\s*\)\s*\}\}""")

    def replace_source(match: re.Match[str]) -> str:
        source_name = match.group(1)
        table_name = match.group(2)
        placeholder = f"{source_name}__{table_name}"
        placeholder_mapping[placeholder] = match.group(0)
        return placeholder

    def replace_ref(match: re.Match[str]) -> str:
        model_name = match.group(1)
        placeholder_mapping[model_name] = match.group(0)
        return model_name

    processed_sql = source_jinja_pattern.sub(replace_source, raw_sql)
    processed_sql = ref_jinja_pattern.sub(replace_ref, processed_sql)
    processed_sql = re.sub(r"\{\{.*?\}\}", "unknown_macro", processed_sql, flags=re.DOTALL)
    return processed_sql, placeholder_mapping


def restore_placeholders(sql_text: str, placeholder_mapping: dict[str, str]) -> str:
    """Restore dbt placeholders inside rendered SQL text."""

    restored = sql_text
    sorted_mapping = sorted(placeholder_mapping.items(), key=lambda item: -len(item[0]))
    for placeholder, original in sorted_mapping:
        restored = restored.replace(placeholder, original)
    return restored


def parse_sql_with_fallback(raw_sql: str) -> SqlParseResult:
    """Parse SQL while tolerating dbt Jinja and parser failures."""

    preprocessed_sql, placeholder_mapping = preprocess_dbt_sql(raw_sql)
    warnings: list[str] = []

    try:
        expression = parse_one(preprocessed_sql, read="postgres")
    except ParseError as exc:
        expression = None
        warnings.append(f"SQL parsing warning: {exc}")

    return SqlParseResult(
        original_sql=raw_sql,
        preprocessed_sql=preprocessed_sql,
        expression=expression,
        placeholder_mapping=placeholder_mapping,
        parsing_warnings=warnings,
    )
