.PHONY: install test lint build clean
install:
	pip install -e ".[test,audio]"
test:
	pytest -q
lint:
	ruff check .
build:
	python -m build
clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache
