**EAU Confessions Bot — Render deployment**

- **Purpose**: Run the Telegram anonymous confessions bot as a long-running worker on Render.

- **Files added**:
  - `app.py` — main bot entrypoint (reads config from environment variables)
  - `requirements.txt` — Python dependencies
  - `render.yaml` — optional Render service template (no secrets included)
  - `Procfile` — declares a `web` process

**Required environment variables (set in Render dashboard or locally):**
- `API_TOKEN` — Telegram bot token (required)
- `CHANNEL_ID` — Telegram channel chat id (optional; integer, e.g. `-1001234567890`)
- `DB_PATH` — optional path to the sqlite DB file (defaults to `eaubot.db`)
- `CONFESSION_NAME`, `CONFESSION_COOLDOWN`, etc. can be set as env vars if desired.

**Quick local run (PowerShell)**

1. Create a `.env` in project root with keys (only for local testing):

```powershell
$env:API_TOKEN = "your_token_here"
$env:CHANNEL_ID = "-1001234567890"
# or create .env file and install python-dotenv
