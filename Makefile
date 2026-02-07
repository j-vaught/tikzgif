# ---------------------------------------------------------------------------
# tikzgif -- Developer Makefile
# ---------------------------------------------------------------------------
# Usage:
#   make install      Install package in editable mode with all extras
#   make test         Run full test suite
#   make test-unit    Run unit tests only (no LaTeX needed)
#   make lint         Run ruff linter
#   make fmt          Auto-format with ruff
#   make typecheck    Run mypy
#   make check        Run lint + typecheck + test (pre-push gate)
#   make docs         Build HTML documentation
#   make clean        Remove build artifacts and caches
#   make build        Build sdist + wheel
#   make publish-test Publish to TestPyPI
#   make publish      Publish to PyPI
# ---------------------------------------------------------------------------

.DEFAULT_GOAL := help
SHELL := /bin/bash
PYTHON ?= python3
SRC_DIR := tikzgif
TEST_DIR := tests

# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------
.PHONY: install
install: ## Install package in editable mode with all extras
	$(PYTHON) -m pip install -e ".[all]"

.PHONY: install-dev
install-dev: ## Install only dev dependencies (no docs, no optional backends)
	$(PYTHON) -m pip install -e ".[dev]"

.PHONY: install-pre-commit
install-pre-commit: ## Install pre-commit hooks
	pre-commit install

# ---------------------------------------------------------------------------
# Quality gates
# ---------------------------------------------------------------------------
.PHONY: lint
lint: ## Run ruff linter
	ruff check $(SRC_DIR) $(TEST_DIR)

.PHONY: fmt
fmt: ## Auto-format code with ruff
	ruff format $(SRC_DIR) $(TEST_DIR)
	ruff check --fix $(SRC_DIR) $(TEST_DIR)

.PHONY: typecheck
typecheck: ## Run mypy type checker
	mypy --package tikzgif

.PHONY: check
check: lint typecheck test ## Run all quality gates (lint + type + test)

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------
.PHONY: test
test: ## Run full test suite
	pytest $(TEST_DIR) --cov=tikzgif --cov-report=term-missing

.PHONY: test-unit
test-unit: ## Run unit tests only (no LaTeX installation required)
	pytest $(TEST_DIR) -v -m "not integration"

.PHONY: test-integration
test-integration: ## Run integration tests (requires LaTeX)
	pytest $(TEST_DIR)/integration -v -m integration

.PHONY: test-parallel
test-parallel: ## Run tests in parallel with pytest-xdist
	pytest $(TEST_DIR) -n auto --cov=tikzgif --cov-report=term-missing

# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------
.PHONY: docs
docs: ## Build HTML documentation
	$(MAKE) -C docs html

.PHONY: docs-serve
docs-serve: docs ## Build and open documentation
	open docs/_build/html/index.html || xdg-open docs/_build/html/index.html

# ---------------------------------------------------------------------------
# Build & Publish
# ---------------------------------------------------------------------------
.PHONY: build
build: clean-build ## Build sdist and wheel
	$(PYTHON) -m build

.PHONY: publish-test
publish-test: build ## Upload to TestPyPI
	twine upload --repository testpypi dist/*

.PHONY: publish
publish: build ## Upload to PyPI (use with care)
	twine upload dist/*

# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------
.PHONY: bench
bench: ## Run benchmark scripts
	$(PYTHON) benchmarks/bench_compiler.py
	$(PYTHON) benchmarks/bench_assembler.py

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
.PHONY: clean
clean: clean-build clean-pyc clean-test ## Remove all build, cache, and test artifacts

.PHONY: clean-build
clean-build:
	rm -rf dist/ build/ *.egg-info

.PHONY: clean-pyc
clean-pyc:
	find . -type f -name '*.pyc' -delete
	find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '.mypy_cache' -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '.ruff_cache' -exec rm -rf {} + 2>/dev/null || true

.PHONY: clean-test
clean-test:
	rm -rf .pytest_cache htmlcov .coverage coverage.xml

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
.PHONY: help
help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
