# Security Policy

## Reporting a vulnerability

This repository has GitHub's private vulnerability reporting enabled. Please
**do not open a public GitHub issue** for a suspected security vulnerability —
instead, use
[Report a vulnerability](https://github.com/negativexq/dbt-feature-lineage/security/advisories/new)
(also available under the repository's "Security" tab) to open a private
security advisory. This reaches the maintainer directly without disclosing
details publicly.

Ordinary bugs (parsing errors, incorrect lineage output, UI issues, etc.) that
don't have security impact should go through the normal
[bug report template](https://github.com/negativexq/dbt-feature-lineage/issues/new?template=bug_report.yml)
instead.

## What counts as a security issue here

This is a local developer tool that reads a dbt project's SQL/YAML (and,
optionally, `target/manifest.json`) from disk and never connects to a
warehouse itself. Relevant categories of security report include:

- **Arbitrary file access** — the tool reading or writing files outside the
  scanned project directory in ways that weren't intended.
- **Command/code execution** — anything that lets a crafted dbt project (SQL,
  YAML, Jinja, or manifest content) cause code execution beyond what's
  expected of static analysis, or unexpected behavior from the `dbt parse`
  subprocess invocation triggered by `--generate-artifacts`.
- **Unsafe parsing behavior** — sqlglot/Jinja-preprocessing edge cases that
  could be abused (e.g. via a malicious model file) rather than just failing
  to parse.
- **Credential exposure** — the tool logging, printing, or persisting
  `profiles.yml` contents or other connection credentials it happens to read.
- **Dependency vulnerabilities** — known CVEs in this project's dependencies
  (dbt-core, sqlglot, Streamlit, etc.) that are actually reachable through
  this tool's usage.

## Scope

There is no live warehouse connection, hosted service, or user data store
involved — the threat model is local-machine/local-project analysis, not a
multi-tenant service.
