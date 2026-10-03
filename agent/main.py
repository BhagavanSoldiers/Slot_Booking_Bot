from contextlib import asynccontextmanager
from pathlib import Path
import secrets
import threading

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from worker import BotWorker

HOST = "127.0.0.1"
PORT = 8765
AGENT_TOKEN = secrets.token_urlsafe(32)
ROOT = Path(__file__).resolve().parent
WEBSITE_DIR = ROOT / "website"
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
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
                   allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Content-Type", "X-Agent-Token"])

def authorize(token: str | None):
    if not token or not secrets.compare_digest(token, AGENT_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid or missing local agent token.")

@app.get("/api/bootstrap")
def bootstrap():
    return {"ok": True, "agent_token": AGENT_TOKEN, "embedded": True}
@app.get("/api/health")
def health(x_agent_token: str | None = Header(default=None)):
    authorize(x_agent_token); s=worker.get_state()
    return {"ok":True,"agent":"saveetha-booking-agent","logged_in":s["logged_in"],"status":s["status"]}
@app.get("/api/state")
def state(x_agent_token: str | None = Header(default=None)):
    authorize(x_agent_token); return worker.get_state()
@app.get("/api/logs")
def logs(x_agent_token: str | None = Header(default=None)):
    authorize(x_agent_token); return {"logs":worker.get_logs()}
@app.get("/api/portal-cookies")
def portal_cookies(x_agent_token: str | None = Header(default=None)):
    authorize(x_agent_token); return worker.submit("cookies")
@app.post("/api/login")
def login(req: LoginRequest, x_agent_token: str | None = Header(default=None)):
    authorize(x_agent_token); result=worker.submit("login",req.model_dump())
    if not result.get("ok"): raise HTTPException(status_code=401,detail=result.get("error","Login failed"))
    return result
@app.post("/api/logout")
def logout(x_agent_token: str | None = Header(default=None)):
    authorize(x_agent_token); return worker.submit("logout")
@app.post("/api/preview")
def preview(req: PreviewRequest, x_agent_token: str | None = Header(default=None)):
    authorize(x_agent_token)
    if not worker.get_state()["logged_in"]: raise HTTPException(status_code=401,detail="Log in first.")
    return worker.submit("preview",req.model_dump())
@app.post("/api/test-selection")
def test_selection(req: SelectionRequest, x_agent_token: str | None = Header(default=None)):
    authorize(x_agent_token)
    if not worker.get_state()["logged_in"]: raise HTTPException(status_code=401,detail="Log in first.")
    return worker.submit("test",req.model_dump())
@app.post("/api/start-booking")
def start_booking(req: BookingRequest, x_agent_token: str | None = Header(default=None)):
    authorize(x_agent_token)
    if not worker.get_state()["logged_in"]: raise HTTPException(status_code=401,detail="Log in first.")
    if not req.confirmed: raise HTTPException(status_code=400,detail="Explicit confirmation is required before actual booking.")
    worker.enqueue("start",req.model_dump()); return {"ok":True,"status":"booking"}
@app.post("/api/stop")
def stop(x_agent_token: str | None = Header(default=None)):
    authorize(x_agent_token); worker.request_stop(); return {"ok":True}

@app.get("/")
def index(): return FileResponse(WEBSITE_DIR / "index.html")
app.mount("/", StaticFiles(directory=WEBSITE_DIR, html=True), name="website")

def start_api():
    import uvicorn
    uvicorn.run(app,host=HOST,port=PORT,log_level="warning")

def start_desktop():
    from PySide6.QtCore import QTimer,QUrl
    from PySide6.QtNetwork import QNetworkCookie
    from PySide6.QtWidgets import QApplication,QMainWindow,QSplitter,QWidget,QVBoxLayout,QLabel,QFrame
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEngineProfile,QWebEnginePage

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__(); self.setWindowTitle("Saveetha Booking Assistant"); self.resize(1500,900); self.setMinimumSize(1100,700)
            root=QWidget(); layout=QVBoxLayout(root); layout.setContentsMargins(0,0,0,0); layout.setSpacing(0)
            header=QFrame(); header.setObjectName("header"); hl=QVBoxLayout(header); hl.setContentsMargins(18,10,18,10)
            t=QLabel("SAVEETHA BOOKING ASSISTANT   •   SINGLE WINDOW"); t.setObjectName("title")
            st=QLabel("Booking controls and the learner portal stay in one application window."); st.setObjectName("subtitle")
            hl.addWidget(t); hl.addWidget(st); layout.addWidget(header)
            split=QSplitter(); split.setChildrenCollapsible(False)
            self.control=QWebEngineView(); self.portal=QWebEngineView()
            self.portal_profile=QWebEngineProfile(self)
            self.portal.setPage(QWebEnginePage(self.portal_profile,self.portal))
            self.portal_profile.cookieStore().deleteAllCookies()
            self.portal.setUrl(QUrl("https://learner.saveetha.in/"))
            split.addWidget(self.control); split.addWidget(self.portal); split.setSizes([650,850]); layout.addWidget(split,1); self.setCentralWidget(root)
            self.control.load(QUrl(f"http://{HOST}:{PORT}/?embedded=1")); self.last=False
            self.timer=QTimer(self); self.timer.timeout.connect(self.sync_portal); self.timer.start(1000)
            self.setStyleSheet("QMainWindow{background:#f4f6fa;} QFrame#header{background:#101722;} QLabel#title{color:white;font-size:16px;font-weight:800;} QLabel#subtitle{color:#aeb8c8;font-size:11px;} QSplitter::handle{background:#dfe4ec;width:2px;}")
        def sync_portal(self):
            try:
                logged=bool(worker.get_state().get("logged_in"))
                if logged and not self.last:
                    result=worker.submit("cookies")
                    store=self.portal_profile.cookieStore()
                    for c in result.get("cookies",[]):
                        ck=QNetworkCookie(c["name"].encode(),c["value"].encode())
                        ck.setPath(c.get("path","/"))
                        if c.get("domain"): ck.setDomain(c["domain"])
                        ck.setSecure(bool(c.get("secure",False))); ck.setHttpOnly(bool(c.get("httpOnly",False)))
                        store.setCookie(ck)
                    QTimer.singleShot(700, lambda: self.portal.setUrl(QUrl("https://learner.saveetha.in/")))
                elif not logged and self.last:
                    self.portal_profile.cookieStore().deleteAllCookies()
                    self.portal.setUrl(QUrl("https://learner.saveetha.in/"))
                self.last=logged
            except Exception: pass
        def closeEvent(self,event):
            try: self.portal_profile.cookieStore().deleteAllCookies()
            except Exception: pass
            try: worker.submit("shutdown")
            except Exception: pass
            event.accept()
    qt=QApplication([]); qt.setApplicationName("Saveetha Booking Assistant"); w=MainWindow(); w.show(); return qt.exec()

if __name__=="__main__":
    threading.Thread(target=start_api,daemon=True).start(); start_desktop()
