COMPOSE ?= docker compose

.PHONY: help up down logs build seed migrate revision shell psql test fmt reset

help:
	@echo "make up        - build and start db + backend + frontend"
	@echo "make seed      - load the offline demo dataset (admin user, 2 sessions, 15 analysed CVs)"
	@echo "make down      - stop everything"
	@echo "make reset     - stop and DELETE the database and stored CVs"
	@echo "make logs      - tail backend logs"
	@echo "make migrate   - run alembic upgrade head"
	@echo "make revision  - autogenerate a migration (m=\"message\")"
	@echo "make test      - run the backend test suite"

up:
	$(COMPOSE) up -d --build
	@echo "Dashboard  http://localhost:5173"
	@echo "API docs   http://localhost:8000/docs"

down:
	$(COMPOSE) down

reset:
	$(COMPOSE) down -v

logs:
	$(COMPOSE) logs -f backend

build:
	$(COMPOSE) build

seed:
	$(COMPOSE) exec backend python -m app.seed

migrate:
	$(COMPOSE) exec backend alembic upgrade head

revision:
	$(COMPOSE) exec backend alembic revision --autogenerate -m "$(m)"

shell:
	$(COMPOSE) exec backend bash

psql:
	$(COMPOSE) exec db psql -U tricv -d tricv

test:
	$(COMPOSE) exec backend pytest -q
