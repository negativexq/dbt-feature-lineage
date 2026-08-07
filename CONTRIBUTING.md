# Contributing to dbt-feature-lineage

Thanks for considering a contribution. This project is a local, open-source dbt lineage explorer (Typer CLI + Streamlit UI), and it's maintained on a best-effort basis — focused, well-tested contributions are very welcome.

## Getting started

Everything runs in Docker; you don't need a local Python environment.

```bash
git clone https://github.com/negativexq/dbt-feature-lineage.git
cd dbt-feature-lineage
make build
make test
make app
```

`make app` starts the Streamlit UI at [http://localhost:8501](http://localhost:8501), pointed at the bundled example projects under `examples/`. The repository is bind-mounted into the container, so code changes are picked up without rebuilding.

Other useful commands (see the [Makefile](Makefile)):

| Command | Purpose |
| --- | --- |
| `make build` | Build the Docker image |
| `make up` | Start the app in the background |
| `make app` | Start Streamlit in the foreground |
| `make down` | Stop and remove the Compose services |
| `make shell` | Open a shell in the running container |
| `make test` | Run the pytest suite in Docker |
| `make lint` | Run Ruff in Docker |
| `make logs` | Follow application logs |

You can also run the CLI directly inside the container, e.g.:

```bash
docker compose run --rm app dbt-feature-lineage analyze examples/sample_banking_dbt
```

See the [README](README.md#cli-usage) for the full set of CLI commands and the [Web interface](README.md#web-interface) section for what each Streamlit page does.

## Project architecture

```text
src/dbt_feature_lineage/
├── cli.py        # Typer CLI entry point
├── domain/       # Pydantic models shared by every other layer (DbtProject, DbtModel, ...)
├── loaders/      # Resolve a project path into domain models -- manifest mode or static mode
├── parsers/      # SQL/Jinja parsing (sqlglot-based) used by static mode and query-flow analysis
├── scanners/     # Filesystem/YAML scanning used by static mode
├── services/     # Lineage graphs, model-DAG construction, column search, impact summaries
└── ui/           # Thin Streamlit-facing helpers (rendering, caching, streamlit-flow-component glue)

pages/            # The five Streamlit pages (select_project, model_explorer, model_dag, column_lineage, feature_explorer)
tests/            # pytest suite, one file per module/page, plus tests/fixtures for manifest-mode fixtures
examples/         # Two full example dbt projects (sample_banking_dbt, multi_domain_dbt) used by tests and the demo UI
```

**The architectural rule that matters most here: the CLI and the Streamlit pages both consume the same `services`/`domain` layer — neither one re-implements analysis logic.** `loaders` normalize a project (manifest or static) into the same `domain` models regardless of source; `services` build everything on top of those models (schema/lineage graphs, model DAG, column search, query-flow steps, impact summaries); `cli.py` and `pages/*.py` are both just callers into that same service layer, formatting the same results differently (Rich tables/JSON vs. Streamlit widgets). If you're adding a feature, the analysis logic belongs in `domain`/`services`, not duplicated in `cli.py` and a page file.

## Development expectations

- **Tests**: behavior changes should come with tests. Bug fixes should preferably include a regression test that fails before the fix and passes after.
- **Lint**: `make lint` (Ruff) must pass.
- **Existing tests**: `make test` must stay green — don't introduce regressions.
- **Docs**: update the README (or relevant `docs/` file) when user-visible behavior changes — new CLI flags, new pages, changed output shape, etc.
- **Nothing generated or sensitive**: don't commit generated dbt artifacts (`target/`, `logs/`), credentials, `profiles.yml` with real connection info, local databases, or other machine-specific files. Check `.gitignore` before adding new example/fixture files.

There's no requirement to open an issue before every PR — small, focused fixes can go straight to a PR.

## Pull requests

- Keep PRs focused on one change; avoid mixing an unrelated refactor into a feature or bug-fix PR.
- Explain the problem and the solution in the PR description, not just what changed.
- Include a screenshot or short GIF for UI changes when it helps a reviewer see the result.
- Include tests for behavior changes (see above).
- The [PR template](.github/PULL_REQUEST_TEMPLATE.md) has a short checklist — use it.

## Reporting bugs and proposing features

Please use the GitHub issue templates rather than a blank issue when you can — they ask for the details that are actually useful for this project (manifest vs. static mode, dbt Core version, etc.):

- [Report a bug](https://github.com/negativexq/dbt-feature-lineage/issues/new?template=bug_report.yml)
- [Request a feature](https://github.com/negativexq/dbt-feature-lineage/issues/new?template=feature_request.yml)

For security issues, see [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Code of Conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md) — please read it before participating.
