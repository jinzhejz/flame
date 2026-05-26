.PHONY: help install test clean build-protos format lint typecheck

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install the package in development mode
	pip install -e .

test: ## Run tests
	uv run -n test/test_flame.py

clean: ## Clean up generated files
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.egg-info" -type d -exec rm -rf {} + 2>/dev/null || true

build-protos: ## Generate protobuf Python files
	uv run -n build_protos.py

format: ## Format code with ruff
	uv run -n --extra dev ruff format src
	uv run -n --extra dev ruff check --fix src

lint: ## Run linting checks
	uv run -n --extra dev ruff format --check src
	uv run -n --extra dev ruff check src

typecheck: ## Run type checking
	uv run -n --extra dev mypy src

check: format lint test ## Run all checks (format, lint, test)

dist: clean ## Build distribution package
	uv run -n setup.py sdist bdist_wheel
