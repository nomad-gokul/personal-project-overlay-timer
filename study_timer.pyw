"""
Study Timer - a tiny always-on-top, see-through stopwatch for your desktop.

Controls
  Double-click digits  -> start / pause  (pausing starts a break, resuming ends it)
  Drag digits          -> move it anywhere (position is remembered)
  Right-click digits   -> menu: today's totals, reset, open CSV log, snap to corner,
                          opacity, size, last 7 days, exit

Every study block and every break is appended to  ~/study_log.csv :
  date, start_time, end_time, type (study/break), duration_minutes

Save this file as  study_timer.pyw  and double-click it (no console window).
"""
import csv
import ctypes
import datetime
import json
import os
import subprocess
import sys
import time
import tkinter as tk
import tkinter.font as tkfont

HOME = os.path.expanduser("~")
DATA_FILE = os.path.join(HOME, ".study_timer.json")   # settings + daily totals
CSV_FILE = os.path.join(HOME, "study_log.csv")        # one row per study block / break
CSV_HEADER = ["date", "start_time", "end_time", "type", "duration_minutes"]
MIN_SEGMENT = 5            # seconds; ignore accidental double-double-clicks
SAVE_EVERY = 30            # seconds between autosaves

KEY = "#010101"            # this colour is made fully transparent
OUTLINE = "#141414"        # dark outline so digits stay readable on white pages
RUN_COLOR = "#FFFFFF"
PAUSE_COLOR = "#FFB547"
MARGIN = 14

IS_WIN = sys.platform.startswith("win")
if IS_WIN:
    try:  # crisp text on high-DPI laptop screens
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def fmt(seconds):
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def hm(seconds):
    s = int(seconds)
    return f"{s // 3600}h {s % 3600 // 60:02d}m"


def now_wall():
    return datetime.datetime.now().replace(microsecond=0)


