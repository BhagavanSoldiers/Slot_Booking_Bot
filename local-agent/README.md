# Local Agent

The local agent runs FastAPI and Playwright on the student's own Windows computer.

## Start

Double-click `run_agent.bat`.

On startup it prints something like:

```text
Agent token: 4f7b... 
Local API:  http://127.0.0.1:8765
```

Paste the token into the website's Local Agent connection box.

## Data handling

The agent keeps Saveetha username/password only in RAM for the current session. Logout closes the browser and clears the credentials.

The access token is generated on every launch and is not saved to disk.
