COMPOSE = docker compose

.PHONY: app api web build up down shell test lint logs

build:
	$(COMPOSE) build

app:
	$(COMPOSE) up app

# The FastAPI backend for the Next.js web app (frontend/) -- the
# primary interface as of v0.10. Run this, then `make web` in another
# terminal (or `cd frontend && npm install && npm run dev` directly).
api:
	$(COMPOSE) up api

web:
	cd frontend && npm install && npm run dev

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

shell:
	$(COMPOSE) exec app /bin/sh

test:
	$(COMPOSE) run --rm app pytest

lint:
	$(COMPOSE) run --rm app ruff check .

logs:
	$(COMPOSE) logs -f app
