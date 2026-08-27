/**
 * A small hand-rolled SQL tokenizer instead of pulling in a highlighting
 * library (prismjs/highlight.js) for one <pre> block -- dbt SQL is a
 * narrow enough dialect (SELECT/CTE/window functions, no procedural
 * blocks) that a single regex pass covers it, and it keeps this at a
 * few KB instead of a real dependency. Not a general-purpose SQL
 * parser: good enough to read at a glance, not to validate syntax.
 */

const KEYWORDS = new Set([
  "select", "from", "where", "join", "left", "right", "inner", "outer", "full", "on", "as",
  "with", "group", "by", "order", "having", "limit", "offset", "union", "all", "distinct",
  "case", "when", "then", "else", "end", "and", "or", "not", "in", "is", "null", "like",
  "ilike", "between", "over", "partition", "asc", "desc", "insert", "into", "values",
  "update", "set", "delete", "create", "table", "view", "using", "cross", "exists", "cast",
  "materialized", "returns", "language", "true", "false", "filter", "qualify", "rows",
  "range", "unbounded", "preceding", "following", "current", "row", "lateral", "unnest",
]);

const TOKEN_RE =
  /(--[^\n]*)|(\/\*[\s\S]*?\*\/)|('(?:[^'\\]|\\.)*')|(\b\d+\.?\d*\b)|([A-Za-z_][A-Za-z0-9_]*)|([(),;])|(\s+)|(.)/g;

interface Token {
  text: string;
  color?: string;
  italic?: boolean;
}

function tokenize(sql: string): Token[] {
  const tokens: Token[] = [];
  let match: RegExpExecArray | null;
  TOKEN_RE.lastIndex = 0;
  while ((match = TOKEN_RE.exec(sql))) {
    const [full, lineComment, blockComment, string, number, word] = match;
    if (lineComment || blockComment) {
      tokens.push({ text: full, color: "var(--syntax-comment)", italic: true });
    } else if (string) {
      tokens.push({ text: full, color: "var(--syntax-string)" });
    } else if (number) {
      tokens.push({ text: full, color: "var(--syntax-number)" });
    } else if (word) {
      const lower = word.toLowerCase();
      const nextChar = sql[TOKEN_RE.lastIndex];
      if (KEYWORDS.has(lower)) {
        tokens.push({ text: full, color: "var(--syntax-keyword)" });
      } else if (nextChar === "(") {
        tokens.push({ text: full, color: "var(--syntax-function)" });
      } else {
        tokens.push({ text: full });
      }
    } else {
      tokens.push({ text: full });
    }
  }
  return tokens;
}

export function SqlCode({ sql, className = "" }: { sql: string; className?: string }) {
  const tokens = tokenize(sql);
  return (
    <pre className={`overflow-auto rounded-lg border border-line bg-ink-950 p-4 font-mono text-sm ${className}`}>
      <code>
        {tokens.map((t, i) => (
          <span key={i} style={{ color: t.color ?? "var(--text-hi)", fontStyle: t.italic ? "italic" : "normal" }}>
            {t.text}
          </span>
        ))}
      </code>
    </pre>
  );
}
