**EAU Confessions Bot — Render deployment**

- **Purpose**: Run the Telegram anonymous confessions bot as a long-running worker on Render.

- **Files added**:
  - `app.py` — main bot entrypoint (reads config from environment variables)
  - `requirements.txt` — Python dependencies
  - `render.yaml` — optional Render service template (no secrets included)
  - `Procfile` — declares a `worker` process

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
```

2. Install deps and run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

**Deploy to Render (summary)**
1. Push your repository to GitHub/GitLab/Bitbucket and connect it to Render.

2. Choose deployment mode:
  - Quick (polling worker): Create a **Worker** service. Start command: `python app.py`.
  - Recommended (webhook): Create a **Web Service** so you get an HTTPS domain and set `WEBHOOK_HOST` to that domain. Start command: `python app.py`.

3. In the service settings set the build command to `pip install -r requirements.txt` (or leave blank to use defaults).

4. Add environment variables in the Render dashboard:
  - `API_TOKEN` (required)
  - `CHANNEL_ID` (optional)
  - `WEBHOOK_HOST` (set for webhook mode, e.g. `https://your-service.onrender.com`)

5. Deploy — Render will install dependencies and start the service.

**Webhook notes**
- If you set `WEBHOOK_HOST`, the app will attempt to set the Telegram webhook to `WEBHOOK_HOST + /webhook/<botid>` on startup and run a small HTTP server to receive updates. Use the Web Service option so the domain is HTTPS-accessible.
- If you don't set `WEBHOOK_HOST`, the app falls back to long-polling (worker mode).

**Notes & caveats**
- SQLite is file-based: on Render the filesystem is ephemeral for some service types. Data will persist only for the lifetime of the instance and can be lost on redeploys. For reliable persistence consider switching to a managed DB (Postgres) and updating the code.
- `API_TOKEN` is required; the app will exit if missing.
- This project keeps secrets out of the repository; configure them in Render's environment settings.

If you want, I can:
- Add Postgres support (migrations + simple adapter), or
- Convert this to a small HTTP wrapper so Render's HTTP service healthchecks are satisfied.
