COMPOSE = docker compose

.PHONY: build up down shell test lint logs

build:
	$(COMPOSE) build

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

