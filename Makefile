.PHONY: run test lint check

PYTHON ?= .venv/Scripts/python.exe
PYTEST ?= .venv/Scripts/pytest.exe

run:
	$(PYTHON) -m app.main

test:
	$(PYTEST) -v

lint:
	$(PYTHON) -m py_compile app/main.py
