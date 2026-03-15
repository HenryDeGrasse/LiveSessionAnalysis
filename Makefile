# ──────────────────────────────────────────────────────────────
# LiveSessionAnalysis — top-level Makefile
# ──────────────────────────────────────────────────────────────
.PHONY: setup run dev dev-backend dev-frontend clean \
        test test-backend test-frontend-unit test-e2e test-e2e-livekit \
        eval eval-fast eval-replay test-all lint \
        test-transcription test-ai-coaching test-ci \
        accuracy-report real-media-accuracy demo-setup

# ── Infrastructure ───────────────────────────────────────────
setup:
	docker compose build

run:
	docker compose up --build

dev: dev-backend dev-frontend

dev-backend:
	cd backend && uv run --python 3.11 --with-requirements requirements.txt \
		uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

clean:
	docker compose down -v

# ── Backend tests ────────────────────────────────────────────
test-backend:
	cd backend && uv run --python 3.11 --with-requirements requirements.txt \
		pytest tests/ -q

# ── Eval suite (deterministic golden + replay) ───────────────
eval-fast:
	cd backend && uv run --python 3.11 --with-requirements requirements.txt \
		pytest tests/evals/ -m eval_fast -q

eval-replay:
	cd backend && uv run --python 3.11 --with-requirements requirements.txt \
		pytest tests/evals/ -m eval_replay -q

eval:
	cd backend && uv run --python 3.11 --with-requirements requirements.txt \
		pytest tests/evals/ -q

# ── Frontend tests ───────────────────────────────────────────
test-frontend-unit:
	cd frontend && npm run test:unit

test-e2e:
	cd frontend && npm run test:e2e

test-e2e-livekit:
	cd frontend && npm run test:e2e:livekit

# ── Conversational Intelligence tests ────────────────────────
test-transcription:
	cd backend && uv run --python 3.11 --with-requirements requirements.txt \
		pytest tests/test_transcription*.py tests/test_session_transcription*.py -q

test-ai-coaching:
	cd backend && uv run --python 3.11 --with-requirements requirements.txt \
		pytest tests/test_ai_*.py tests/test_uncertainty*.py -q

test-ci:
	cd backend && uv run --python 3.11 --with-requirements requirements.txt \
		pytest tests/ -q --ignore=tests/evals
	cd frontend && npm run test:unit

# ── Accuracy report ──────────────────────────────────────────
accuracy-report:
	cd backend && uv run --python 3.11 --with-requirements requirements.txt \
		python ../scripts/accuracy_report.py

# ── Real media accuracy validation ──────────────────────────
real-media-accuracy:
	cd backend && uv run --python 3.11 --with-requirements requirements.txt \
		python ../scripts/real_media_accuracy.py

# ── Demo setup ──────────────────────────────────────────────
demo-setup:
	./scripts/demo-setup.sh

# ── Type checking / lint ─────────────────────────────────────
lint:
	cd frontend && npx tsc --noEmit
	cd backend && uv run --python 3.11 --with-requirements requirements.txt \
		python -m py_compile app/main.py

# ── Aggregate targets ────────────────────────────────────────
test: test-backend test-frontend-unit
	@echo ""
	@echo "✓ Backend tests + frontend unit tests passed"

test-all: test-backend test-frontend-unit eval test-e2e
	@echo ""
	@echo "✓ All tests passed (backend · frontend-unit · evals · e2e)"
