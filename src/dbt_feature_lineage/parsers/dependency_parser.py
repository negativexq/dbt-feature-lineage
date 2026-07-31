"""Regex-based extraction of dbt dependencies."""

from __future__ import annotations

import re

from dbt_feature_lineage.domain.models import DbtDependency

REF_PATTERN = re.compile(r"""ref\(\s*['"]([^'"]+)['"]\s*\)""")
SOURCE_PATTERN = re.compile(
    r"""source\(\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]\s*\)"""
)


def parse_ref_dependencies(raw_sql: str) -> list[DbtDependency]:
    """Extract ref() calls from raw SQL."""

    return [
        DbtDependency(dependency_type="ref", target_name=match)
        for match in REF_PATTERN.findall(raw_sql)
    ]


def parse_source_dependencies(raw_sql: str) -> list[DbtDependency]:
    """Extract source() calls from raw SQL."""

    return [
        DbtDependency(
            dependency_type="source",
            source_name=source_name,
            target_name=table_name,
        )
        for source_name, table_name in SOURCE_PATTERN.findall(raw_sql)
    ]

