# AGENTS.md - Ampr Core Backend

## Build, Test & Lint Commands
- **Install dependencies**: `poetry install`
- **Run all tests**: `pytest`
- **Run single test**: `pytest src/tests/test_file.py::test_function_name -v`
- **Run dev server**: `uvicorn src.main:fast_api --reload`

## Architecture & Structure
- **Framework**: FastAPI (Python 3.10+)
- **Database**: EdgeDB (instance v6.9)
- **AI**: Pydantic-AI agents for LLM integration
- **SMS/Chat**: Vonage for SMS, chat via API
- **Key modules**:
  - `src/api/`: FastAPI routers (users, auth, chat, webhooks)
  - `src/agents/`: AI agent implementations (amprChat)
  - `src/models/`: Pydantic models for validation
  - `src/queries/`: EdgeDB async queries
  - `src/clients/`: Third-party integrations (Vonage, etc.)
  - `src/config/`: Configuration (vonage_config)

## Code Style Guidelines
- **Type hints**: Required on all function signatures. Use `from typing import ...`
- **Imports**: Group stdlib, third-party, local. Use absolute imports from `src/`
- **Models**: Use Pydantic BaseModel with Field validators, docstrings for classes
- **Naming**: snake_case for functions/vars, PascalCase for classes, UPPER_CASE for constants
- **Logging**: `logger = logging.getLogger(__name__)` per module
- **Async/await**: All I/O uses `async def` with `await` (FastAPI, Gel, Vonage)
- **Error handling**: Raise exceptions with context, use `logger.error(..., exc_info=True)`
- **Docstrings**: Module-level docstrings, function docstrings with Args/Returns/Raises

## Dependencies
- fastapi, uvicorn, pydantic, pydantic-ai
- gel (EdgeDB async client), pydantic-extra-types
- vonage, vonage-messages (SMS), resend (email)
- httpx (HTTP client), python-dotenv, pycountry, phonenumbers
