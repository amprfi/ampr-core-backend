# Migration: Pydantic-AI → Mistral SDK

## Status: Core Migration Gate Complete (AMPRFI-115)

This document tracks the migration of Ampersand's backend from `pydantic-ai`
to the official `mistralai` SDK for all **in-scope core** Mistral paths.

### What's Done

All in-scope core Mistral paths now use the official `mistralai` SDK rather
than direct calls to `https://api.mistral.ai`:

- **amprChat** — migrated to the shared streaming-native Mistral tool runner
  (AMPRFI-116, AMPRFI-117). Uses `get_shared_client()` and the `RunnerConfig`
  pattern.
- **Extractor, WatchlistInferrer, DatePreprocessor, CurrencyInferrer**
  — migrated to direct Mistral SDK calls with structured JSON output
  (AMPRFI-120). All use `get_shared_client()` and the shared
  `complete_json_schema()` helper.
- **Summarizer**
  — migrated to direct Mistral SDK calls with plain-text output
  (AMPRFI-120). Uses `get_shared_client()` and the shared
  `complete_text()` helper.
- **Module router** — uses the shared Mistral SDK client for LLM classification
  (AMPRFI-120).
- **Admin latency diagnostics** — uses the shared Mistral SDK client instead of
  raw `httpx` calls (AMPRFI-123).
- **Lens ingestion** — `clean_with_mistral` uses the shared Mistral SDK client
  with fail-closed behavior (AMPRFI-123).
- **Notification synthesizer** — uses the shared Mistral SDK client with
  fallback-to-concatenation behavior.
- **Currency converter** — uses the shared Mistral SDK client.

### Shared Helpers

All in-scope SDK callers use the shared helpers in `src/agents/mistral_helpers.py`:

- **`get_shared_client()`** — singleton Mistral client for reuse across agents.
  All in-scope SDK callers must use this instead of `get_mistral_client()`.
- **`get_mistral_client()`** — factory function that creates a new client
  instance. Confined to shared-client construction; in-scope callers should not
  use it directly.
- **`complete_json_schema()`** — structured-output completion helper with
  explicit `model`, `temperature`, `reasoning_effort`, retry (via client
  `RetryConfig`), and caller-handled fallback.
- **`complete_text()`** — plain-text completion helper with explicit
  `model`, `temperature`, `reasoning_effort`, retry (via client `RetryConfig`),
  and caller-handled fallback.
- **`build_messages()`** — builds `SystemMessage` + `UserMessage` pairs.
- **`extract_text_from_content()`** — extracts text from Mistral response
  content (handles reasoning chunks).
- **`to_strict_schema()`** — transforms Pydantic JSON schemas to strict-mode
  compliant for reliable structured output.

### Deferred Holdouts (Not Regressions)

The following modules still use `pydantic-ai` and/or raw Mistral HTTP calls.
They are **outside the scope** of this migration pass and are tracked by
separate issues:

| File | Reason | Tracking Issue |
|------|--------|----------------|
| `src/agents/onboarding.py` | Still uses `pydantic_ai.Agent` | AMPRFI-110 |
| `src/modules/defianalyst/agent.py` | Still uses `pydantic_ai.Agent` | AMPRFI-122 |
| `src/modules/defianalyst/utils.py` | Still uses `pydantic_ai.Agent` | AMPRFI-127 |
| `src/modules/lens/agent.py` | Still uses `pydantic_ai.Agent` | AMPRFI-121 |
| `src/modules/oracle/agent.py` | Uses raw `httpx` to `https://api.mistral.ai` | AMPRFI-125 |

### Dependency State

`pydantic-ai` **remains** in `pyproject.toml` because the deferred holdouts
above (plus `src/agents/onboarding.py`) still depend on it. The lockfile
intentionally retains `pydantic-ai`.

### What's Next (After This Gate)

Frontend work follows this core migration gate. The remaining `pydantic-ai`
holdouts will be migrated in subsequent waves (AMPRFI-110, AMPRFI-121,
AMPRFI-122, AMPRFI-125, AMPRFI-127), after which `pydantic-ai` can be removed
from `pyproject.toml`.

### Post-Migration Optimizations (Not Part of This Gate)

- **AMPRFI-124** — Evaluate Mistral prompt caching for amprChat.
- **AMPRFI-128** — Add future safeguards for runtime-only internal chat context.
