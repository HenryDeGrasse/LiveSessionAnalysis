.PHONY: setup run test test-e2e test-e2e-livekit dev dev-backend dev-frontend clean

setup:
	docker compose build

run:
	docker compose up

test:
	cd backend && uv run --python 3.11 --with-requirements requirements.txt pytest tests/ -v

test-e2e:
	cd frontend && npm run test:e2e

test-e2e-livekit:
	cd frontend && npm run test:e2e:livekit

dev: dev-backend dev-frontend

dev-backend:
	cd backend && uv run --python 3.11 --with-requirements requirements.txt uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

clean:
	docker compose down -v
