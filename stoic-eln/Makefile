.PHONY: help install dev test lint format run init-db clean translations

help:
	@echo "Stoic ELN — development commands"
	@echo ""
	@echo "  make install       Install the project (with dev dependencies)"
	@echo "  make init-db       Create the database and admin user"
	@echo "  make run           Start the development server"
	@echo "  make test          Run the test suite"
	@echo "  make lint          Run ruff linter"
	@echo "  make format        Auto-format code with ruff"
	@echo "  make translations  Compile .po files into .mo"
	@echo "  make clean         Remove caches and build artifacts"

install:
	pip install -e ".[dev]"

init-db:
	python scripts/init_db.py

init-db-reset:
	python scripts/init_db.py --reset

run:
	flask --app stoic_eln run --debug --port 5000

test:
	pytest

lint:
	ruff check .

format:
	ruff format .
	ruff check . --fix

translations:
	pybabel compile -d stoic_eln/translations

translations-extract:
	pybabel extract -F babel.cfg -o messages.pot stoic_eln/
	pybabel update -i messages.pot -d stoic_eln/translations

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -f messages.pot
