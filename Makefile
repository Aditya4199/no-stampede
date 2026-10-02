.PHONY: run test lint check

PYTHON ?= python
PYTEST ?= pytest

run:
	$(PYTHON) -m uvicorn app.main:create_app --factory --reload

test:
	$(PYTEST) -v

lint:
	$(PYTHON) -m py_compile app/main.py
