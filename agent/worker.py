import copy
import queue
import threading
import time
from datetime import datetime

import bot_dynamic_threadsafe as core


class BotWorker:
    """Single-owner Playwright worker.

    All Playwright objects are created and used on this worker thread. Saveetha
    credentials exist only in memory for the current agent session.
    """

    def __init__(self):
        self.commands = queue.Queue()
        self.thread = threading.Thread(target=self._run, daemon=True, name="saveetha-bot-worker")
        self.stop_event = threading.Event()
        self.browser = None
        self.context = None
        self.page = None
        self.playwright = None
        self.credentials = None
        self.logs = []
        self.logs_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.state = {
            "status": "logged_out",
            "logged_in": False,
            "preview_slots": [],
            "events": [],
            "times": [],
            "venues": [],
            "selected_event": "",
            "selected_dates": [],
            "booked": {},
        }
        self.thread.start()

    def log(self, message):
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {message}"
        with self.logs_lock:
            self.logs.append(line)
            self.logs = self.logs[-500:]

    def get_logs(self):
        with self.logs_lock:
            return list(self.logs)

    def clear_logs(self):
        with self.logs_lock:
            self.logs.clear()

    def get_state(self):
        with self.state_lock:
            return copy.deepcopy(self.state)

    def set_state(self, **updates):
        with self.state_lock:
            self.state.update(updates)

    def submit(self, command, payload=None):
        reply = queue.Queue(maxsize=1)
        self.commands.put((command, payload or {}, reply))
        return reply.get()

    def enqueue(self, command, payload=None):
        self.commands.put((command, payload or {}, None))

    def request_stop(self):
        self.stop_event.set()
        core.STOP_BOT = True
        self.log("!!! STOP REQUESTED !!!")

    def _run(self):
        while True:
            command, payload, reply = self.commands.get()
            try:
                if command == "login":
                    result = self.login(payload)
                elif command == "logout":
                    result = self.logout()
                elif command == "preview":
                    result = self.preview(payload)
                elif command == "test":
                    result = self.test_selection(payload)
                elif command == "start":
                    result = self.start_booking(payload)
                elif command == "shutdown":
                    result = {"ok": True}
                    if reply is not None:
                        reply.put(result)
                    self._cleanup()
                    return
                else:
                    result = {"ok": False, "error": f"Unknown command: {command}"}

                if reply is not None:
                    reply.put(result)
            except Exception as exc:
                self.log(f"ERROR: {exc}")
                if reply is not None:
                    reply.put({"ok": False, "error": str(exc)})
                self.set_state(status="error")

    def login(self, payload):
        username = (payload.get("username") or "").strip()
        password = payload.get("password") or ""
        if not username or not password:
            return {"ok": False, "error": "Enter your Saveetha login ID and password."}

        self._cleanup()
        self.clear_logs()
        self.set_state(
            status="logging_in",
            logged_in=False,
            preview_slots=[],
            events=[],
            times=[],
            venues=[],
            selected_event="",
            selected_dates=[],
            booked={},
        )
        self.log("Connecting to the fixed Saveetha learner portal...")

        self.credentials = (username, password)
        self.stop_event.clear()
        core.STOP_BOT = False

        try:
            self.playwright = core.sync_playwright().start()
            self.browser = self.playwright.chromium.launch(headless=False)
            self.context = self.browser.new_context()
            self.page = self.context.new_page()
            core.login(self.page, self.log, username, password)
            core.open_bookings(self.page, self.log)
            self.set_state(status="logged_in", logged_in=True)
            self.log("✓ App login successful. Ready to scan bookings.")
            return {"ok": True, "state": self.get_state(), "logs": self.get_logs()}
        except Exception:
            self._cleanup()
            self.credentials = None
            self.set_state(status="login_failed", logged_in=False)
            raise

    def logout(self):
        self.request_stop()
        self._cleanup()
        self.credentials = None
        self.clear_logs()
        self.set_state(
            status="logged_out",
            logged_in=False,
            preview_slots=[],
            events=[],
            times=[],
            venues=[],
            selected_event="",
            selected_dates=[],
            booked={},
        )
        return {"ok": True, "state": self.get_state()}

    def _require_login(self):
        if not self.page or self.page.is_closed() or not self.credentials:
            raise RuntimeError("Please log in with your Saveetha ID and password first.")

    @staticmethod
    def _serialize(slot):
        return {
            "title": slot["title"],
            "date": slot["date"].isoformat(),
            "start": slot["start"],
            "end": slot["end"],
            "duration": slot["duration"],
            "venue": slot["venue"],
            "status": slot["status"],
            "available": slot["available"],
            "session": core.fmt_session(slot),
        }

    def preview(self, payload):
        self._require_login()
        dates = [datetime.strptime(x, "%Y-%m-%d").date() for x in payload["dates"]]
        self.stop_event.clear()
        core.STOP_BOT = False
        self.set_state(status="scanning", selected_dates=[x.isoformat() for x in dates], selected_event="", booked={})
        self.clear_logs()
        self.log("PREVIEW SCAN — read-only; no booking will be performed.")
        self.log("Dates: " + ", ".join(d.strftime("%d/%m/%Y") for d in dates))

        core.apply_preview_filter(self.page, dates, self.log)
        slots = core.scan_cards(self.page, dates, self.log)

        self.set_state(
            preview_slots=[self._serialize(s) for s in slots],
            events=sorted({s["title"] for s in slots}),
            times=sorted({core.fmt_session(s) for s in slots}, key=lambda x: core.parse_session(x)[0] or 9999),
            venues=sorted({s["venue"] for s in slots if s["venue"]}),
            status="ready",
        )
        self.log(f"Detected {len(slots)} sessions.")
        self.log("Preview complete.")
        return {"ok": True, "state": self.get_state(), "logs": self.get_logs()}

    def _state_slots_as_core(self):
        dates = [datetime.strptime(x, "%Y-%m-%d").date() for x in self.get_state()["selected_dates"]]
        return dates, core.scan_cards(self.page, dates, self.log)

    def test_selection(self, payload):
        self._require_login()
        event = payload["event"]
        times = payload["times"]
        venues = payload["venues"]
        per_date = int(payload["slots_per_date"])

        dates, slots = self._state_slots_as_core()
        chosen = core.choose_slots(slots, event, times, venues, per_date, require_bookable=False)
        result = [self._serialize(s) for s in chosen]
        self.set_state(selected_event=event, status="tested")
        self.log("TEST SELECTION — NO BOOKING PERFORMED.")
        for s in result:
            self.log(f"  {s['date']} | {s['title']} | {s['session']} | Venue {s['venue']} | {s['status']}")
        return {"ok": True, "selected": result, "logs": self.get_logs(), "state": self.get_state()}

    def start_booking(self, payload):
        self._require_login()
        dates = [datetime.strptime(x, "%Y-%m-%d").date() for x in payload["dates"]]
        event = payload["event"]
        times = payload["times"]
        venues = payload["venues"]
        per_date = max(1, int(payload["slots_per_date"]))
        purpose = payload.get("purpose", "CIA").strip() or "CIA"
        monitor = bool(payload.get("monitor", True))
        retry = max(2, int(payload.get("retry", 5)))

        self.stop_event.clear()
        core.STOP_BOT = False
        self.set_state(status="booking", selected_event=event)
        self.log("START BOOKING — actual booking attempts enabled.")

        booked = {d: 0 for d in dates}
        used = {d: [] for d in dates}
        self.set_state(booked={d.isoformat(): 0 for d in dates})

        while not self.stop_event.is_set():
            core.apply_preview_filter(self.page, dates, self.log)
            slots = core.scan_cards(self.page, dates, self.log)
            chosen = core.choose_slots(slots, event, times, venues, per_date, require_bookable=True)

            progress = False
            for slot in chosen:
                if self.stop_event.is_set():
                    break

                d = slot["date"]
                if booked[d] >= per_date:
                    continue
                if any(core.overlap(slot, used_slot) for used_slot in used[d]):
                    continue

                if core.book_slot(self.page, slot, purpose, self.log):
                    booked[d] += 1
                    used[d].append(slot)
                    progress = True
                    self.set_state(booked={day.isoformat(): n for day, n in booked.items()})
                    self.log(f"✓ {d}: {booked[d]}/{per_date} booked")
                    core.refresh_page(self.page, self.log)

            if all(booked[d] >= per_date for d in dates):
                self.set_state(status="completed", booked={d.isoformat(): n for d, n in booked.items()})
                self.log("ALL REQUIRED BOOKINGS COMPLETED.")
                return {"ok": True, "status": "completed", "booked": {d.isoformat(): n for d, n in booked.items()}}

            if not monitor:
                self.set_state(status="stopped", booked={d.isoformat(): n for d, n in booked.items()})
                self.log("Retry monitor OFF. Stopping after current scan.")
                return {"ok": True, "status": "stopped", "booked": {d.isoformat(): n for d, n in booked.items()}}

            if not progress:
                self.log(f"No matching available slot yet. Refreshing in {retry} seconds...")
                for _ in range(retry * 10):
                    if self.stop_event.is_set():
                        break
                    time.sleep(0.1)

        self.set_state(status="stopped", booked={d.isoformat(): n for d, n in booked.items()})
        self.log("BOT STOPPED.")
        return {"ok": True, "status": "stopped", "booked": {d.isoformat(): n for d, n in booked.items()}}

    def _cleanup(self):
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass
        try:
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass
        self.browser = self.context = self.page = self.playwright = None
