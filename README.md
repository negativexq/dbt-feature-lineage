# dbt-feature-lineage

dbt-feature-lineage is a local, open-source development project for exploring dbt model and column lineage from a developer-friendly environment. This initial step only sets up the repository structure and Docker-based tooling needed to start implementation later.

Current status: project scaffold and containerized development environment are in place; the lineage application itself is not implemented yet.

## Docker setup

1. Build the development image with `make build`.
2. Start the container with `make up`.
3. Open a shell in the running container with `make shell`.
4. Stop the environment with `make down`.

The repository is mounted into `/app`, and `PYTHONPATH` is set to `/app/src` inside the container.

## Available Makefile commands

- `make build`
- `make up`
- `make down`
- `make shell`
- `make test`
- `make lint`
- `make logs`
