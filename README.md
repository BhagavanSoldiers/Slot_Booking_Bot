# Saveetha Booking Assistant — Vercel + Local Agent

This project separates the UI from the browser automation:

```text
Vercel website
     |
     | HTTPS
     v
Student's browser
     |
     | localhost:8765
     v
Local Agent on student's PC
     |
     v
Playwright -> Saveetha learner portal
```

## Folders

- `website/` — static frontend. Deploy this folder to Vercel.
- `agent/` — local FastAPI + Playwright agent. Each student runs it on their own PC.

## Important security model

- Saveetha credentials are sent only to `127.0.0.1:8765`.
- Credentials are kept in memory only for the current local-agent session.
- The agent does not write credentials to files or return them in API responses.
- The local agent generates a random access token every time it starts. The user enters that token into the website. The token is required for local API calls.
- The Saveetha portal URL is fixed inside `agent/bot_dynamic_threadsafe.py`.
- Do not commit passwords, tokens, `.env` files, browser profiles, or cookies.

## Deploy the website to Vercel

1. Create a GitHub repository and upload the project.
2. In Vercel, import the repository.
3. Set **Root Directory** to `website`.
4. Deploy.
5. The website will be available at your Vercel URL.

No backend is deployed to Vercel. Vercel only serves the static HTML/CSS/JS.

## Run the local agent on Windows

1. Install Python 3.11 or newer.
2. Double-click `agent/run_agent.bat`.
3. On the first run it creates `.venv`, installs dependencies, and installs Playwright Chromium.
4. The terminal prints an `Agent token`.
5. Open the Vercel website and paste that token into the **Local Agent** connection box.
6. Sign in with the student's own Saveetha credentials.
7. Keep the agent terminal open while the bot is being used.

The agent listens only on `127.0.0.1:8765`; it is not exposed directly to the internet.

## Local testing of the website

You can open `website/index.html` directly, but some browsers may restrict localhost requests from `file://`. For local testing, serve the website with any simple static HTTP server, or use the deployed Vercel URL.

## Playwright policy

The bot uses normal browser automation against the Saveetha portal. It does not contain CAPTCHA bypasses, rate-limit bypasses, credential harvesting, or authentication-protection bypasses. Use a reasonable retry interval.
