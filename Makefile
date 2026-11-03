# Convenience targets (Linux/macOS/Git Bash). On Windows PowerShell run the commands directly.
.PHONY: up down logs ps test test-backend test-frontend test-simulator lint demo traffic clean

up:            ## build and start the whole stack
	docker compose up -d --build --wait

down:          ## stop (keeps data)
	docker compose down

clean:         ## stop and remove THIS project's volumes
	docker compose down -v

ps:
	docker compose ps

logs:
	docker compose logs -f api worker beat

test: test-backend test-simulator test-frontend

test-backend:
	cd backend && pytest --cov=app

test-simulator:
	cd simulator && pytest

test-frontend:
	cd frontend && npm run test:ci && npm run build

lint:
	cd backend && ruff check app tests && ruff format --check app tests && mypy app
	cd simulator && ruff check . && ruff format --check .
	cd frontend && npm run format:check && npm run typecheck

demo:          ## end-to-end resilience scenario against the running stack
	python tests/e2e/demo_scenario.py

traffic:       ## populate the dashboard with real signed webhooks
	python scripts/generate_traffic.py --count 40
