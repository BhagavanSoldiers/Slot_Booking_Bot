import os
import re
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, date
import calendar

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE_URL = "https://learner.saveetha.in/"
DEFAULT_PURPOSE = "CIA"
DEFAULT_RETRY_SECONDS = 5
STOP_BOT = False


# ------------------------- parsing helpers -------------------------

def norm(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_time(s):
    # Accept both "3 PM" and the website's "3 p.m." format.
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\.?", s, re.I)
    if not m:
        return None

    h = int(m.group(1))
    mi = int(m.group(2) or 0)
    ap = m.group(3).lower()

    if ap == "p" and h != 12:
        h += 12
    elif ap == "a" and h == 12:
        h = 0

    return h * 60 + mi


def parse_session(text):
    ms = re.findall(r"(\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?)", text, re.I)
    if len(ms) < 2:
        return None, None
    return parse_time(ms[0]), parse_time(ms[1])


def parse_date(text):
    m = re.search(r"([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})", text)
    if not m:
        return None
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(m.group(1), fmt).date()
        except ValueError:
            pass
    return None


def fmt_minute(v):
    if v is None:
        return "--"
    h, mi = divmod(v, 60)
    ap = "AM" if h < 12 else "PM"
    h = h % 12 or 12
    return f"{h}:{mi:02d} {ap}"


def fmt_session(slot):
    return f"{fmt_minute(slot['start'])} - {fmt_minute(slot['end'])}"


def duration(slot):
    if slot["start"] is None or slot["end"] is None:
        return 0
    return slot["end"] - slot["start"]


def slot_key(s):
    return (s["date"].isoformat(), s["title"], s["start"], s["end"], s["venue"])


def overlap(a, b):
    return a["start"] < b["end"] and b["start"] < a["end"]


# ------------------------- status / extraction -------------------------

def get_status(card, text, book_button):
    low = text.lower()

    # More specific states first.
    if "cancel booking" in low:
        return "ALREADY_BOOKED", False

    if "booking closed" in low:
        return "CLOSED", False

    if "waitlist open" in low:
        return "WAITLIST", False

    if "opening soon" in low:
        return "OPENING_SOON", False

    # A visible "Book Now" is only usable when the button is enabled.
    if book_button.count() > 0:
        try:
            if not book_button.first.is_disabled():
                return "BOOKABLE", True
            return "OPENING_SOON", False
        except Exception:
            return "UNKNOWN", False

    return "UNKNOWN", False


def scan_cards(page, selected_dates, log):
    wanted = set(selected_dates)
    cards = page.locator(".card")
    total = cards.count()
    log(f"Scanning {total} card elements...")

    slots = []
    for i in range(total):
        if STOP_BOT:
            break

        card = cards.nth(i)
        try:
            text = norm(card.inner_text())
            heading = card.locator("h5")
            if heading.count() == 0:
                continue
            title = norm(heading.first.inner_text())
            d = parse_date(text)
            if d not in wanted:
                continue

            start, end = parse_session(text)
            if start is None or end is None or end <= start:
                continue

            vm = re.search(r"Venue:\s*([A-Za-z0-9_-]+)", text, re.I)
            venue = vm.group(1).strip() if vm else ""

            button = card.get_by_role("button", name=re.compile(r"Book Now", re.I))
            status, available = get_status(card, text, button)

            slots.append({
                "card": card,
                "title": title,
                "date": d,
                "start": start,
                "end": end,
                "venue": venue,
                "duration": end - start,
                "status": status,
                "available": available,
                "book_button": button,
                "text": text,
            })
        except Exception:
            continue

    log(f"Detected {len(slots)} sessions.")
    return slots


# ------------------------- website helpers -------------------------

def login(page, log, username, password):
    log("Opening Saveetha learner portal...")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)

    try:
        user = page.locator('input[name="username"], input[type="text"]').first
        user.wait_for(state="visible", timeout=10000)
        log("✓ Login page detected.")

        if not username or not password:
            raise RuntimeError("Saveetha login ID and password are required.")

        user.fill(username)
        page.locator('input[type="password"]').first.fill(password)

        sign_in = page.get_by_role("button", name=re.compile(r"Sign in|Login", re.I))
        if sign_in.count() == 0:
            sign_in = page.locator('input[type="submit"]').first
        sign_in.click()
        log("✓ Automatic login submitted.")
    except PlaywrightTimeoutError:
        log("Login page did not appear; checking active session...")

    page.wait_for_load_state("domcontentloaded", timeout=30000)
    page.get_by_text("Bookings", exact=True).wait_for(state="visible", timeout=15000)
    log("✓ Successfully logged in.")


