"""SQL preprocessing and parsing helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

import jinja2
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


class _DbtUndefined(jinja2.ChainableUndefined):
    """What any Jinja name this preprocessor doesn't model (an unset dbt
    var, a `dbt_utils`/custom-package macro, `this`/`target`, ...)
    resolves to. Three behaviors matter here, none of which are
    ChainableUndefined's own default:

    - printed (`{{ x }}`) -> the literal text "unknown_macro", matching
      the old regex-only preprocessor's fallback for any `{{ ... }}` it
      couldn't handle, so callers already tolerant of that placeholder
      keep working unchanged.
    - called (`{{ dbt_utils.pivot(...) }}`) -> returns another Undefined
      instead of raising. Base Undefined raises on call, which would
      otherwise take down the *entire* model's Jinja render (and with
      it every output column, not just the one macro) for the common
      case of a project using one package macro this tool has never
      heard of.
    - iterated (`{% for x in some_undefined_list %}`) -> zero iterations
      instead of raising, so a for-loop driven by an unresolvable
      variable degrades to "no extra columns from this loop" rather
      than crashing the render.
    """

    def __str__(self) -> str:
        return "unknown_macro"

    def __call__(self, *args: object, **kwargs: object) -> "_DbtUndefined":
        return self

    def __iter__(self):
        return iter(())


def preprocess_dbt_sql(raw_sql: str) -> tuple[str, dict[str, str]]:
    """Render a model's dbt Jinja into plain SQL sqlglot can parse.

    Real Jinja2 rendering, not a regex sweep over `{{ ... }}`: a regex
    can strip a `{{ ref(...) }}` call but has no way to *evaluate*
    `{% set %}`/`{% for %}` control flow -- and dynamic-column patterns
    built from a `{% set %}` list and a `{% for %}` loop are common
    enough in real dbt projects (dbt Labs' own jaffle_shop example
    included) that skipping them meant those models failed to parse at
    all, not just lost one macro's worth of information.

    ref()/source() are intercepted as Jinja globals rather than left to
    render as arbitrary text, and still populate `placeholder_mapping`
    with a reconstructed `{{ ref(...) }}`/`{{ source(...) }}` call
    exactly as the old regex version did -- every existing caller
    (query_flow_parser.restore_placeholders, schema_builder's source
    table matching) depends on that placeholder shape, so real Jinja
    rendering changes *how* the substitution happens, not its output.
    """

    placeholder_mapping: dict[str, str] = {}

    def ref(model_name: str, *_args: object, **_kwargs: object) -> str:
        placeholder_mapping[model_name] = f"{{{{ ref('{model_name}') }}}}"
        return model_name

    def source(source_name: str, table_name: str) -> str:
        placeholder = f"{source_name}__{table_name}"
        placeholder_mapping[placeholder] = f"{{{{ source('{source_name}', '{table_name}') }}}}"
        return placeholder

    # keep_trailing_newline=True: Jinja2's default silently drops the raw
    # SQL's own trailing newline (nothing to do with Jinja rendering,
    # just Jinja's default template-source handling) -- this preprocessor's
    # contract is "render Jinja constructs", not "also reformat whitespace
    # the source file never asked to have touched".
    env = jinja2.Environment(undefined=_DbtUndefined, autoescape=False, keep_trailing_newline=True)
    template_globals = {
        "ref": ref,
        "source": source,
        "config": lambda *args, **kwargs: "",
        "var": lambda name, default="": default,
    }

    try:
        template = env.from_string(raw_sql, globals=template_globals)
        processed_sql = template.render()
    except jinja2.TemplateError:
        # Genuinely malformed/unsupported Jinja (rare) -- fall back to
        # the raw SQL untouched rather than losing the whole model's
        # analysis outright; sqlglot's own parse failure just below
        # still produces an honest warning instead of a 500.
        processed_sql = raw_sql

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
