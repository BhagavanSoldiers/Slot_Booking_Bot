# Saveetha Booking Assistant — Single Window Agent

The desktop agent now opens as **one application window**. The booking controls are on the left and the Saveetha learner portal is on the right.

## Start

Double-click **Start Saveetha Agent.bat**.

The first run creates `.venv`, installs Python packages including PySide6/Qt WebEngine, and installs Playwright Chromium. Later launches reuse the environment.

You no longer need to paste an agent token when using the embedded single-window UI. The local UI receives a temporary token from the agent itself.

## Architecture

- Left pane: the same booking website UI, served locally by the agent.
- Right pane: Saveetha learner portal in an embedded Qt WebEngine view.
- Background: Playwright runs headlessly for automation.
- After successful Saveetha login, the authenticated Playwright cookies are copied to the embedded portal view.

Credentials stay in RAM for the current session and are not written to disk by the agent.
