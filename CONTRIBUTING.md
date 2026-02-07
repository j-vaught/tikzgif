# Contributing to tikzgif

Thank you for your interest in contributing. This document explains how to set
up a development environment, run the test suite, and submit changes.

## Development setup

```bash
# Clone the repository
git clone https://github.com/j-vaught/tikzgif.git
cd tikzgif

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in editable mode with all extras
make install

# Install pre-commit hooks
make install-pre-commit
```

## System dependencies

You need a working LaTeX installation for integration tests. See the README
for platform-specific instructions.

For unit tests only (no LaTeX needed):

```bash
make test-unit
```

## Running quality checks

```bash
# Lint, type-check, and test in one command
make check

# Or individually:
make lint
make typecheck
make test
```

## Code style

This project uses **ruff** for both linting and formatting. The configuration
lives in `pyproject.toml`. Running `make fmt` will auto-format your code.

## Commit messages

Use imperative mood in the subject line:

- "Add PDF caching layer" (good)
- "Added PDF caching layer" (avoid)
- "Adds PDF caching layer" (avoid)

Keep the subject under 72 characters. Add a body if the change needs
explanation.

## Pull requests

1. Create a feature branch from `main`.
2. Make your changes with tests.
3. Verify `make check` passes locally.
4. Push and open a PR against `main`.
5. Fill in the PR template.

## Versioning

This project uses [Semantic Versioning](https://semver.org/). Bump the version
in `pyproject.toml` and `src/tikzgif/__init__.py` when preparing a release.

## Reporting bugs

Use the GitHub issue tracker. Include:

- Your OS and Python version.
- LaTeX distribution and version (`pdflatex --version`).
- The `.tex` file that triggered the bug (if applicable).
- Full traceback.