def open_bookings(page, log):
    log("Opening Bookings...")
    page.get_by_text("Bookings", exact=True).click()
    page.wait_for_url(re.compile(r".*/academicevents/event-booking/.*"), timeout=15000)
    page.get_by_text("Event Term", exact=False).wait_for(state="visible", timeout=15000)
    log("✓ Booking page opened.")
    log(f"URL: {page.url}")


def set_event_term_all(page):
    sel = page.locator('select[name="event_term"]')
    if sel.count() == 0:
        return
    opts = sel.locator("option")
    for i in range(opts.count()):
        opt = opts.nth(i)
        if norm(opt.inner_text()).lower() == "all":
            sel.select_option(value=opt.get_attribute("value") or "")
            return
    sel.select_option("")


def apply_preview_filter(page, selected_dates, log):
    if not selected_dates:
        raise ValueError("Select at least one booking date.")

    set_event_term_all(page)

    # IMPORTANT: no event-title filter here. Preview must discover all events.
    title = page.locator('input[name="slot_name"]')
    if title.count():
        title.fill("")

    frm = page.locator('input[name="date_from"]')
    to = page.locator('input[name="date_to"]')
    if frm.count():
        frm.fill(min(selected_dates).isoformat())
    if to.count():
        to.fill(max(selected_dates).isoformat())

    session = page.locator('input[name="session_time"]')
    if session.count():
        session.fill("")

    apply_btn = page.get_by_role("button", name=re.compile(r"Apply", re.I))
    if apply_btn.count():
        apply_btn.click()
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        page.get_by_text("Event Term", exact=False).wait_for(state="visible", timeout=10000)
    log("✓ Preview filters applied.")


def wait_for_booking_page(page, log):
    try:
        page.get_by_text("Event Term", exact=False).wait_for(state="visible", timeout=10000)
        return True
    except PlaywrightTimeoutError:
        return False


def refresh_page(page, log):
    try:
        page.reload(wait_until="domcontentloaded", timeout=30000)
        if wait_for_booking_page(page, log):
            return True
    except Exception:
        pass
    return False


# ------------------------- priority sorting -------------------------

def rank_map(items):
    return {str(v): i for i, v in enumerate(items)}


def sort_for_selection(slots, time_priority, venue_priority):
    tr = rank_map(time_priority)
    vr = rank_map(venue_priority)

    def key(s):
        # PriorityList displays human-readable times, e.g.
        # "1:15 PM - 2:44 PM". Convert that label back to the
        # internal minute values when matching the scanned slot.
        display_time = f"{fmt_minute(s['start'])} - {fmt_minute(s['end'])}"
        return (
            s["date"],
            tr.get(display_time, 999),
            s["start"],
            vr.get(s["venue"], 999),
            s["venue"],
        )
    return sorted(slots, key=key)


def choose_slots(slots, selected_event, time_priority, venue_priority, per_date, require_bookable=False):
    """Choose slots using the user's current event/time/venue priorities.

    Preview/Test mode can select published sessions even when they are
    OPENING_SOON, so the user can see exactly what would be targeted.
    Actual booking mode uses require_bookable=True and therefore considers
    only sessions whose Book Now button is currently enabled.
    """
    selected_event = norm(selected_event)
    allowed_status = {"BOOKABLE"} if require_bookable else {
        "BOOKABLE", "OPENING_SOON", "UNKNOWN", "CLOSED", "WAITLIST"
    }

    candidates = [
        s for s in slots
        if norm(s.get("title")) == selected_event
        and s.get("status") in allowed_status
    ]

    # If the user removed every time/venue from the priority lists, there is
    # no meaningful selection to make.
    if not time_priority or not venue_priority:
        return []

    ordered = sort_for_selection(candidates, time_priority, venue_priority)

    result = []
    by_date = {}
    for s in ordered:
        d = s["date"]
        if len(by_date.get(d, [])) >= per_date:
            continue
        if any(overlap(s, x) for x in by_date.get(d, [])):
            continue
        by_date.setdefault(d, []).append(s)
        result.append(s)
    return result


