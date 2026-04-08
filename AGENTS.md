# AGENTS.md - Ampr Core Backend

## Overview

Ampersand is a complete financial portal combining a web3 wallet, intelligent AI co-pilot, and an app store filled with financial products, strategies, and agents.

---

## Core Agent Principles

### 1. Discuss Before Implementing
- **NEVER begin implementing code unless the user says to**
- Do not modify code if the user is asking about plans or has a question
- Find and trace issues without immediately modifying code for a solution
- Focus on architecture and planning until explicitly told to implement any code changes
- When implementing code, keep a clear separation between steps, do not automatically proceed from one aspect to another

### 2. Question Before Concluding
- **Ask clarifying questions** when requirements are ambiguous
- Do not make assumptions about user intent without confirmation
- Request specific details about:
  - Database schema requirements
  - API endpoint specifications
  - Integration preferences
  - Expected behavior and edge cases

### 3. Explain Your Work
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
- **Language**: Python (managed via Poetry); database managed via TypeScript
- **Database**: Convex DB (relational + vector storage)
- **AI Orchestration**: Pydantic AI
- **LLM Provider**: Mistral (primary)
- **Communications**: Telegram + WhatsApp

### Infrastructure
- **Deployment**: Railway
- **Environment Management**: Poetry virtual environment

---

## Development Commands

### Poetry Virtual Environment
**CRITICAL**: All Python commands must run through Poetry:
