.PHONY: dev test reset

dev:
	cd backend && SOT_ALLOW_RESET=1 .venv/bin/uvicorn sot.api.app:create_app --factory --reload --port 8000

test:
	cd backend && .venv/bin/python -m pytest -q

# Empties the database and the runtime folders through the running server (deleting the files under a live server breaks it).
reset:
	curl -fsS -X POST http://localhost:8000/api/reset
