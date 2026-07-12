.PHONY: install install-all test lint typecheck run backlog clean

install:
	python -m pip install -e .

install-all:
	python -m pip install -e ".[dev]"

test:
	python -m pytest

lint:
	ruff check research_agent tests

typecheck:
	mypy research_agent

run:
	research-agent run --config config/hexgen.yaml

backlog:
	research-agent backlog --config config/hexgen.yaml

clean:
	rm -rf data/ output/ .pytest_cache .ruff_cache .mypy_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
