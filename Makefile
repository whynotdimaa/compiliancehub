.PHONY: up down logs migrate revision test test-integration lint seed

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api worker

migrate:
	docker compose exec api alembic upgrade head

revision:
	docker compose exec api alembic revision --autogenerate -m "$(m)"

test:
	pytest tests -q --ignore=tests/integration

test-integration:
	RUN_INTEGRATION=1 pytest tests/integration -q -m integration

lint:
	ruff check app tests alembic scripts

seed:
	python scripts/seed_demo.py
