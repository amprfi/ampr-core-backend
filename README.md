# Ampersand Core Backend

**The world's first open financial operating system.**

Ampersand combines a web3 wallet, an intelligent AI co-pilot (Ampr), and an app store of financial products, strategies, and agents — all accessible through an accessible user interface (*coming soon*) conversational interfaces like Telegram.

---

## What is Ampersand?

Ampersand is a financial platform that brings together:

- **AI Co-Pilot (Ampr)**: A conversational assistant powered by Mistral AI that helps users understand their finances, track investments, and get market data
- **Multi-Channel Access**: Beyond a traditional application interface, users can interact via Telegram, WhatsApp, or Email
- **Modular Agents**: Specialized AI and Human agents provide domain-specific capabilities, data, and financial products
- **Complex Memory**: Investment preferences, risk appetite, and financial goals — both stated and inferred from conversations

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                       Communication Layer                      │
│             (Telegram Bot / Email + SMS + WhatsApp)             │
└─────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                         FastAPI Backend                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │   Webhooks  │  │    Users    │  │   Notifs    │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
└─────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                         AI Agent Layer                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │  Ampr Chat  │  │  Onboarding │  │ DeFi Analyst│              │
│  │   (Core)    │  │   Agent     │  │   Module    │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
└─────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Convex Database                           │
│   Users │ Profiles │ Chats │ Messages │ Assets │ Portfolios     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Technology Stack

| Layer | Technology |
|-------|------------|
| **API Framework** | FastAPI (Python) |
| **AI Orchestration** | Pydantic AI |
| **LLM Provider** | Mistral (mistral-large-latest) |
| **Database** | Convex (relational + vector storage) |
| **Messaging** | Telegram (aiogram) |
| **Deployment** | Railway |
| **Package Management** | Poetry (Python) / Bun (TypeScript for Convex) |

---

## Project Structure

```
ampr-core-backend/
├── src/
│   ├── agents/              # AI agents powered by Pydantic AI
│   │   ├── amprChat.py      # Core conversational agent
│   │   ├── onboarding.py    # New user onboarding flow
│   │   ├── extractor.py     # Data extraction utilities
│   │   ├── preprocessor.py  # Message preprocessing
│   │   └── summarizer.py    # Conversation summarization
│   │
│   ├── api/                 # FastAPI route handlers
│   │   ├── telegram_ingestion.py  # Telegram webhook handlers
│   │   ├── testing_ingestion.py   # Local REST testing endpoint
│   │   ├── users.py         # User management endpoints
│   │   ├── notifications.py # Notification endpoints
│   │   ├── countries.py     # Country data endpoints
│   │   └── responses.py     # AI response generation
│   │
│   ├── modules/             # Pluggable agent modules
│   │   ├── defianalyst/     # Crypto market data (CoinGecko)
│   │   ├── base.py          # Base module class
│   │   ├── registry.py      # Module discovery & routing
│   │   └── modules.yaml     # Module configuration
│   │
│   ├── clients/             # External service clients
│   │   ├── convex_client.py # Convex database client
│   │   └── telegram_client.py
│   │
│   ├── models/              # Pydantic data models
│   ├── notifications/       # Notification queue & delivery
│   ├── config/              # Configuration (Telegram, etc.)
│   └── main.py              # FastAPI application entry
│
├── convex/                  # Convex database schema & functions
│   ├── schema.ts            # Database schema definition
│   ├── tables/              # Table definitions
│   │   ├── users.ts
│   │   ├── profiles.ts
│   │   ├── messaging.ts
│   │   └── ...
│   └── *.ts                 # Query/mutation functions
│
├── pyproject.toml           # Python dependencies (Poetry)
├── package.json             # Node dependencies (Convex)
└── Procfile                 # Railway deployment config
```

---

## Core Components

### 1. Ampr Chat Agent (`src/agents/amprChat.py`)

The primary conversational AI that handles user interactions. Features:
- Investment preference awareness via user profile tools
- Content restrictions (won't provide financial advice without module data)
- Multi-message response format for natural conversation flow

### 2. Onboarding Agent (`src/agents/onboarding.py`)

Guides new users through account setup:
- Collects name, email, phone progressively
- Links Telegram accounts to existing users
- Marks onboarding complete when essential info is gathered

### 3. Module System (`src/modules/`)

Extensible architecture for specialized agents:
- **DeFi Analyst**: Real-time crypto data via CoinGecko API
  - Price lookups, market cap rankings
  - Historical comparisons, ATH/ATL data
  - Top gainers/losers across timeframes
- Modules are triggered via `&mention` syntax (e.g., `&defianalyst what's bitcoin's price?`)

### 4. Ingestion Modules

Processes incoming messages from external services:
- **Telegram Ingestion** (`src/api/telegram_ingestion.py`): Bot updates, inline keyboards, contact sharing, account linking
- **Testing Ingestion** (`src/api/testing_ingestion.py`): Local REST endpoint for development/testing (no auth)

---

## Database Schema (Convex)

Key tables:

| Table | Purpose |
|-------|---------|
| `users` | Core user data (name, email, phone, telegram_id) |
| `profiles` | Investment preferences, risk appetite, KYC status |
| `chats` | Conversation containers per user |
| `messages` | Individual messages with role (user/assistant) |
| `summaries` | Compressed conversation history |
| `assets` | Tracked financial assets |
| `portfolioItems` | User portfolio holdings |
| `modules` | Registered agent modules |
| `notificationQueue` | Pending notifications |

---

## Getting Started

### Prerequisites

- Python 3.10+
- Poetry
- Node.js / Bun (for Convex)
- Convex account

### Installation

```bash
# Clone the repository
git clone https://github.com/amprfi/ampr-core-backend.git
cd ampr-core-backend

# Install Python dependencies
poetry install

# Install Node dependencies (for Convex)
bun install

# Set up environment variables
cp .env.example .env
# Edit .env with your credentials
```

### Environment Variables

```bash
# Convex
CONVEX_URL=https://your-deployment.convex.cloud

# Mistral AI
MISTRAL_API_KEY=your-mistral-key

# Telegram
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_WEBHOOK_SECRET=your-webhook-secret

# CoinGecko (for DeFi Analyst module)
COINGECKO_API_KEY=your-coingecko-key
```

### Running Locally

```bash
# Start Convex dev server
bun run convex dev

# Start FastAPI server
poetry run uvicorn src.main:fast_api --reload --port 8000

# Or use the local REST endpoint for testing
curl -X POST http://localhost:8000/api/webhooks/rest-message \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello!", "from_number": "+1234567890", "to_number": "+0987654321"}'
```

### Deployment (Railway)

The app is configured for Railway via `Procfile`:

```
web: poetry run uvicorn src.main:fast_api --host 0.0.0.0 --port $PORT
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Health check |
| `POST` | `/api/webhooks/telegram` | Telegram bot updates |
| `POST` | `/api/webhooks/rest-message` | Local dev endpoint |
| `*` | `/api/users/*` | User management |
| `*` | `/api/notifications/*` | Notification management |
| `*` | `/api/countries/*` | Country data |

---

## Development

### Adding a New Module

1. Create a new directory in `src/modules/your_module/`
2. Implement the `BaseModule` interface
3. Register in `modules.yaml`
4. The module will be invoked when users mention `@your_module`

### Testing

```bash
poetry run pytest
```

---

## License

Proprietary - Ampersand Financial Inc.

---

## Contact

- **Founder**: Chris Georgen
- **GitHub**: [@amprfi](https://github.com/amprfi)
