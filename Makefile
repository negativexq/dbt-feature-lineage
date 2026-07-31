COMPOSE = docker compose

.PHONY: app build up down shell test lint logs

build:
	$(COMPOSE) build

app:
	$(COMPOSE) up app

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
