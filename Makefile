# Prompt Engineering Studio - developer commands. Run `make help` for the list.

PYTHON ?= python3
VENV := backend/.venv
BIN := $(CURDIR)/$(VENV)/bin
# The repository-root .env (copied from .env.example) is loaded by dev-backend when it exists.
ENV_FILE_ARG := $(if $(wildcard .env),--env-file ../.env)

.DEFAULT_GOAL := help
.PHONY: help install dev dev-backend dev-frontend lint format test build docker-build up down clean

help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Create backend/.venv with the dev requirements and install frontend packages
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/pip install -r backend/requirements-dev.txt
	cd frontend && npm ci

dev: ## Run the backend (port 8000) and the frontend dev server (port 5173) together
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend: ## Run the API with auto-reload on http://localhost:8000 (reads ./.env when present)
	cd backend && $(BIN)/uvicorn app.main:create_app --factory --reload --port 8000 $(ENV_FILE_ARG)

dev-frontend: ## Run the Vite dev server on http://localhost:5173 (proxies /api to port 8000)
	cd frontend && npm run dev

lint: ## Lint and type-check both halves (no changes)
	cd backend && $(BIN)/ruff check . && $(BIN)/ruff format --check .
	cd frontend && npm run lint && npm run typecheck

format: ## Format the backend and apply safe lint fixes
	cd backend && $(BIN)/ruff format . && $(BIN)/ruff check --fix .

test: ## Run the backend and frontend test suites
	cd backend && $(BIN)/python -m pytest -W error
	cd frontend && npm test

build: ## Build the frontend for production (frontend/dist)
	cd frontend && npm run build

docker-build: ## Build both Docker images
	docker compose build

up: ## Build and start the stack in the background (UI on http://localhost:3000)
	docker compose up --build -d

down: ## Stop the stack (the database volume is kept)
	docker compose down

clean: ## Remove local build output, caches and the backend virtual environment
	rm -rf $(VENV) frontend/node_modules frontend/dist frontend/coverage
	rm -rf backend/.pytest_cache backend/.ruff_cache backend/.coverage backend/htmlcov
	find backend -type d -name __pycache__ -prune -exec rm -rf {} +
