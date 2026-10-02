.PHONY: run test lint up

PYTHON ?= python
PYTEST ?= pytest

run:
	$(PYTHON) -m uvicorn app.main:create_app --factory --reload

up:
	docker-compose up --build -d

test:
	docker-compose up -d db
	@echo "Waiting for db to be ready..."
	@sleep 3
	DATABASE_URL=postgresql://postgres:password@localhost:5432/no_stampede $(PYTEST) -v

lint:
	$(PYTHON) -m py_compile app/main.py
