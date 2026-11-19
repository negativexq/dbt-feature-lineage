"""dbt 2.0 upgrade readiness: a static scan of a project's YAML for the
patterns dbt 2.0's stricter spec rejects.

No dbt install needed -- the point is to answer "what breaks if we move to
dbt 2.0?" from a project still on 1.x. Every rule here was checked against
dbt-oss 2.0.11's own `dbt parse` output (see tests/test_upgrade_readiness.py
and docs in README): a top-level property dbt 2.0 now wants under
`config:` is *ignored* with an UnusedConfigKey error -- so, for example,
a model's `meta: {owner: ...}` silently disappears from the manifest --
and generic-test keyword arguments must move under `arguments:`.
Line numbers come from PyYAML's composed node marks, so each finding
points at the exact key to change.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

Severity = Literal["blocker", "error", "info"]

# Adapters dbt 2.0.11 parses without DBT_ALLOW_EXPERIMENTAL_ADAPTERS.
STABLE_V2_ADAPTERS = frozenset(
    {"snowflake", "bigquery", "databricks", "redshift", "duckdb", "salesforce", "clickhouse"}
)

# Properties dbt 2.0 only accepts under `config:` -- per resource kind.
_MOVED_TO_CONFIG: dict[str, frozenset[str]] = {
    "model": frozenset({"meta", "tags", "docs"}),
    "seed": frozenset({"meta", "tags", "docs"}),
    "snapshot": frozenset({"meta", "tags", "docs"}),
    "column": frozenset({"meta", "tags"}),
    "source": frozenset({"meta", "tags", "freshness", "loaded_at_field"}),
    "source_table": frozenset({"meta", "tags", "freshness", "loaded_at_field"}),
}

# Keys a generic test entry may carry next to `arguments:` itself.
_TEST_ENTRY_KEYS = frozenset(
    {
        "arguments",
        "config",
        "name",
        "description",
        "column_name",
        "severity",
        "where",
        "tags",
        "meta",
        "enabled",
        "store_failures",
        "store_failures_as",
        "error_if",
        "warn_if",
        "limit",
        "fail_calc",
    }
)

_SKIP_DIRS = frozenset({"target", "dbt_packages", "dbt_modules", "logs", "node_modules", ".venv"})
_VAR_CALL = re.compile(r"""var\(\s*['"](?P<name>[^'"]+)['"]""")


@dataclass(frozen=True)
class ReadinessFinding:
    rule: str
    severity: Severity
    file: str
    line: int | None
    message: str
    fix: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_upgrade_readiness(project_path: str | Path) -> list[ReadinessFinding]:
    """Every dbt 2.0 incompatibility found in the project, most severe first."""

    root = Path(project_path).expanduser().resolve()
    findings: list[ReadinessFinding] = []
    findings.extend(_check_project_vars(root))
    findings.extend(_check_adapter(root))
    for yaml_file in _yaml_files(root):
        findings.extend(_check_properties_file(root, yaml_file))

    order = {"blocker": 0, "error": 1, "info": 2}
    return sorted(findings, key=lambda f: (order[f.severity], f.file, f.line or 0, f.rule))


def summarize(findings: list[ReadinessFinding]) -> dict[str, int]:
    summary = {"blocker": 0, "error": 0, "info": 0}
    for finding in findings:
        summary[finding.severity] += 1
    return summary


# ---------------------------------------------------------------------------
# dbt_project.yml / profiles.yml
# ---------------------------------------------------------------------------


def _check_project_vars(root: Path) -> list[ReadinessFinding]:
    project_file = root / "dbt_project.yml"
    document = _compose(project_file)
    vars_node = _mapping_get(document, "vars")
    if not isinstance(vars_node, yaml.MappingNode):
        return []

    findings = []
    for key_node, value_node in vars_node.value:
        if not isinstance(value_node, yaml.ScalarNode):
            continue
        for match in _VAR_CALL.finditer(str(value_node.value)):
            if match.group("name") == key_node.value:
                findings.append(
                    ReadinessFinding(
                        rule="self_referencing_var",
                        severity="blocker",
                        file="dbt_project.yml",
                        line=key_node.start_mark.line + 1,
                        message=(
                            f"var '{key_node.value}' defaults to var('{key_node.value}') — "
                            "dbt 2.0 crashes while parsing a project that resolves it."
                        ),
                        fix=(
                            "Give it a literal default; callers already pass their own "
                            "fallback via var(name, default)."
                        ),
                    )
                )
    return findings


def _check_adapter(root: Path) -> list[ReadinessFinding]:
    from dbt_feature_lineage.loaders.artifact_detector import _resolve_profiles_dir

    project = _load_yaml(root / "dbt_project.yml")
    profile_name = project.get("profile") if isinstance(project, dict) else None
    profiles_dir = _resolve_profiles_dir(root)
    if not profile_name or profiles_dir is None:
        return []
    profiles_file = profiles_dir / "profiles.yml"
    profiles = _load_yaml(profiles_file)
    profile = profiles.get(profile_name) if isinstance(profiles, dict) else None
    if not isinstance(profile, dict):
        return []
    outputs = profile.get("outputs") or {}
    target = outputs.get(profile.get("target")) if isinstance(outputs, dict) else None
    adapter = target.get("type") if isinstance(target, dict) else None
    if not adapter or adapter in STABLE_V2_ADAPTERS:
        return []
    return [
        ReadinessFinding(
            rule="experimental_adapter",
            severity="info",
            file=_display_path(root, profiles_file),
            line=None,
            message=(
                f"The '{adapter}' adapter is experimental in dbt 2.0: dbt refuses to run "
                "unless DBT_ALLOW_EXPERIMENTAL_ADAPTERS=true is set."
            ),
            fix=(
                "Set DBT_ALLOW_EXPERIMENTAL_ADAPTERS=true, or stay on dbt 1.x for this "
                "warehouse (this tool sets it for its own `dbt parse` runs)."
            ),
        )
    ]


# ---------------------------------------------------------------------------
# Properties (schema) YAML files
# ---------------------------------------------------------------------------


def _check_properties_file(root: Path, path: Path) -> list[ReadinessFinding]:
    document = _compose(path)
    if not isinstance(document, yaml.MappingNode):
        return []
    rel = _display_path(root, path)
    findings: list[ReadinessFinding] = []

    for kind in ("models", "seeds", "snapshots"):
        for entry in _sequence_items(_mapping_get(document, kind)):
            findings.extend(_moved_keys(rel, entry, kind[:-1]))
            findings.extend(_test_findings(rel, entry))
            for column in _sequence_items(_mapping_get(entry, "columns")):
                findings.extend(_moved_keys(rel, column, "column"))
                findings.extend(_test_findings(rel, column))

    for source in _sequence_items(_mapping_get(document, "sources")):
        findings.extend(_moved_keys(rel, source, "source"))
        for table in _sequence_items(_mapping_get(source, "tables")):
            findings.extend(_moved_keys(rel, table, "source_table"))
            findings.extend(_test_findings(rel, table))
            for column in _sequence_items(_mapping_get(table, "columns")):
                findings.extend(_moved_keys(rel, column, "column"))
                findings.extend(_test_findings(rel, column))

    return findings


def _moved_keys(rel: str, node: yaml.Node, kind: str) -> list[ReadinessFinding]:
    if not isinstance(node, yaml.MappingNode):
        return []
    name = _scalar(_mapping_get(node, "name")) or "?"
    label = kind.replace("_", " ")
    findings = []
    for key_node, _value in node.value:
        key = key_node.value
        if key in _MOVED_TO_CONFIG[kind]:
            consequence = (
                " — the owner and every other meta field vanish from the manifest"
                if key == "meta"
                else ""
            )
            findings.append(
                ReadinessFinding(
                    rule="property_moved_to_config",
                    severity="error",
                    file=rel,
                    line=key_node.start_mark.line + 1,
                    message=(
                        f"`{key}` on {label} '{name}' must be under `config:`; dbt 2.0 "
                        f"ignores it here{consequence}."
                    ),
                    fix=f"Move it to `config: {{{key}: ...}}` (valid since dbt 1.10).",
                )
            )
    return findings


def _test_findings(rel: str, node: yaml.Node) -> list[ReadinessFinding]:
    findings: list[ReadinessFinding] = []
    for test_key in ("data_tests", "tests"):
        tests_node = _mapping_get(node, test_key)
        if tests_node is None:
            continue
        if test_key == "tests":
            key_node = _mapping_key(node, "tests")
            findings.append(
                ReadinessFinding(
                    rule="tests_key_renamed",
                    severity="info",
                    file=rel,
                    line=key_node.start_mark.line + 1 if key_node else None,
                    message="`tests:` is deprecated in favor of `data_tests:` (dbt 1.8+).",
                    fix="Rename the key to `data_tests:`; dbt 2.0.11 still accepts the old one.",
                )
            )
        for test in _sequence_items(tests_node):
            if not isinstance(test, yaml.MappingNode) or len(test.value) != 1:
                continue
            test_name_node, body = test.value[0]
            if not isinstance(body, yaml.MappingNode):
                continue
            loose_nodes = sorted(
                (k for k, _ in body.value if k.value not in _TEST_ENTRY_KEYS),
                key=lambda k: k.value,
            )
            loose = [k.value for k in loose_nodes]
            if loose:
                findings.append(
                    ReadinessFinding(
                        rule="test_arguments_top_level",
                        severity="error",
                        file=rel,
                        # Same anchor dbt 2.0 reports: the alphabetically first
                        # offending key.
                        line=loose_nodes[0].start_mark.line + 1,
                        message=(
                            f"Test `{test_name_node.value}` passes "
                            f"{', '.join(f'`{k}`' for k in loose)} at the top level; dbt 2.0 "
                            "rejects that."
                        ),
                        fix="Nest them under `arguments:` (valid since dbt 1.10.5).",
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------


def _yaml_files(root: Path) -> list[Path]:
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for filename in filenames:
            if filename.endswith((".yml", ".yaml")) and filename not in {
                "dbt_project.yml",
                "profiles.yml",
                "packages.yml",
                "dependencies.yml",
                "selectors.yml",
            }:
                files.append(Path(dirpath) / filename)
    return sorted(files)


def _compose(path: Path) -> yaml.Node | None:
    try:
        return yaml.compose(path.read_text(encoding="utf-8"), Loader=yaml.SafeLoader)
    except (OSError, yaml.YAMLError):
        return None


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None


def _mapping_key(node: yaml.Node | None, key: str) -> yaml.Node | None:
    if isinstance(node, yaml.MappingNode):
        for key_node, _value in node.value:
            if key_node.value == key:
                return key_node
    return None


def _mapping_get(node: yaml.Node | None, key: str) -> yaml.Node | None:
    if isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            if key_node.value == key:
                return value_node
    return None


def _sequence_items(node: yaml.Node | None) -> list[yaml.Node]:
    return list(node.value) if isinstance(node, yaml.SequenceNode) else []


def _scalar(node: yaml.Node | None) -> str | None:
    return str(node.value) if isinstance(node, yaml.ScalarNode) else None


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)
