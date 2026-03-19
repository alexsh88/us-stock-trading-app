.PHONY: up down build logs shell-backend shell-frontend migrate seed test lint format

# Docker
up:
	docker-compose up -d

down:
	docker-compose down

build:
	docker-compose build

logs:
	docker-compose logs -f

logs-backend:
	docker-compose logs -f backend celery-worker celery-beat

# Shell access
shell-backend:
	docker-compose exec backend bash

shell-frontend:
	docker-compose exec frontend sh

# Database
migrate:
	docker-compose exec backend alembic upgrade head

makemigration:
	docker-compose exec backend alembic revision --autogenerate -m "$(msg)"

seed:
	docker-compose exec backend python infra/scripts/seed-dev.py

# Development
install-backend:
	cd backend && pip install -e ".[dev]"

install-frontend:
	cd frontend && npm install

# Testing
test:
	docker-compose exec backend pytest tests/ -v

test-unit:
	docker-compose exec backend pytest tests/unit/ -v

test-integration:
	docker-compose exec backend pytest tests/integration/ -v

# Code quality
lint:
	cd backend && ruff check .
	cd frontend && npm run lint

format:
	cd backend && ruff format .

typecheck:
	cd backend && mypy app/

# Analysis
run-analysis:
	curl -X POST http://localhost:8000/api/v1/analysis/run \
		-H "Content-Type: application/json" \
		-d '{"top_n": 5, "mode": "swing"}'

# Monitoring
flower:
	docker-compose exec celery-worker celery -A app.tasks.celery_app flower --port=5555

# Cleanup
clean:
	docker-compose down -v
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
