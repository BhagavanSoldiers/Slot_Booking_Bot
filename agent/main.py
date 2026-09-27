from contextlib import asynccontextmanager
import secrets
import threading

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from worker import BotWorker

HOST = "127.0.0.1"
PORT = 8765
AGENT_TOKEN = secrets.token_urlsafe(32)
worker = BotWorker()


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=300)


class PreviewRequest(BaseModel):
    dates: list[str] = Field(min_length=1)


class SelectionRequest(BaseModel):
    event: str = Field(min_length=1)
    times: list[str]
    venues: list[str]
    slots_per_date: int = Field(default=1, ge=1, le=10)


class BookingRequest(SelectionRequest):
    dates: list[str] = Field(min_length=1)
    purpose: str = Field(default="CIA", max_length=255)
    monitor: bool = True
    retry: int = Field(default=5, ge=2, le=60)
    confirmed: bool = False


@asynccontextmanager
async def lifespan(app):
    yield
    worker.submit("shutdown")


app = FastAPI(title="Saveetha Booking Local Agent", lifespan=lifespan)

# The access token is the actual authorization mechanism. CORS is permissive so
# the same agent can be used from a student's deployed Vercel URL.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Agent-Token"],
)


def authorize(token: str | None):
    if not token or not secrets.compare_digest(token, AGENT_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid or missing local agent token.")


@app.get("/api/health")
def health(x_agent_token: str | None = Header(default=None)):
    authorize(x_agent_token)
    s = worker.get_state()
    return {
        "ok": True,
        "agent": "saveetha-booking-agent",
        "logged_in": s["logged_in"],
        "status": s["status"],
    }


@app.get("/api/state")
def state(x_agent_token: str | None = Header(default=None)):
    authorize(x_agent_token)
    return worker.get_state()


@app.get("/api/logs")
def logs(x_agent_token: str | None = Header(default=None)):
    authorize(x_agent_token)
    return {"logs": worker.get_logs()}


@app.post("/api/login")
def login(req: LoginRequest, x_agent_token: str | None = Header(default=None)):
    authorize(x_agent_token)
    result = worker.submit("login", req.model_dump())
    if not result.get("ok"):
        raise HTTPException(status_code=401, detail=result.get("error", "Login failed"))
    return result


@app.post("/api/logout")
def logout(x_agent_token: str | None = Header(default=None)):
    authorize(x_agent_token)
    return worker.submit("logout")


@app.post("/api/preview")
def preview(req: PreviewRequest, x_agent_token: str | None = Header(default=None)):
    authorize(x_agent_token)
    if not worker.get_state()["logged_in"]:
        raise HTTPException(status_code=401, detail="Log in first.")
    return worker.submit("preview", req.model_dump())


@app.post("/api/test-selection")
def test_selection(req: SelectionRequest, x_agent_token: str | None = Header(default=None)):
    authorize(x_agent_token)
    if not worker.get_state()["logged_in"]:
        raise HTTPException(status_code=401, detail="Log in first.")
    return worker.submit("test", req.model_dump())


@app.post("/api/start-booking")
def start_booking(req: BookingRequest, x_agent_token: str | None = Header(default=None)):
    authorize(x_agent_token)
    if not worker.get_state()["logged_in"]:
        raise HTTPException(status_code=401, detail="Log in first.")
    if not req.confirmed:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required before actual booking.")
    worker.enqueue("start", req.model_dump())
    return {"ok": True, "status": "booking"}


@app.post("/api/stop")
def stop(x_agent_token: str | None = Header(default=None)):
    authorize(x_agent_token)
    worker.request_stop()
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    print("===============================================")
    print("   Saveetha Booking Assistant - Local Agent")
    print("===============================================")
    print(f"Local API:  http://{HOST}:{PORT}")
    print(f"Agent token: {AGENT_TOKEN}")
    print("Keep this window open while using the website.")
    print()
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