class StudyTimer:
    def __init__(self):
        self.data = self._load()
        self.data.setdefault("log", {})        # date -> study seconds
        self.data.setdefault("breaks", {})     # date -> break seconds
        self.data.setdefault("csv_queue", [])  # rows waiting to be written (e.g. CSV open in Excel)

        # timer state
        self.running = False
        self.session = 0.0          # seconds in this session (shown)
        self.tick_ref = None        # monotonic time of last tick
        self.unlogged = 0.0         # study seconds not yet added to today's total
        self.seg = None             # current block: {"type", "start", "mono"}
        self._last_save = time.monotonic()

        # If the laptop shut down / crashed mid-study, log that block up to the last autosave.
        pending = self.data.pop("pending", None)
        if pending and pending.get("type") == "study":
            self._record("study", pending["start"], pending["end"], pending["dur"])
        self._write_csv()

        self.root = r = tk.Tk()
        r.title("Study Timer")
        r.overrideredirect(True)                 # no title bar / borders
        r.attributes("-topmost", True)           # stays above every window
        try:
            r.attributes("-transparentcolor", KEY)   # Windows: see-through background
        except tk.TclError:
            pass
        r.attributes("-alpha", self.data.get("opacity", 0.9))
        r.configure(bg=KEY)

        self.font = tkfont.Font(family="Segoe UI Semibold" if IS_WIN else "DejaVu Sans",
                                size=self.data.get("size", 20))
        self.canvas = tk.Canvas(r, bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack()
        self._resize_canvas()

        for seq, fn in (("<ButtonPress-1>", self._press), ("<B1-Motion>", self._drag),
                        ("<ButtonRelease-1>", self._release), ("<Double-Button-1>", self.toggle),
                        ("<Button-3>", self._menu)):
            self.canvas.bind(seq, fn)

        self._build_menu()
        r.update_idletasks()
        pos = self.data.get("pos")
        if pos:
            r.geometry(f"+{pos[0]}+{pos[1]}")
        else:
            self.snap("tr")
        r.protocol("WM_DELETE_WINDOW", self.quit)
        self._draw()
        self._loop()

    # ---------- persistence ----------
    def _load(self):
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self):
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=1)
        except Exception:
            pass

    def _flush(self):
        """Add accumulated study seconds to today's total."""
        if self.unlogged > 0:
            today = datetime.date.today().isoformat()
            self.data["log"][today] = self.data["log"].get(today, 0) + self.unlogged
            self.unlogged = 0.0
            self._save()

    def today_study(self):
        return self.data["log"].get(datetime.date.today().isoformat(), 0) + self.unlogged

    def today_breaks(self):
        return self.data["breaks"].get(datetime.date.today().isoformat(), 0)

    # ---------- study blocks / breaks -> CSV ----------
    def _begin(self, kind):
        self.seg = {"type": kind, "start": now_wall().isoformat(), "mono": time.monotonic()}
        self._checkpoint()

    def _seg_duration(self):
        return time.monotonic() - self.seg["mono"] if self.seg else 0.0

    def _checkpoint(self):
        """Remember the open block so it survives a crash or shutdown."""
        if self.seg:
            self.data["pending"] = {"type": self.seg["type"], "start": self.seg["start"],
                                    "end": now_wall().isoformat(), "dur": self._seg_duration()}
        else:
            self.data.pop("pending", None)
        self._save()

    def _end(self, record=True):
        """Close the open block; write it to the CSV if record=True."""
        if not self.seg:
            return
        if record:
            self._record(self.seg["type"], self.seg["start"], now_wall().isoformat(),
                         self._seg_duration())
        self.seg = None
        self.data.pop("pending", None)
        self._save()

    def _record(self, kind, start_iso, end_iso, seconds):
        if seconds < MIN_SEGMENT:
            return
        start = datetime.datetime.fromisoformat(start_iso)
        end = datetime.datetime.fromisoformat(end_iso)
        day = start.date().isoformat()
        if kind == "break":
            self.data["breaks"][day] = self.data["breaks"].get(day, 0) + seconds
        self.data["csv_queue"].append([day, start.strftime("%H:%M:%S"), end.strftime("%H:%M:%S"),
                                       kind, f"{seconds / 60:.2f}"])
        self._write_csv()

    def _write_csv(self):
        if not self.data["csv_queue"]:
            return
        try:
            new_file = not os.path.exists(CSV_FILE) or os.path.getsize(CSV_FILE) == 0
            with open(CSV_FILE, "a", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                if new_file:
                    w.writerow(CSV_HEADER)
                w.writerows(self.data["csv_queue"])
            self.data["csv_queue"] = []
        except OSError:
            pass  # e.g. the CSV is open in Excel; rows stay queued and are retried later
        self._save()

    # ---------- timer ----------
    def _loop(self):
        now = time.monotonic()
        if self.running:
            dt = now - self.tick_ref
            self.tick_ref = now
            self.session += dt
            self.unlogged += dt
        if now - self._last_save >= SAVE_EVERY:
            self._last_save = now
            self._flush()
            self._checkpoint()
            self._write_csv()
        self._draw()
        self.root.after(250, self._loop)

    def toggle(self, _=None):
        self.running = not self.running
        if self.running:                 # resume: the break (if any) ends, study begins
            self.tick_ref = time.monotonic()
            self._end()
            self._begin("study")
        else:                            # pause: study block ends, a break begins
            self._flush()
            self._end()
            self._begin("break")
        self._draw()

    def _stop(self):
        """Finish for now: log a running study block, drop an unfinished break."""
        self._flush()
        if self.seg and self.seg["type"] == "study":
            self._end()
        else:
            self._end(record=False)     # a pause you never came back from isn't a break
        self.running = False

    def reset(self):
        self._stop()
        self.session = 0.0
        self._draw()

    def _draw(self):
        c = self.canvas
        c.delete("all")
        text = fmt(self.session)
        for dx in (-2, -1, 0, 1, 2):            # outline pass
            for dy in (-2, -1, 0, 1, 2):
                if dx or dy:
                    c.create_text(self.cx + dx, self.cy + dy, text=text, font=self.font, fill=OUTLINE)
        c.create_text(self.cx, self.cy, text=text, font=self.font,
                      fill=RUN_COLOR if self.running else PAUSE_COLOR)

    # ---------- placement ----------
    def _work_area(self):
        if IS_WIN:
            try:
                class RECT(ctypes.Structure):
                    _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                                ("r", ctypes.c_long), ("b", ctypes.c_long)]
                rc = RECT()
                ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rc), 0)
                return rc.l, rc.t, rc.r, rc.b      # screen minus taskbar
            except Exception:
                pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight() - 48

    def snap(self, corner):
        self.root.update_idletasks()
        l, t, r, b = self._work_area()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        x = l + MARGIN if "l" in corner else r - w - MARGIN
        y = t + MARGIN if "t" in corner else b - h - MARGIN
        self.root.geometry(f"+{x}+{y}")
        self.data["pos"] = [x, y]
        self._save()

    def _press(self, e):
        self._off = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag(self, e):
        self.root.geometry(f"+{e.x_root - self._off[0]}+{e.y_root - self._off[1]}")

    def _release(self, _):
        self.data["pos"] = [self.root.winfo_x(), self.root.winfo_y()]
        self._save()

    # ---------- menu ----------
    def _build_menu(self):
        m = self.menu = tk.Menu(self.root, tearoff=0, postcommand=self._refresh_menu)
        m.add_command(label="Today", state="disabled")
        m.add_separator()
        m.add_command(label="Start / Pause   (double-click)", command=self.toggle)
        m.add_command(label="Reset session", command=self.reset)
        m.add_command(label="Open study log (CSV)", command=self.open_log)
        m.add_command(label="Last 7 days", command=self.show_week)
        m.add_separator()
        corners = tk.Menu(m, tearoff=0)
        for label, code in (("Top-right", "tr"), ("Top-left", "tl"),
                            ("Bottom-right", "br"), ("Bottom-left", "bl")):
            corners.add_command(label=label, command=lambda c=code: self.snap(c))
        m.add_cascade(label="Snap to corner", menu=corners)
        op = tk.Menu(m, tearoff=0)
        for pct in (100, 85, 70, 50, 35):
            op.add_command(label=f"{pct}%", command=lambda p=pct: self.set_opacity(p / 100))
        m.add_cascade(label="Opacity", menu=op)
        sz = tk.Menu(m, tearoff=0)
        for label, s in (("Small", 14), ("Medium", 20), ("Large", 28)):
            sz.add_command(label=label, command=lambda s=s: self.set_size(s))
        m.add_cascade(label="Size", menu=sz)
        m.add_separator()
        m.add_command(label="Exit", command=self.quit)

    def _refresh_menu(self):
        self.menu.entryconfigure(
            0, label=f"Today: {hm(self.today_study())} studied · {hm(self.today_breaks())} breaks")

    def _menu(self, e):
        self.menu.tk_popup(e.x_root, e.y_root)

    def open_log(self):
        self._write_csv()
        if not os.path.exists(CSV_FILE):
            with open(CSV_FILE, "w", encoding="utf-8", newline="") as f:
                csv.writer(f).writerow(CSV_HEADER)
        try:
            if IS_WIN:
                os.startfile(CSV_FILE)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", CSV_FILE])
            else:
                subprocess.Popen(["xdg-open", CSV_FILE])
        except Exception:
            pass

    def set_opacity(self, a):
        self.root.attributes("-alpha", a)
        self.data["opacity"] = a
        self._save()

    def _resize_canvas(self):
        w = self.font.measure("00:00:00") + 10
        h = self.font.metrics("linespace") + 6
        self.canvas.configure(width=w, height=h)
        self.cx, self.cy = w // 2, h // 2

    def set_size(self, s):
        self.data["size"] = s
        self.font.configure(size=s)
        self._resize_canvas()
        self._draw()
        self._save()

    def show_week(self):
        self._flush()
        top = tk.Toplevel(self.root)
        top.title("Study time - last 7 days")
        top.attributes("-topmost", True)
        today = datetime.date.today()
        tot_s = tot_b = 0
        tk.Label(top, font=("Consolas", 11, "bold"), anchor="w",
                 text="Day           Study    Break").pack(fill="x", padx=12, pady=(10, 0))
        for i in range(6, -1, -1):
            d = (today - datetime.timedelta(days=i)).isoformat()
            s = int(self.data["log"].get(d, 0))
            b = int(self.data["breaks"].get(d, 0))
            tot_s += s
            tot_b += b
            bar = "█" * min(40, s // 900)          # one block = 15 min of study
            label = datetime.date.fromisoformat(d).strftime("%a %d %b")
            tk.Label(top, font=("Consolas", 11), anchor="w",
                     text=f"{label}  {hm(s):>7}  {hm(b):>7}  {bar}").pack(fill="x", padx=12)
        tk.Label(top, font=("Consolas", 11, "bold"), anchor="w",
                 text=f"\nTotal: {hm(tot_s)} studied, {hm(tot_b)} on breaks"
                 ).pack(fill="x", padx=12, pady=(0, 10))

    def quit(self):
        self._stop()
        self._write_csv()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    StudyTimer().run()
