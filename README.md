# Saveetha Booking Assistant — Local Agent Edition

A zero-cost local-agent architecture: the website is the UI and the student's own Windows PC runs FastAPI + Playwright.

## Folders
- `website/` — colorful modern web UI. Deploy the contents of this folder to Vercel if desired.
- `local-agent/` — Windows local agent.
- `website/local-agent.zip` — downloadable copy of the local agent.

## Start
1. Open `local-agent/`.
2. Double-click `Start Saveetha Agent.bat`.
3. On first run, it creates the virtual environment, installs Python packages, and installs Chromium.
4. Copy the Agent token printed in the terminal.
5. Open the website and paste the token.
6. Log in with your own Saveetha credentials.
7. Select dates → Scan → configure priorities → Test Selection → Start Booking.

## Browser
The Playwright Chromium window starts minimized so the Saveetha portal stays out of the way while the bot runs.

## Credentials
Never put Saveetha credentials in GitHub, the website source, or this ZIP. They are entered into the website and held by the local agent only for the active session.

## Speed/reliability improvements
- Reuses the authenticated browser session.
- Avoids unnecessary scrolling.
- Uses targeted DOM locators and waits.
- Keeps the booking page filtered during monitoring instead of resubmitting the filter every cycle.
- Refreshes after a successful booking and rescans with fresh DOM state before the next booking.
- Uses a configurable retry interval (minimum 2 seconds).

The bot does not bypass CAPTCHAs, authentication protections, rate limits, or other anti-abuse controls.
