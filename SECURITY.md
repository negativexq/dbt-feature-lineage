# Security Policy

## Reporting a vulnerability

This repository does not currently have GitHub's private vulnerability
reporting enabled, and there is no dedicated security email address. Please
**do not open a public GitHub issue** for a suspected security vulnerability.

Until private reporting is enabled, the safest option is to open a
[GitHub issue](https://github.com/negativexq/dbt-feature-lineage/issues) with
minimal detail (e.g. "possible security issue, will share details privately")
and no proof-of-concept or exploit details, and note in it that you'd like to
coordinate a private disclosure. The maintainer ([@negativexq](https://github.com/negativexq))
will follow up to arrange a private channel. If you'd rather not do even that,
reaching out through the maintainer's GitHub profile is the next-best option.

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
