# Repository Guidelines

## Project Structure & Module Organization

OpenFolio is a portfolio tracker with a FastAPI backend and React 19 frontend.
- `backend/api/` contains routes and schemas; `services/` holds business logic; `models/` contains SQLAlchemy models. Database migrations live in `backend/alembic/versions/`.
- `frontend/src/` contains pages, reusable components, hooks, contexts, and utilities; `frontend/public/` holds static assets.
- Backend tests live in `backend/tests/`; frontend tests use colocated `__tests__/` directories.
- `docs/` documents financial invariants and external APIs; `scripts/` contains operational utilities; `monitoring/` contains observability configuration.

## Build, Test, and Development Commands

Use Node.js compatible with `frontend/.nvmrc`, Python 3.14+, and Docker Compose v2. Run commands from the indicated directory.
- Root: `./init.sh` performs initial setup.
- Backend: `pip install -r requirements.txt` installs dependencies; `uvicorn main:app --reload` starts the development API.
- Frontend: `npm install` installs dependencies; `npm run dev` starts Vite; `npm run build` produces the production bundle; `npm run preview` serves that bundle locally.
- Backend: `pytest tests/ -v` runs the Python suite.
- Frontend: `npm test` runs Vitest once.

## Coding Style & Naming Conventions

Follow surrounding code: four-space Python indentation and two-space JavaScript/JSX indentation. Use snake_case for Python modules/functions, PascalCase for React components, and `use...` names for hooks. No repository-wide formatter or lint command is configured.

Write code in English and user-facing text in German. Add type annotations to public Python functions, validate API inputs with constrained Pydantic models, and log caught exceptions. Use React function components, Tailwind, and Lucide icons; follow `frontend/DESIGN_SYSTEM.md` and label inputs accessibly.

## Testing Guidelines

Use pytest/pytest-asyncio with `test_*.py`; shared fixtures provide in-memory SQLite. Frontend tests use Vitest and `*.test.js`. Add regression tests for critical logic; no numeric coverage threshold is configured. Verify UI changes on mobile widths below 768px and run the frontend build.

Read `docs/INVARIANTS.md` before changing financial calculations or signals. Keep golden-master tests passing and discuss semantic changes with the maintainer.

## Commit & Pull Request Guidelines

History uses Conventional Commits with optional scopes, such as `fix(frontend): ...`. Prefer English messages as requested in `CONTRIBUTING.md`. Work on a feature branch. Describe the change, link relevant issues, report validation, and include screenshots for UI changes. Justify new dependencies.

## Security & Configuration

Use `.env.example` as the configuration reference; never commit credentials or private portfolio data. Follow `SECURITY.md` for vulnerability reporting.
