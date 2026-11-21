.PHONY: up down logs test

.env:
	cp .env.example .env
	@echo ">> Created .env from .env.example. Put real keys in LLM_API_KEYS."

up: .env
	docker compose up --build -d
	@echo "Frontend: http://localhost:3000   Backend: http://localhost:8000/health"

down:
	docker compose down

logs:
	docker compose logs -f

test:
	cd backend && python -m pytest -q
