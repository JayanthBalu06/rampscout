# RampScout developer commands. Run `make help`.
PY := backend/.venv/bin
SHELL := /bin/bash

.PHONY: help setup up down migrate migrate-test seed api worker web test test-backend test-frontend lint demo

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-15s %s\n", $$1, $$2}'

setup: ## Create venv, install backend + frontend deps, copy .env
	test -f .env || cp .env.example .env
	cd backend && python3.11 -m venv .venv && .venv/bin/pip install -q -e '.[dev]'
	cd frontend && npm install

up: ## Start Postgres (docker compose) and apply migrations
	docker compose up -d --wait
	$(MAKE) migrate migrate-test

down: ## Stop Postgres
	docker compose down

migrate: ## Apply migrations to the dev database
	cd backend && .venv/bin/alembic upgrade head

migrate-test: ## Apply migrations to the test database
	cd backend && ALEMBIC_DATABASE_URL=$$(grep ^TEST_DATABASE_URL ../.env | cut -d= -f2-) .venv/bin/alembic upgrade head

seed: ## Seed demo user, destination, and a fresh demo session
	cd backend && .venv/bin/python -m scripts.seed

api: ## Run FastAPI on :8000 (reload)
	cd backend && .venv/bin/uvicorn rampscout.api.app:app --reload --port 8000

worker: ## Run the background worker
	cd backend && .venv/bin/python -m rampscout.worker.main

web: ## Run the Vite dev server on :5173
	cd frontend && npm run dev

test: test-backend test-frontend ## Run all tests

test-backend:
	cd backend && .venv/bin/pytest -q

test-frontend:
	cd frontend && npm test

lint: ## Lint + typecheck everything
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy rampscout
	cd frontend && npm run lint && npm run typecheck