# ------------------------- booking -------------------------

def book_slot(page, slot, purpose, log):
    if STOP_BOT:
        return False

    # Re-check the card immediately before clicking.
    button = slot["card"].get_by_role("button", name=re.compile(r"Book Now", re.I))
    if button.count() == 0:
        log("✗ Book Now button disappeared.")
        return False

    try:
        if button.first.is_disabled():
            log("✗ Slot is not currently bookable.")
            return False
    except Exception:
        return False

    try:
        inp = slot["card"].locator('input[name="purpose"]')
        if inp.count():
            inp.fill(purpose)

        log(f"Attempting: {slot['date']} | {fmt_session(slot)} | Venue {slot['venue']}")
        # Playwright's click already waits for the normal form navigation.
        # Avoid an additional load-state wait; go straight to the booking
        # success signal so the successful path is as short as possible.
        button.first.click()

        success = page.get_by_text(re.compile(r"Event session booked successfully", re.I))
        try:
            success.wait_for(state="visible", timeout=5000)
            log("✓✓✓ BOOKING SUCCESSFUL ✓✓✓")
            log(f"Booked: {slot['date']} | {fmt_session(slot)} | Venue {slot['venue']}")
            return True
        except PlaywrightTimeoutError:
            pass

        body = norm(page.locator("body").inner_text()).lower()
        if any(x in body for x in (
            "slot is filled", "not available", "booking closed", "already booked"
        )):
            log("✗ Slot is no longer available.")
            return False

        log("⚠ Booking result could not be confirmed.")
        return False
    except Exception as e:
        log(f"✗ Booking error: {e}")
        return False


# ------------------------- calendar -------------------------

class CalendarPicker(tk.Frame):
    def __init__(self, parent, on_change=None):
        super().__init__(parent)
        self.on_change = on_change
        today = date.today()
        self.year, self.month = today.year, today.month
        self.selected = set()

        head = ttk.Frame(self)
        head.pack(fill="x")
        ttk.Button(head, text="◀", width=3, command=self.prev_month).pack(side="left")
        self.month_label = ttk.Label(head, anchor="center")
        self.month_label.pack(side="left", fill="x", expand=True)
        ttk.Button(head, text="▶", width=3, command=self.next_month).pack(side="right")

        self.grid_frame = ttk.Frame(self)
        self.grid_frame.pack(pady=3)
        self.draw()

    def draw(self):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.month_label.config(text=f"{calendar.month_name[self.month]} {self.year}")
        for c, name in enumerate(("Mon","Tue","Wed","Thu","Fri","Sat","Sun")):
            ttk.Label(self.grid_frame, text=name, width=4, anchor="center").grid(row=0, column=c)
        today = date.today()
        for r, week in enumerate(calendar.monthcalendar(self.year, self.month), 1):
            for c, n in enumerate(week):
                if not n:
                    ttk.Label(self.grid_frame, text="", width=4).grid(row=r, column=c)
                    continue
                d = date(self.year, self.month, n)
                b = tk.Button(
                    self.grid_frame, text=str(n), width=3,
                    relief=tk.SUNKEN if d in self.selected else tk.RAISED,
                    command=lambda x=d: self.toggle(x)
                )
                if d < today:
                    b.config(state="disabled")
                b.grid(row=r, column=c, padx=1, pady=1)

    def toggle(self, d):
        if d < date.today():
            return
        if d in self.selected:
            self.selected.remove(d)
        else:
            self.selected.add(d)
        self.draw()
        if self.on_change:
            self.on_change(self.get_dates())

    def prev_month(self):
        if self.month == 1:
            self.month, self.year = 12, self.year - 1
        else:
            self.month -= 1
        self.draw()

    def next_month(self):
        if self.month == 12:
            self.month, self.year = 1, self.year + 1
        else:
            self.month += 1
        self.draw()

    def today(self):
        d = date.today()
        self.year, self.month = d.year, d.month
        self.draw()

    def clear(self):
        self.selected.clear()
        self.draw()
        if self.on_change:
            self.on_change([])

    def get_dates(self):
        return sorted(self.selected)


