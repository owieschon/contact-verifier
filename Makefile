.PHONY: install test lint run db-up db-down migrate

install:        ## install the package + dev/mcp extras
	pip install -e ".[dev,mcp]"

test:           ## run the test suite
	pytest -q

lint:           ## lint
	ruff check src tests

run:            ## run the REST API (SQLite by default)
	contact-verifier serve

db-up:          ## start Postgres in docker
	docker compose up -d db

db-down:
	docker compose down

migrate:        ## apply migrations to CV_DATABASE_URL
	alembic upgrade head
