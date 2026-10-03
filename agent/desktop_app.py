"""Single-window desktop shell for the Saveetha booking agent.

The visible Saveetha portal is rendered inside Qt WebEngine. Playwright runs
headless in the worker thread for reliable automation, so no second Chromium
window is opened. The authenticated cookies are synchronized from Playwright
to the embedded web view after login.
"""

import sys
import threading
from datetime import datetime

from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView

from main import AGENT_TOKEN, HOST, PORT, app, worker

BASE_URL = "https://learner.saveetha.in/"
BOOKING_URL = BASE_URL + "academicevents/event-booking/"


class WorkerSignals(QObject):
    finished = Signal(str, object)


class CommandRunner:
    """Run blocking BotWorker commands away from the Qt GUI thread."""

    def __init__(self, owner):
        self.owner = owner
        self.signals = WorkerSignals()

    def run(self, command, payload=None):
        threading.Thread(
            target=self._target,
            args=(command, payload or {}),
            daemon=True,
        ).start()

    def _target(self, command, payload):
        try:
            result = worker.submit(command, payload)
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        self.signals.finished.emit(command, result)


class SaveethaView(QWebEngineView):
    def __init__(self, parent=None):
        super().__init__(parent)
        profile = QWebEngineProfile.defaultProfile()
        page = QWebEnginePage(profile, self)
        self.setPage(page)
        self.loadFinished.connect(self._loaded)

    @Slot(bool)
    def _loaded(self, ok):
        if ok:
            self.page().runJavaScript(
                "document.title = document.title || 'Saveetha Learner Portal';"
            )

    def clear_session(self):
        self.page().profile().cookieStore().deleteAllCookies()
        self.page().profile().clearHttpCache()
        self.page().profile().clearAllVisitedLinks()

    def sync_cookies(self, cookies):
        store = self.page().profile().cookieStore()
        for raw in cookies:
            cookie = QNetworkCookie()
            cookie.setName(raw.get("name", "").encode())
            cookie.setValue(raw.get("value", "").encode())
            domain = raw.get("domain") or "learner.saveetha.in"
            cookie.setDomain(domain)
            cookie.setPath(raw.get("path") or "/")
            cookie.setSecure(bool(raw.get("secure", False)))
            cookie.setHttpOnly(bool(raw.get("httpOnly", False)))
            expires = raw.get("expires")
            if isinstance(expires, (int, float)) and expires > 0:
                from PySide6.QtCore import QDateTime
                cookie.setExpirationDate(QDateTime.fromSecsSinceEpoch(int(expires)))
            # Use the learner host for host-only cookies.
            url = QUrl("https://learner.saveetha.in/")
            store.setCookie(cookie, url)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Saveetha Booking Assistant")
        self.resize(1400, 850)
        self.runner = CommandRunner(self)
        self.runner.signals.finished.connect(self.command_finished)
        self._last_status = None
        self._last_booked = None
        self._build_ui()
        self._start_state_timer()

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        header = QFrame()
        header.setFrameShape(QFrame.StyledPanel)
        h = QHBoxLayout(header)
        h.setContentsMargins(10, 8, 10, 8)

        title = QLabel("<b>Saveetha Booking Assistant</b>")
        title.setStyleSheet("font-size: 18px;")
        h.addWidget(title)
        h.addStretch()
        self.status_label = QLabel("Agent: logged out")
        h.addWidget(self.status_label)
        outer.addWidget(header)

        splitter = QSplitter()
        splitter.setOrientation(1)  # Horizontal
        outer.addWidget(splitter, 1)

        # Left control panel.
        controls = QWidget()
        controls.setMinimumWidth(300)
        controls.setMaximumWidth(360)
        c = QVBoxLayout(controls)
        c.setContentsMargins(8, 8, 8, 8)
        c.setSpacing(8)

        c.addWidget(QLabel("<b>Saveetha Login</b>"))
        self.username = QLineEdit()
        self.username.setPlaceholderText("Saveetha Login ID")
        c.addWidget(self.username)

        self.password = QLineEdit()
        self.password.setPlaceholderText("Password")
        self.password.setEchoMode(QLineEdit.Password)
        c.addWidget(self.password)

        self.login_btn = QPushButton("Login & Open Portal")
        self.login_btn.clicked.connect(self.login)
        c.addWidget(self.login_btn)

        self.logout_btn = QPushButton("Logout")
        self.logout_btn.clicked.connect(self.logout)
        self.logout_btn.setEnabled(False)
        c.addWidget(self.logout_btn)

        c.addSpacing(10)
        c.addWidget(QLabel("<b>Portal</b>"))
        self.bookings_btn = QPushButton("Open Bookings")
        self.bookings_btn.clicked.connect(lambda: self.portal.setUrl(QUrl(BOOKING_URL)))
        self.bookings_btn.setEnabled(False)
        c.addWidget(self.bookings_btn)

        self.refresh_btn = QPushButton("Refresh Portal")
        self.refresh_btn.clicked.connect(self.portal.reload)
        self.refresh_btn.setEnabled(False)
        c.addWidget(self.refresh_btn)

        c.addSpacing(10)
        c.addWidget(QLabel("<b>Agent connection</b>"))
        token = QLineEdit(AGENT_TOKEN)
        token.setReadOnly(True)
        c.addWidget(token)
        copy_btn = QPushButton("Copy Agent Token")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(AGENT_TOKEN))
        c.addWidget(copy_btn)
        c.addWidget(QLabel(f"API: http://{HOST}:{PORT}"))

        c.addStretch()
        c.addWidget(QLabel("Automation runs headless; the Saveetha portal stays inside this window."))

        self.portal = SaveethaView()
        self.portal.setUrl(QUrl(BASE_URL))

        splitter.addWidget(controls)
        splitter.addWidget(self.portal)
        splitter.setSizes([330, 1070])

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")

    def _start_state_timer(self):
        self.state_timer = QTimer(self)
        self.state_timer.setInterval(1200)
        self.state_timer.timeout.connect(self.refresh_state)
        self.state_timer.start()

    def refresh_state(self):
        try:
            state = worker.get_state()
        except Exception:
            return
        status = state.get("status", "unknown")
        booked = state.get("booked", {})
        self.status_label.setText(f"Agent: {status}")
        self.statusBar().showMessage(
            f"{datetime.now().strftime('%H:%M:%S')}  •  {status}"
        )
        if status != self._last_status or booked != self._last_booked:
            if status in {"ready", "tested", "booking", "completed", "stopped"}:
                if self.logout_btn.isEnabled():
                    self.portal.reload()
            self._last_status = status
            self._last_booked = dict(booked)

    def login(self):
        username = self.username.text().strip()
        password = self.password.text()
        if not username or not password:
            QMessageBox.warning(self, "Login", "Enter your Saveetha login ID and password.")
            return
        self.login_btn.setEnabled(False)
        self.status_label.setText("Agent: logging in…")
        self.runner.run("login", {"username": username, "password": password})

    def logout(self):
        self.login_btn.setEnabled(False)
        self.logout_btn.setEnabled(False)
        self.runner.run("logout")

    def command_finished(self, command, result):
        if command == "login":
            self.login_btn.setEnabled(True)
            if not result.get("ok"):
                QMessageBox.critical(self, "Login failed", result.get("error", "Login failed"))
                return
            self.logout_btn.setEnabled(True)
            self.bookings_btn.setEnabled(True)
            self.refresh_btn.setEnabled(True)
            cookies_result = worker.submit("cookies")
            self.portal.sync_cookies(cookies_result.get("cookies", []))
            QTimer.singleShot(500, lambda: self.portal.setUrl(QUrl(BOOKING_URL)))
            self.statusBar().showMessage("Logged in — embedded Saveetha portal is ready.")
        elif command == "logout":
            self.login_btn.setEnabled(True)
            self.logout_btn.setEnabled(False)
            self.bookings_btn.setEnabled(False)
            self.refresh_btn.setEnabled(False)
            self.portal.clear_session()
            self.portal.setUrl(QUrl(BASE_URL))
            self.statusBar().showMessage("Logged out")

    def closeEvent(self, event):
        try:
            worker.request_stop()
            worker.submit("shutdown")
        except Exception:
            pass
        event.accept()


def run_server():
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


def main():
    # API remains available for the existing website while the desktop shell
    # provides the single visible application window.
    server_thread = threading.Thread(target=run_server, daemon=True, name="saveetha-api")
    server_thread.start()

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("Saveetha Booking Assistant")
    window = MainWindow()
    window.show()
    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()