# ------------------------- dynamic GUI -------------------------

class PriorityList(ttk.Frame):
    def __init__(self, parent, title):
        super().__init__(parent)
        ttk.Label(self, text=title).pack(anchor="w")
        body = ttk.Frame(self)
        body.pack(fill="x", pady=2)
        self.listbox = tk.Listbox(body, height=4, exportselection=False)
        self.listbox.pack(side="left", fill="x", expand=True)
        buttons = ttk.Frame(body)
        buttons.pack(side="left", padx=(5, 0))
        ttk.Button(buttons, text="▲", width=3, command=self.up).pack()
        ttk.Button(buttons, text="▼", width=3, command=self.down).pack()
        ttk.Button(buttons, text="✕", width=3, command=self.remove).pack()
        self.items = []

    def set_items(self, items, preserve_order=False):
        new_items = list(dict.fromkeys(items))
        if preserve_order:
            kept = [x for x in self.items if x in new_items]
            additions = [x for x in new_items if x not in kept]
            self.items = kept + additions
        else:
            self.items = new_items
        self.refresh()

    def refresh(self):
        self.listbox.delete(0, "end")
        for x in self.items:
            self.listbox.insert("end", x)

    def up(self):
        sel = self.listbox.curselection()
        if not sel or sel[0] == 0:
            return
        i = sel[0]
        self.items[i-1], self.items[i] = self.items[i], self.items[i-1]
        self.refresh()
        self.listbox.selection_set(i-1)

    def down(self):
        sel = self.listbox.curselection()
        if not sel or sel[0] >= len(self.items)-1:
            return
        i = sel[0]
        self.items[i+1], self.items[i] = self.items[i], self.items[i+1]
        self.refresh()
        self.listbox.selection_set(i+1)

    def remove(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        del self.items[sel[0]]
        self.refresh()

    def get(self):
        return list(self.items)


class BookingBotGUI:
    def __init__(self, root):
        self.root = root

        # Landscape layout so all controls are visible without scrolling.
        root.title("Saveetha Booking Bot - Dynamic Preview")
        root.geometry("1100x760")
        root.resizable(False, False)

        self.preview_slots = []
        self.browser = None
        self.context = None
        self.page = None
        self.playwright = None

        # ========================================================
        # MAIN LANDSCAPE GRID
        # ========================================================
        outer = ttk.Frame(root, padding=10)
        outer.pack(fill="both", expand=True)

        outer.columnconfigure(0, weight=0, minsize=400)
        outer.columnconfigure(1, weight=1, minsize=660)
        outer.rowconfigure(1, weight=1)
        outer.rowconfigure(2, weight=0)

        # ========================================================
        # LEFT: DATE SELECTION
        # ========================================================
        date_frame = ttk.LabelFrame(
            outer,
            text="1. Select Booking Dates",
            padding=8
        )
        date_frame.grid(
            row=0,
            column=0,
            rowspan=2,
            sticky="nsew",
            padx=(0, 8)
        )

        self.cal = CalendarPicker(
            date_frame,
            self.update_dates
        )
        self.cal.pack(
            anchor="center",
            pady=(5, 8)
        )

        date_buttons = ttk.Frame(date_frame)
        date_buttons.pack(fill="x", pady=(0, 5))

        ttk.Button(
            date_buttons,
            text="TODAY",
            command=self.cal.today
        ).pack(side="left", expand=True, fill="x")

        ttk.Button(
            date_buttons,
            text="CLEAR",
            command=self.cal.clear
        ).pack(side="left", expand=True, fill="x", padx=5)

        ttk.Label(
            date_frame,
            text="Selected Dates:"
        ).pack(anchor="w", pady=(5, 2))

        self.date_var = tk.StringVar(
            value="No dates selected"
        )

        ttk.Label(
            date_frame,
            textvariable=self.date_var,
            wraplength=370,
            justify="left"
        ).pack(
            anchor="w",
            fill="x"
        )

        ttk.Button(
            date_frame,
            text="SCAN PREVIEW",
            command=self.scan_preview
        ).pack(
            fill="x",
            pady=(15, 5)
        )

        ttk.Label(
            date_frame,
            text="Preview scan is read-only.\n"
                 "It detects the currently published events, "
                 "times, venues and booking status.",
            wraplength=370,
            justify="left"
        ).pack(
            anchor="w",
            pady=(5, 0)
        )

        # ========================================================
        # RIGHT: CONFIGURATION
        # ========================================================
        config = ttk.LabelFrame(
            outer,
            text="2. Configure Booking",
            padding=8
        )
        config.grid(
            row=0,
            column=1,
            sticky="nsew"
        )

        config.columnconfigure(1, weight=1)
        config.rowconfigure(3, weight=1)
        config.rowconfigure(4, weight=1)

        # Event + slots
        ttk.Label(
            config,
            text="Event:"
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 5),
            pady=2
        )

        self.event_var = tk.StringVar()
        self._priority_event = ""

        self.event_box = ttk.Combobox(
            config,
            textvariable=self.event_var,
            state="readonly",
            width=45
        )

        self.event_box.grid(
            row=0,
            column=1,
            sticky="ew",
            pady=2
        )
        self.event_box.bind("<<ComboboxSelected>>", self.event_changed)

        ttk.Label(
            config,
            text="Slots/date:"
        ).grid(
            row=1,
            column=0,
            sticky="w",
            padx=(0, 5),
            pady=2
        )

        self.slots_var = tk.IntVar(value=1)

        ttk.Spinbox(
            config,
            from_=1,
            to=10,
            textvariable=self.slots_var,
            width=8
        ).grid(
            row=1,
            column=1,
            sticky="w",
            pady=2
        )

        # Time priority
        self.time_priority = PriorityList(
            config,
            "Time Priority (highest → lowest)"
        )

        self.time_priority.grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(8, 4)
        )

        # Venue priority
        self.venue_priority = PriorityList(
            config,
            "Venue Priority (highest → lowest)"
        )

        self.venue_priority.grid(
            row=3,
            column=0,
            columnspan=2,
            sticky="nsew",
            pady=4
        )

        # Purpose
        purpose_frame = ttk.Frame(config)
        purpose_frame.grid(
            row=4,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(5, 2)
        )
        purpose_frame.columnconfigure(1, weight=1)

        ttk.Label(
            purpose_frame,
            text="Purpose:"
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 5)
        )

        self.purpose_var = tk.StringVar(
            value=DEFAULT_PURPOSE
        )

        ttk.Entry(
            purpose_frame,
            textvariable=self.purpose_var
        ).grid(
            row=0,
            column=1,
            sticky="ew"
        )

        # Options
        opt = ttk.Frame(config)
        opt.grid(
            row=5,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(7, 3)
        )

        self.monitor_var = tk.BooleanVar(value=True)

        ttk.Checkbutton(
            opt,
            text="Refresh/retry until available",
            variable=self.monitor_var
        ).pack(
            side="left"
        )

        ttk.Label(
            opt,
            text="Retry:"
        ).pack(
            side="left",
            padx=(15, 3)
        )

        self.retry_var = tk.IntVar(
            value=DEFAULT_RETRY_SECONDS
        )

        ttk.Spinbox(
            opt,
            from_=2,
            to=60,
            textvariable=self.retry_var,
            width=5
        ).pack(
            side="left"
        )

        self.dry_var = tk.BooleanVar(value=True)

        ttk.Checkbutton(
            opt,
            text="TEST mode",
            variable=self.dry_var
        ).pack(
            side="left",
            padx=15
        )

        # Action buttons
        buttons = ttk.Frame(config)
        buttons.grid(
            row=6,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(5, 0)
        )

        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)

        self.test_btn = ttk.Button(
            buttons,
            text="TEST SELECTION",
            command=self.test_selection
        )

        self.test_btn.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=(0, 4)
        )

        self.start_btn = ttk.Button(
            buttons,
            text="START BOOKING",
            command=self.start_booking,
            state="disabled"
        )

        self.start_btn.grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(4, 0)
        )

        ttk.Button(
            config,
            text="STOP BOT",
            command=self.stop
        ).grid(
            row=7,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(6, 0)
        )

        # ========================================================
        # BOTTOM: LIVE LOG
        # ========================================================
        log_frame = ttk.LabelFrame(
            outer,
            text="Live Log",
            padding=5
        )

        log_frame.grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="nsew",
            pady=(8, 0)
        )

        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_box = tk.Text(
            log_frame,
            height=8,
            wrap="word"
        )

        self.log_box.grid(
            row=0,
            column=0,
            sticky="nsew"
        )

        log_scroll = ttk.Scrollbar(
            log_frame,
            orient="vertical",
            command=self.log_box.yview
        )

        log_scroll.grid(
            row=0,
            column=1,
            sticky="ns"
        )

        self.log_box.configure(
            yscrollcommand=log_scroll.set
        )

    def log(self, msg):
        self.root.after(0, lambda: (self.log_box.insert("end", msg + "\n"), self.log_box.see("end")))

    def update_dates(self, dates):
        self.date_var.set(", ".join(d.strftime("%d/%m/%Y") for d in dates) if dates else "No dates selected")

    def scan_preview(self):
        dates = self.cal.get_dates()
        if not dates:
            messagebox.showerror("Preview", "Select at least one date first.")
            return
        self.log_box.delete("1.0", "end")
        self.log("PREVIEW SCAN — read-only; no booking will be performed.")
        self.log("Dates: " + ", ".join(d.strftime("%d/%m/%Y") for d in dates))
        threading.Thread(target=self._scan_thread, args=(dates,), daemon=True).start()

    def _scan_thread(self, dates):
        global STOP_BOT
        STOP_BOT = False
        try:
            load_dotenv()
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(headless=False)
            self.context = self.browser.new_context()
            self.page = self.context.new_page()

            login(self.page, self.log, os.getenv("SAVEETHA_USERNAME"), os.getenv("SAVEETHA_PASSWORD"))
            if STOP_BOT:
                return
            open_bookings(self.page, self.log)
            apply_preview_filter(self.page, dates, self.log)
            slots = scan_cards(self.page, dates, self.log)
            self.preview_slots = slots

            events = sorted({s["title"] for s in slots})
            # Show real clock times in the UI instead of internal minute values.
            times = sorted(
                {f"{fmt_minute(s['start'])} - {fmt_minute(s['end'])}" for s in slots},
                key=lambda x: parse_session(x)
            )
            venues = sorted({s["venue"] for s in slots if s["venue"]})

            self.root.after(0, lambda: self.populate_config(events, times, venues))
            self.log("Preview complete. Configure Event / Time / Venue, then TEST SELECTION.")
        except Exception as e:
            self.log(f"PREVIEW ERROR: {e}")
            self.cleanup_browser()
        # Keep browser/page alive after preview so test selection can inspect the same cards.

    def populate_config(self, events, times, venues):
        self.event_box["values"] = list(events)

        if events:
            self.event_var.set(events[0])
            self._priority_event = ""
            self.update_event_dependent_lists()
        else:
            self.event_var.set("")
            self.time_priority.set_items([])
            self.venue_priority.set_items([])

        self.start_btn.config(state="disabled")
        self.test_btn.config(state="normal")

    def event_changed(self, event=None):
        """Rebuild time/venue choices whenever the selected event changes."""
        self.update_event_dependent_lists()

    def update_event_dependent_lists(self):
        selected_event = norm(self.event_var.get())

        if not selected_event or not self.preview_slots:
            self.time_priority.set_items([])
            self.venue_priority.set_items([])
            return

        event_slots = [
            s for s in self.preview_slots
            if norm(s.get("title")) == selected_event
        ]

        time_map = {}
        for s in event_slots:
            label = f"{fmt_minute(s['start'])} - {fmt_minute(s['end'])}"
            time_map[label] = s["start"]

        times = [
            label for label, _ in sorted(
                time_map.items(), key=lambda item: item[1]
            )
        ]

        venues = sorted({s["venue"] for s in event_slots if s.get("venue")})

        same_event = self._priority_event == selected_event
        self.time_priority.set_items(times, preserve_order=same_event)
        self.venue_priority.set_items(venues, preserve_order=same_event)
        self._priority_event = selected_event

        self.log(f"Configuration filtered for: {selected_event}")
        self.log(f"  Times detected: {len(times)}")
        self.log(f"  Venues detected: {len(venues)}")

    def selected_time_keys(self):
        return self.time_priority.get()

    def test_selection(self):
        if not self.preview_slots:
            messagebox.showerror("Test", "Run SCAN PREVIEW first.")
            return

        event = norm(self.event_var.get())
        if not event:
            messagebox.showerror("Test", "Select one event.")
            return

        try:
            per_date = max(1, int(self.slots_var.get()))
        except Exception:
            messagebox.showerror("Test", "Invalid slots/date.")
            return

        purpose = self.purpose_var.get().strip()
        if not purpose:
            messagebox.showerror("Test", "Enter a purpose.")
            return

        time_priority = self.time_priority.get()
        venue_priority = self.venue_priority.get()

        if not time_priority:
            messagebox.showerror("Test", "Keep at least one time in Time Priority.")
            return
        if not venue_priority:
            messagebox.showerror("Test", "Keep at least one venue in Venue Priority.")
            return

        # Test mode intentionally allows OPENING_SOON/CLOSED/WAITLIST so the
        # user can inspect what the configured priorities would select.
        chosen = choose_slots(
            self.preview_slots,
            event,
            time_priority,
            venue_priority,
            per_date,
            require_bookable=False,
        )

        self.log("========================================")
        self.log("TEST SELECTION — NO BOOKING PERFORMED.")
        self.log(f"Event: {event}")
        self.log(f"Slots/date: {per_date}")
        self.log("Time priority: " + " > ".join(time_priority))
        self.log("Venue priority: " + " > ".join(venue_priority))

        if not chosen:
            self.log("No matching published sessions for the CURRENT configuration.")
            messagebox.showwarning(
                "Test Selection",
                "No published slots match the CURRENT event/time/venue configuration."
            )
            self.start_btn.config(state="disabled")
            return

        lines = []
        for s in chosen:
            line = (
                f"{s['date'].strftime('%d/%m/%Y')} | {s['title']} | "
                f"{fmt_session(s)} | {s['duration']} min | "
                f"Venue {s['venue']} | {s['status']}"
            )
            lines.append(line)
            self.log("  " + line)

        self.log("========================================")
        self.log(f"Test selected {len(chosen)} session(s).")

        messagebox.showinfo(
            "Test Selection",
            "Selected slots:\n\n" + "\n".join(lines) +
            "\n\nNo booking was performed."
        )
        self.start_btn.config(state="normal")

    def start_booking(self):
        if not self.preview_slots:
            messagebox.showerror("Booking", "Run SCAN PREVIEW first.")
            return
        if not messagebox.askyesno("Confirm Booking", "Start actual booking attempts now?\n\nThe bot will only click enabled Book Now buttons matching your TEST SELECTION."):
            return

        dates = self.cal.get_dates()
        event = self.event_var.get().strip()
        per_date = max(1, int(self.slots_var.get()))
        times = self.time_priority.get()
        venues = self.venue_priority.get()
        purpose = self.purpose_var.get().strip()
        monitor = self.monitor_var.get()
        retry = max(2, int(self.retry_var.get()))

        self.start_btn.config(state="disabled")
        self.test_btn.config(state="disabled")
        threading.Thread(
            target=self._booking_thread,
            args=(dates, event, per_date, times, venues, purpose, monitor, retry),
            daemon=True
        ).start()

    def _booking_thread(self, dates, event, per_date, times, venues, purpose, monitor, retry):
        global STOP_BOT
        STOP_BOT = False

        # IMPORTANT: Playwright sync objects are thread-affine.  The preview
        # runs in _scan_thread, so its page/browser cannot be reused here.
        # Create a fresh Playwright/browser/page inside THIS booking thread.
        booking_playwright = None
        booking_browser = None
        booking_context = None
        booking_page = None

        try:
            load_dotenv()
            booking_playwright = sync_playwright().start()
            booking_browser = booking_playwright.chromium.launch(headless=False)
            booking_context = booking_browser.new_context()
            booking_page = booking_context.new_page()

            # From this point on, all Playwright work in this thread uses
            # the page created by this same thread.
            self.page = booking_page

            login(self.page, self.log, os.getenv("SAVEETHA_USERNAME"), os.getenv("SAVEETHA_PASSWORD"))
            if STOP_BOT:
                return
            open_bookings(self.page, self.log)

            booked = {d: 0 for d in dates}
            used = {d: [] for d in dates}
            attempted = set()

            while not STOP_BOT:
                # Refresh the published page before every new scan.
                if not wait_for_booking_page(self.page, self.log):
                    if not refresh_page(self.page, self.log):
                        self.log("⚠ Booking page unavailable; retrying after interval.")
                        if not monitor:
                            break
                        time.sleep(retry)
                        continue

                apply_preview_filter(self.page, dates, self.log)
                slots = scan_cards(self.page, dates, self.log)
                self.preview_slots = slots

                chosen = choose_slots(
                    slots, event, times, venues, per_date, require_bookable=True
                )
                progress = False

                for s in chosen:
                    if STOP_BOT:
                        break
                    d = s["date"]
                    if booked[d] >= per_date:
                        continue

                    k = slot_key(s)
                    if k in attempted:
                        continue
                    if any(overlap(s, u) for u in used[d]):
                        continue

                    if book_slot(self.page, s, purpose, self.log):
                        attempted.add(k)
                        booked[d] += 1
                        used[d].append(s)
                        progress = True
                        self.log(f"✓ {d}: {booked[d]}/{per_date} booked")

                        # Refresh after success so the next attempt sees current state.
                        refresh_page(self.page, self.log)
                    else:
                        # Do not permanently blacklist a slot after a race or
                        # transient page state. It may become bookable later.
                        self.log("  Slot not booked; it remains eligible on a future scan.")

                if all(booked[d] >= per_date for d in dates):
                    self.log("ALL REQUIRED BOOKINGS COMPLETED.")
                    break

                if not monitor:
                    self.log("Retry monitor OFF. Stopping after current scan.")
                    break

                if not progress:
                    self.log(f"No matching available slot yet. Refreshing in {retry} seconds...")
                    end = time.time() + retry
                    while time.time() < end and not STOP_BOT:
                        time.sleep(0.2)

                if STOP_BOT:
                    break

            if STOP_BOT:
                self.log("BOT STOPPED.")
        except Exception as e:
            self.log(f"BOOKING ERROR: {e}")
        finally:
            # Close only objects created by this booking thread.
            try:
                if booking_browser:
                    booking_browser.close()
            except Exception:
                pass
            try:
                if booking_playwright:
                    booking_playwright.stop()
            except Exception:
                pass

            self.root.after(0, lambda: self.test_btn.config(state="normal"))
            self.root.after(0, lambda: self.start_btn.config(state="normal"))

    def stop(self):
        global STOP_BOT
        STOP_BOT = True
        self.log("!!! STOP REQUESTED !!!")

    def cleanup_browser(self):
        # Only used on unrecoverable preview errors.
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


if __name__ == "__main__":
    load_dotenv()
    root = tk.Tk()
    BookingBotGUI(root)
    root.mainloop()
