# TrustMark Bot

Production-ready Telegram bot for reputation checks, anti-scam reports, guarantors, trusted users and deal-risk cards.

Owner and creator: [@Vexsento](https://t.me/Vexsento)

## Stack

- Python 3.11+
- aiogram 3
- PostgreSQL
- SQLAlchemy Async ORM
- asyncpg
- Alembic
- Pillow
- python-dotenv

## Quick Start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env`, then run migrations:

```bash
docker compose up -d postgres
alembic upgrade head
python -m app.main
```

## Group Checks

In any chat where the bot is present:

- `чек @username`
- `чек 7258447737`
- `чек ми`
- reply to a user's message with `чек`

Telegram usernames can be changed. TrustMark stores username history and always treats Telegram user ID as the main identifier.
