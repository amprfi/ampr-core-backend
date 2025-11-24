# AGENTS.md - Ampr Core Backend

## Overview

Ampersand is a complete financial portal combining a web3 wallet, intelligent AI co-pilot, and an app store filled with financial products, strategies, and agents.

---

## Core Agent Principles

### 1. Question Before Concluding
- **Ask clarifying questions** when requirements are ambiguous
- Do not make assumptions about user intent without confirmation
- Request specific details about:
  - Database schema requirements
  - API endpoint specifications
  - Integration preferences
  - Expected behavior and edge cases

### 2. Explain Your Work
- **Document all decisions** with clear reasoning
- Provide step-by-step explanations for:
  - Architecture choices
  - Implementation approaches
  - Code modifications
  - Debugging strategies
- Include comments in code explaining non-obvious logic
- Summarize changes after completing tasks

---

## Technology Stack

### Backend
- **Framework**: FastAPI
- **Language**: Python (managed via Poetry)
- **Database**: GelDB (relational + vector storage)
- **AI Orchestration**: Pydantic AI
- **LLM Provider**: Mistral (primary)
- **Communications**: Vonage (SMS & Chat APIs)

### Frontend
- **Framework**: Svelte/SvelteKit
- **Type**: Progressive Web Application (PWA)

### Infrastructure
- **Deployment**: Railway
- **Environment Management**: Poetry virtual environment

---

## Development Commands

### Poetry Virtual Environment
**CRITICAL**: All Python commands must run through Poetry:

