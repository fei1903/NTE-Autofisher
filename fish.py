import sys, ctypes, os

def _require_admin():
    if ctypes.windll.shell32.IsUserAnAdmin():
        return  # already admin
    # Re-launch self as admin
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, " ".join(f'"{a}"' for a in sys.argv), None, 1
    )
    sys.exit()

_require_admin()

import cv2
import numpy as np
import mss
import time
import win32gui
import win32con
import win32api
import win32process
import psutil
import ctypes
import threading
import tkinter as tk
import tkinter.ttk as ttk
import queue
import sys
import traceback
from datetime import timedelta

# ── DPI Awareness ─────────────────────────────────────────────────────────────
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════════════════════
#  PALETTE
# ══════════════════════════════════════════════════════════════════════════════
BG       = "#0b0f0b"
BG2      = "#111711"
BG3      = "#182118"
ACCENT   = "#39ff6a"
ACCENT2  = "#1aff4a"
DIM      = "#2a3d2a"
TEXT     = "#c8e6c8"
TEXT_DIM = "#5a7a5a"
RED      = "#ff4444"
YELLOW   = "#ffd740"
BORDER   = "#1e2e1e"
FONT_MONO = ("Consolas", 9)
FONT_STAT = ("Consolas", 13, "bold")

# ══════════════════════════════════════════════════════════════════════════════
#  THREAD COMMUNICATION
# ══════════════════════════════════════════════════════════════════════════════
log_queue   = queue.Queue()
state_queue = queue.Queue()
stop_event  = threading.Event()

def _log(msg: str):
    log_queue.put(f"[{time.strftime('%H:%M:%S')}] {msg}")

def _log_err(msg: str):
    log_queue.put(f"[{time.strftime('%H:%M:%S')}] ERR {msg}")

# ══════════════════════════════════════════════════════════════════════════════
#  WIN32 HELPERS
# ══════════════════════════════════════════════════════════════════════════════
VK_CODE = {'a': 0x41, 'd': 0x44, 'f': 0x46}
_cached_hwnd = None

def get_hwnd_by_process_name(process_name: str):
    global _cached_hwnd
    if _cached_hwnd and win32gui.IsWindow(_cached_hwnd):
        return _cached_hwnd
    target_pid = None
    for proc in psutil.process_iter(['name', 'pid']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == process_name.lower():
                target_pid = proc.info['pid']
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if not target_pid:
        return None
    found = []
    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid == target_pid:
                    r = win32gui.GetClientRect(hwnd)
                    if r[2] > 0 and r[3] > 0:
                        found.append(hwnd)
            except Exception:
                pass
        return True
    win32gui.EnumWindows(_cb, None)
    if found:
        _cached_hwnd = found[0]
        return _cached_hwnd
    return None

def get_window_bbox(process_name: str):
    hwnd = get_hwnd_by_process_name(process_name)
    if not hwnd:
        return None
    try:
        rect  = win32gui.GetClientRect(hwnd)
        point = win32gui.ClientToScreen(hwnd, (0, 0))
        return {"left": point[0], "top": point[1], "width": rect[2], "height": rect[3]}
    except Exception:
        global _cached_hwnd
        _cached_hwnd = None
        return None

def _post(hwnd, msg, wp, lp):
    try:
        win32api.PostMessage(hwnd, msg, wp, lp)
    except Exception:
        pass

def simulate_keydown(key: str, process_name: str):
    hwnd = get_hwnd_by_process_name(process_name)
    if hwnd:
        _post(hwnd, win32con.WM_KEYDOWN, VK_CODE.get(key, 0), 0)

def simulate_keyup(key: str, process_name: str):
    hwnd = get_hwnd_by_process_name(process_name)
    if hwnd:
        _post(hwnd, win32con.WM_KEYUP, VK_CODE.get(key, 0), 0)

def force_release_all_keys(cfg: dict):
    pn = cfg.get('process', '')
    simulate_keyup(cfg.get('key_left',  'a'), pn)
    simulate_keyup(cfg.get('key_right', 'd'), pn)
    hwnd = get_hwnd_by_process_name(pn)
    if hwnd:
        _post(hwnd, win32con.WM_KEYUP,     VK_CODE.get('f', 0), 0)
        _post(hwnd, win32con.WM_LBUTTONUP, 0, 0)

def get_windowed_processes() -> list[str]:
    """Return sorted list of unique .exe names that own at least one visible window."""
    windowed_pids = set()
    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                windowed_pids.add(pid)
            except Exception:
                pass
        return True
    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        pass
    names = set()
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['pid'] in windowed_pids and proc.info['name']:
                names.add(proc.info['name'])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return sorted(names, key=str.lower)



    if not hwnd:
        return
    _post(hwnd, win32con.WM_ACTIVATE,  win32con.WA_INACTIVE, 0)
    _post(hwnd, win32con.WM_KILLFOCUS, 0, 0)
    time.sleep(0.1)
    _post(hwnd, win32con.WM_ACTIVATE,  win32con.WA_ACTIVE, 0)
    _post(hwnd, win32con.WM_SETFOCUS,  0, 0)

# ══════════════════════════════════════════════════════════════════════════════
#  CV HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def refresh_window_focus(hwnd):
    if not hwnd:
        return
    _post(hwnd, win32con.WM_ACTIVATE,  win32con.WA_INACTIVE, 0)
    _post(hwnd, win32con.WM_KILLFOCUS, 0, 0)
    time.sleep(0.1)
    _post(hwnd, win32con.WM_ACTIVATE,  win32con.WA_ACTIVE, 0)
    _post(hwnd, win32con.WM_SETFOCUS,  0, 0)


def find_yellow_center(mask):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    if cv2.contourArea(c) <= 5:
        return None
    M = cv2.moments(c)
    if M["m00"] == 0:
        return None
    return int(M["m10"] / M["m00"])

def find_green_bounds(mask):
    xs = np.where(mask > 0)[1]
    if len(xs) == 0:
        return None, None
    return int(xs.min()), int(xs.max())

# ══════════════════════════════════════════════════════════════════════════════
#  MACRO CORE
# ══════════════════════════════════════════════════════════════════════════════
def auto_fishing(cfg: dict, stop_ev: threading.Event, catches_ref: list, restarts_ref: list):
    global _cached_hwnd
    _cached_hwnd = None

    PROC          = cfg['process']
    SLIDER_ROI    = cfg['slider_roi']
    GREEN_LOWER   = cfg['green_lower']
    GREEN_UPPER   = cfg['green_upper']
    YELLOW_LOWER  = cfg['yellow_lower']
    YELLOW_UPPER  = cfg['yellow_upper']
    KEY_LEFT      = cfg['key_left']
    KEY_RIGHT     = cfg['key_right']
    CENTER_TOL    = cfg['center_tol']
    PREDICT_TIME  = cfg['predict_time']
    MORPH_K       = cfg['morph_kernel']
    GREEN_MIN_A   = cfg['green_min_area']
    STATE_TIMEOUT = cfg['state_timeout']
    IDLE_TIMEOUT  = cfg['idle_timeout']
    SHOW_DEBUG    = cfg['show_debug']

    _log("Waiting for game window...")
    state_queue.put(("SEARCHING", catches_ref[0], restarts_ref[0], []))

    while get_window_bbox(PROC) is None:
        if stop_ev.is_set():
            return
        time.sleep(1)

    _log(f"Found {PROC}")
    hwnd = get_hwnd_by_process_name(PROC)
    if hwnd:
        refresh_window_focus(hwnd)

    spammer_active = [True]

    def _spammer():
        while spammer_active[0] and not stop_ev.is_set():
            try:
                h = get_hwnd_by_process_name(PROC)
                if not h:
                    time.sleep(0.5)
                    continue
                r = win32gui.GetClientRect(h)
                if r[2] <= 0 or r[3] <= 0:
                    time.sleep(0.4)
                    continue
                lp = win32api.MAKELONG(r[2] // 2, r[3] // 2)
                _post(h, win32con.WM_KEYDOWN,    VK_CODE['f'],          0)
                time.sleep(0.1)
                _post(h, win32con.WM_KEYUP,      VK_CODE['f'],          0)
                time.sleep(0.1)
                _post(h, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lp)
                time.sleep(0.1)
                _post(h, win32con.WM_LBUTTONUP,  0,                    lp)
            except Exception:
                pass
            time.sleep(0.3)

    threading.Thread(target=_spammer, daemon=True).start()

    state             = "IDLE"
    state_timer       = time.time()
    current_key       = None
    last_valid_time   = time.time()
    last_green_center = None
    smooth_vel        = 0.0

    # Anti-spam + per-catch timing
    MIN_REEL_DURATION  = 2.5   # seconds — ignore catches faster than this (false positives)
    POST_CATCH_COOLDOWN = 1.5  # seconds — wait after a catch before detecting again
    reel_start_time    = None
    last_catch_time    = 0.0
    catch_durations    = []    # rolling list of real catch durations (seconds)

    if SHOW_DEBUG:
        cv2.namedWindow("Debug Vision", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("Debug Vision", SLIDER_ROI[2] * 2, SLIDER_ROI[3] * 6)

    def switch_key(new_key):
        nonlocal current_key
        if current_key != new_key:
            if current_key is not None:
                simulate_keyup(current_key, PROC)
            if new_key is not None:
                simulate_keydown(new_key, PROC)
            current_key = new_key

    try:
        with mss.mss() as sct:
            while not stop_ev.is_set():
                bbox = get_window_bbox(PROC)
                if not bbox:
                    time.sleep(0.2)
                    continue

                raw = np.array(sct.grab(bbox))
                img = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
                img = cv2.resize(img, (1920, 1080))

                x, y, w, h = SLIDER_ROI
                roi = img[y:y+h, x:x+w]
                hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

                mg = cv2.inRange(hsv, GREEN_LOWER, GREEN_UPPER)
                if MORPH_K > 0:
                    k  = np.ones((MORPH_K, MORPH_K), np.uint8)
                    mg = cv2.morphologyEx(mg, cv2.MORPH_CLOSE, k)
                contours_g, _ = cv2.findContours(mg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                clean_mg = np.zeros_like(mg)
                for cg in contours_g:
                    if cv2.contourArea(cg) > GREEN_MIN_A:
                        cv2.drawContours(clean_mg, [cg], -1, 255, -1)
                mg = clean_mg

                my = cv2.inRange(hsv, YELLOW_LOWER, YELLOW_UPPER)
                gmin, gmax = find_green_bounds(mg)
                yx         = find_yellow_center(my)

                if SHOW_DEBUG:
                    dv = roi.copy()
                    if gmin is not None:
                        cv2.rectangle(dv, (gmin, 0), (gmax, h-1), (0, 255, 0), 1)
                    if yx is not None:
                        cv2.line(dv, (yx, 0), (yx, h-1), (0, 255, 255), 1)
                    cv2.imshow("Debug Vision",
                               np.vstack([dv,
                                          cv2.cvtColor(mg, cv2.COLOR_GRAY2BGR),
                                          cv2.cvtColor(my, cv2.COLOR_GRAY2BGR)]))
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break

                now = time.time()

                if state == "REELING" and now - state_timer > STATE_TIMEOUT:
                    _log("State timeout - restarting...")
                    restarts_ref[0] += 1
                    state_queue.put(("RESTARTING", catches_ref[0], restarts_ref[0], catch_durations[:]))
                    break
                if state == "IDLE" and now - state_timer > IDLE_TIMEOUT:
                    _log("Idle timeout - restarting...")
                    restarts_ref[0] += 1
                    state_queue.put(("RESTARTING", catches_ref[0], restarts_ref[0], catch_durations[:]))
                    break

                if state == "IDLE":
                    state_queue.put(("IDLE", catches_ref[0], restarts_ref[0], catch_durations[:]))
                    if gmin is not None and (now - last_catch_time) >= POST_CATCH_COOLDOWN:
                        smooth_vel        = 0.0
                        last_green_center = (gmin + gmax) // 2
                        last_valid_time   = now
                        reel_start_time   = now
                        state             = "REELING"
                        state_timer       = now
                        _log("Fish detected - reeling!")

                elif state == "REELING":
                    state_queue.put(("REELING", catches_ref[0], restarts_ref[0], catch_durations[:]))
                    if gmin is not None and yx is not None:
                        gc = (gmin + gmax) // 2
                        if last_green_center is not None and gc != last_green_center:
                            dt = now - last_valid_time
                            if 0 < dt < 0.2:
                                smooth_vel = 0.25 * smooth_vel + 0.75 * (gc - last_green_center) / dt
                            else:
                                smooth_vel = 0.0
                            last_green_center = gc
                            last_valid_time   = now

                        target = gc + smooth_vel * PREDICT_TIME
                        target = max(gmin + 10, min(target, gmax - 10))

                        if yx < target - CENTER_TOL:
                            switch_key(KEY_RIGHT)
                        elif yx > target + CENTER_TOL:
                            switch_key(KEY_LEFT)
                        else:
                            switch_key(None)
                    else:
                        switch_key(None)
                        reel_duration = now - reel_start_time if reel_start_time else 0
                        if reel_duration >= MIN_REEL_DURATION:
                            # Real catch — record timing
                            catch_durations.append(reel_duration)
                            if len(catch_durations) > 30:   # keep last 30 catches
                                catch_durations.pop(0)
                            catches_ref[0] += 1
                            last_catch_time = now
                            _log(f"Catch #{catches_ref[0]} ({reel_duration:.1f}s)")
                        else:
                            _log(f"False positive ignored ({reel_duration:.1f}s reel)")
                        state_queue.put(("IDLE", catches_ref[0], restarts_ref[0], catch_durations[:]))
                        state       = "IDLE"
                        state_timer = now
                        reel_start_time = None

    except Exception as e:
        _log_err(f"Macro crashed: {e}")
        _log_err(traceback.format_exc())
    finally:
        spammer_active[0] = False
        force_release_all_keys(cfg)
        if SHOW_DEBUG:
            cv2.destroyAllWindows()


def macro_runner(cfg: dict):
    catches  = [0]
    restarts = [0]
    try:
        while not stop_event.is_set():
            auto_fishing(cfg, stop_event, catches, restarts)
            if stop_event.is_set():
                break
            _log("Restarting in 1s...")
            time.sleep(1)
    except Exception as e:
        _log_err(f"Fatal error: {e}")
        _log_err(traceback.format_exc())
    finally:
        _log("Macro thread exited.")
        state_queue.put(("STOPPED", catches[0], restarts[0], []))


# ══════════════════════════════════════════════════════════════════════════════
#  GUI
# ══════════════════════════════════════════════════════════════════════════════
class FishingApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("NTE Auto Fisher")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._running         = False
        self._start_time      = None
        self._catches         = 0
        self._restarts        = 0
        self._catch_durations = []
        self._hotkey_thread   = None
        self._hotkey_stop     = threading.Event()
        self._topmost_var     = tk.BooleanVar(value=False)
        self._hotkey_var      = tk.StringVar(value="F6")

        self._build_ui()
        self._load_settings()
        # Auto-save whenever any setting changes
        self._hotkey_var.trace_add("write", lambda *_: self._save_settings())
        self._topmost_var.trace_add("write", lambda *_: self._save_settings())
        self._debug_var.trace_add("write", lambda *_: self._save_settings())
        for var in self._vars.values():
            var.trace_add("write", lambda *_: self._save_settings())
        self._process_var.trace_add("write", lambda *_: self._save_settings())
        self.report_callback_exception = self._tk_exception_handler
        self._poll()

    # ── Panels ────────────────────────────────────────────────────────────────
    def _panel(self, parent, title: str, pady_bottom: int = 0) -> tk.Frame:
        outer = tk.Frame(parent, bg=BG2, highlightthickness=1, highlightbackground=BORDER)
        outer.pack(fill="x", pady=(0, pady_bottom))
        tk.Label(outer, text=title, font=("Consolas", 8, "bold"),
                 bg=BG2, fg=TEXT_DIM, pady=4).pack(anchor="w", padx=10)
        tk.Frame(outer, bg=BORDER, height=1).pack(fill="x")
        return outer

    # ── Build UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────────────
        title_bar = tk.Frame(self, bg=BG3, pady=8)
        title_bar.pack(fill="x")
        tk.Label(title_bar, text="NTE AUTO FISHER",
                 font=("Consolas", 13, "bold"), bg=BG3, fg=ACCENT).pack(side="left", padx=16)
        self._status_dot = tk.Label(title_bar, text="●", font=("Consolas", 18), bg=BG3, fg=DIM)
        self._status_dot.pack(side="right", padx=16)
        self._status_lbl = tk.Label(title_bar, text="IDLE",
                                    font=("Consolas", 10, "bold"), bg=BG3, fg=TEXT_DIM)
        self._status_lbl.pack(side="right")
        # Settings nav button in header
        self._nav_btn = tk.Button(
            title_bar, text="⚙  SETTINGS", font=("Consolas", 8, "bold"),
            bg=BG3, fg=TEXT_DIM, activebackground=DIM, activeforeground=ACCENT,
            relief="flat", bd=0, padx=10, pady=4, cursor="hand2",
            command=self._show_settings)
        self._nav_btn.pack(side="right", padx=4)

        tk.Frame(self, bg=ACCENT, height=2).pack(fill="x")

        # ── Page container ────────────────────────────────────────────────────
        self._page_container = tk.Frame(self, bg=BG)
        self._page_container.pack(fill="both", expand=True)

        self._main_page     = tk.Frame(self._page_container, bg=BG)
        self._settings_page = tk.Frame(self._page_container, bg=BG)

        self._build_main_page()
        self._build_settings_page()
        self._show_main()  # start on main

        # ── Footer ────────────────────────────────────────────────────────────
        self._footer_sep = tk.Frame(self, bg=BORDER, height=1)
        self._footer_sep.pack(fill="x")
        self._footer = tk.Frame(self, bg=BG3, pady=10, padx=14)
        self._footer.pack(fill="x")
        self._start_btn = tk.Button(
            self._footer, text="START", font=("Consolas", 10, "bold"),
            bg=ACCENT, fg=BG, activebackground=ACCENT2, activeforeground=BG,
            relief="flat", bd=0, padx=20, pady=8, cursor="hand2",
            command=self._toggle)
        self._start_btn.pack(side="left")
        self._footer_hotkey_lbl = tk.Label(
            self._footer, text="F6",
            font=("Consolas", 10, "bold"),
            bg=BG2, fg=ACCENT,
            relief="flat", bd=0, padx=20, pady=8)
        self._footer_hotkey_lbl.pack(side="left", padx=(4, 0))
        self._hotkey_var.trace_add("write", lambda *_: self._update_footer_hotkey())
        tk.Button(self._footer, text="QUIT", font=("Consolas", 10, "bold"),
                  bg=BG2, fg=TEXT_DIM, activebackground=RED, activeforeground="white",
                  relief="flat", bd=0, padx=20, pady=8, cursor="hand2",
                  command=self._on_close).pack(side="right")

    # ── Main page ─────────────────────────────────────────────────────────────
    def _build_main_page(self):
        p = self._main_page
        body = tk.Frame(p, bg=BG, padx=14, pady=10)
        body.pack(fill="both", expand=True)
        left  = tk.Frame(body, bg=BG)
        right = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right.pack(side="left", fill="both")

        # Stats
        self._catches_var  = tk.StringVar(value="0")
        self._restarts_var = tk.StringVar(value="0")
        self._runtime_var  = tk.StringVar(value="00:00:00")
        self._cpm_var      = tk.StringVar(value="--")
        sf = self._panel(left, "STATS", pady_bottom=8)
        g  = tk.Frame(sf, bg=BG2, padx=10, pady=8)
        g.pack(fill="x")
        for row, (lbl, var, col) in enumerate([
            ("CATCHES",    self._catches_var,  ACCENT),
            ("RESTARTS",   self._restarts_var, YELLOW),
            ("RUNTIME",    self._runtime_var,  TEXT),
            ("CATCHES/HR", self._cpm_var,      TEXT_DIM),
        ]):
            tk.Label(g, text=lbl, font=FONT_MONO, bg=BG2, fg=TEXT_DIM,
                     anchor="w", width=12).grid(row=row, column=0, sticky="w", pady=1)
            tk.Label(g, textvariable=var, font=FONT_STAT, bg=BG2,
                     fg=col, anchor="e").grid(row=row, column=1, sticky="e", padx=(20, 0), pady=1)
        g.columnconfigure(1, weight=1)

        # Log
        lf = self._panel(right, "LOG")
        self._log_text = tk.Text(lf, width=44, height=24,
                                 bg=BG, fg=TEXT, font=FONT_MONO,
                                 relief="flat", bd=0, padx=8, pady=6,
                                 state="disabled", wrap="word",
                                 insertbackground=ACCENT)
        self._log_text.pack(fill="both", expand=True, padx=4, pady=4)
        self._log_text.tag_config("green",  foreground=ACCENT)
        self._log_text.tag_config("yellow", foreground=YELLOW)
        self._log_text.tag_config("red",    foreground=RED)
        self._log_text.tag_config("dim",    foreground=TEXT_DIM)

    # ── Settings page ─────────────────────────────────────────────────────────
    def _build_settings_page(self):
        p = self._settings_page
        body = tk.Frame(p, bg=BG, padx=14, pady=10)
        body.pack(fill="both", expand=True)

        # Back button row
        back_row = tk.Frame(body, bg=BG)
        back_row.pack(fill="x", pady=(0, 8))
        tk.Button(back_row, text="← BACK", font=("Consolas", 9, "bold"),
                  bg=BG2, fg=TEXT_DIM, activebackground=DIM, activeforeground=ACCENT,
                  relief="flat", bd=0, padx=12, pady=4, cursor="hand2",
                  command=self._show_main).pack(side="left")

        # ── Hotkey section ────────────────────────────────────────────────────
        hf = self._panel(body, "HOTKEY", pady_bottom=8)
        hg = tk.Frame(hf, bg=BG2, padx=10, pady=8)
        hg.pack(fill="x")

        tk.Label(hg, text="Start/Stop Key", font=FONT_MONO, bg=BG2, fg=TEXT_DIM,
                 anchor="w", width=16).grid(row=0, column=0, sticky="w", pady=2)

        hkey_row = tk.Frame(hg, bg=BG2)
        hkey_row.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=2)

        tk.Button(hkey_row, text="Start / Stop", font=("Consolas", 9, "bold"),
                  bg=BG3, fg=TEXT, activebackground=DIM, activeforeground=ACCENT,
                  relief="flat", bd=0, padx=10, pady=6, cursor="hand2",
                  command=self._open_hotkey_dialog).pack(side="left", padx=(0, 6))

        self._hotkey_display = tk.Label(
            hkey_row, textvariable=self._hotkey_var,
            font=("Consolas", 13, "bold"), bg=DIM, fg=ACCENT,
            width=8, anchor="center", pady=4, relief="flat")
        self._hotkey_display.pack(side="left", fill="x", expand=True)

        self._hotkey_status = tk.Label(hg, text="● Listening", font=FONT_MONO,
                                       bg=BG2, fg=ACCENT)
        self._hotkey_status.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        hg.columnconfigure(1, weight=1)

        # ── Window section ────────────────────────────────────────────────────
        wf = self._panel(body, "WINDOW", pady_bottom=8)
        wg = tk.Frame(wf, bg=BG2, padx=10, pady=8)
        wg.pack(fill="x")

        tk.Checkbutton(wg, text="Always on top  (stays visible over game)",
                       variable=self._topmost_var,
                       command=self._apply_topmost,
                       bg=BG2, fg=TEXT, selectcolor=BG3,
                       activebackground=BG2, activeforeground=ACCENT,
                       font=FONT_MONO).pack(side="left")

        # ── Process picker ────────────────────────────────────────────────────
        self._vars = {}
        pf = self._panel(body, "PROCESS", pady_bottom=8)
        pg = tk.Frame(pf, bg=BG2, padx=10, pady=8)
        pg.pack(fill="x")

        tk.Label(pg, text="Game Process", font=FONT_MONO, bg=BG2, fg=TEXT_DIM,
                 anchor="w", width=14).grid(row=0, column=0, sticky="w", pady=2)

        self._process_var = tk.StringVar(value="HTGame.exe")

        # Style the combobox to match the dark theme
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Dark.TCombobox",
                        fieldbackground=BG3, background=BG3,
                        foreground=TEXT, selectbackground=DIM,
                        selectforeground=ACCENT, arrowcolor=ACCENT,
                        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
        style.map("Dark.TCombobox",
                  fieldbackground=[("readonly", BG3)],
                  foreground=[("readonly", TEXT)],
                  selectbackground=[("readonly", DIM)])

        self._proc_combo = ttk.Combobox(
            pg, textvariable=self._process_var,
            font=FONT_MONO, style="Dark.TCombobox",
            state="readonly", width=20)
        self._proc_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=2)

        tk.Button(pg, text="↺ REFRESH", font=("Consolas", 8, "bold"),
                  bg=DIM, fg=ACCENT, activebackground=ACCENT, activeforeground=BG,
                  relief="flat", bd=0, padx=8, pady=3, cursor="hand2",
                  command=self._refresh_processes).grid(row=1, column=1, sticky="e",
                                                        padx=(8, 0), pady=(4, 0))
        self._proc_status = tk.Label(pg, text="Click ↺ to scan", font=FONT_MONO,
                                     bg=BG2, fg=TEXT_DIM)
        self._proc_status.grid(row=1, column=0, sticky="w", pady=(4, 0))
        pg.columnconfigure(1, weight=1)

        # Populate immediately
        self._refresh_processes()

        # ── Config section ────────────────────────────────────────────────────
        fields = [
            ("Key Left",       "key_left",       "a"),
            ("Key Right",      "key_right",       "d"),
            ("Center Tol.",    "center_tol",      "5"),
            ("Predict Time",   "predict_time",    "0.08"),
            ("Morph Kernel",   "morph_kernel",    "21"),
            ("Green Min Area", "green_min_area",  "1400"),
            ("State Timeout",  "state_timeout",   "20"),
            ("Idle Timeout",   "idle_timeout",    "10"),
        ]
        cf = self._panel(body, "CONFIG", pady_bottom=8)
        cg = tk.Frame(cf, bg=BG2, padx=10, pady=8)
        cg.pack(fill="x")
        for row, (label, key, default) in enumerate(fields):
            tk.Label(cg, text=label, font=FONT_MONO, bg=BG2, fg=TEXT_DIM,
                     anchor="w", width=16).grid(row=row, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=default)
            self._vars[key] = var
            tk.Entry(cg, textvariable=var, font=FONT_MONO,
                     bg=BG3, fg=TEXT, insertbackground=ACCENT,
                     relief="flat", bd=4, width=14,
                     highlightthickness=1, highlightbackground=BORDER,
                     highlightcolor=ACCENT).grid(row=row, column=1, sticky="ew",
                                                 padx=(8, 0), pady=2)
        cg.columnconfigure(1, weight=1)

        self._debug_var = tk.BooleanVar(value=False)
        dbrow = tk.Frame(cf, bg=BG2, padx=10, pady=4)
        dbrow.pack(fill="x")
        tk.Checkbutton(dbrow, text="Show Debug Vision", variable=self._debug_var,
                       bg=BG2, fg=TEXT, selectcolor=BG3,
                       activebackground=BG2, activeforeground=ACCENT,
                       font=FONT_MONO).pack(side="left")

    # ── Page switching ────────────────────────────────────────────────────────
    def _show_main(self):
        self._settings_page.pack_forget()
        self._main_page.pack(fill="both", expand=True)
        self._nav_btn.config(text="⚙  SETTINGS", command=self._show_settings)
        if hasattr(self, "_footer_sep"):
            self._footer_sep.pack(fill="x")
            self._footer.pack(fill="x")

    def _show_settings(self):
        self._main_page.pack_forget()
        if hasattr(self, "_footer"):
            self._footer.pack_forget()
            self._footer_sep.pack_forget()
        self._settings_page.pack(fill="both", expand=True)
        self._nav_btn.config(text="◀  MAIN", command=self._show_main)

    # ── Settings persistence ──────────────────────────────────────────────────
    def _settings_path(self):
        import os
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "nte_autofisher_settings.json")

    def _save_settings(self):
        import json, os
        data = {
            "hotkey":       self._hotkey_var.get(),
            "process":      self._process_var.get(),
            "always_on_top": self._topmost_var.get(),
        }
        for key, var in self._vars.items():
            data[key] = var.get()
        data["show_debug"] = self._debug_var.get()
        try:
            with open(self._settings_path(), "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _load_settings(self):
        import json
        try:
            with open(self._settings_path()) as f:
                data = json.load(f)
        except Exception:
            return
        if "hotkey" in data:
            self._hotkey_var.set(data["hotkey"])
        if "process" in data:
            self._process_var.set(data["process"])
        if "always_on_top" in data:
            self._topmost_var.set(data["always_on_top"])
            self._apply_topmost()
        for key, var in self._vars.items():
            if key in data:
                var.set(data[key])
        if "show_debug" in data:
            self._debug_var.set(data["show_debug"])

    # ── Always-on-top ─────────────────────────────────────────────────────────
    def _apply_topmost(self):
        self.wm_attributes("-topmost", self._topmost_var.get())

    def _update_footer_hotkey(self):
        key = self._hotkey_var.get().strip() or "F6"
        self._footer_hotkey_lbl.config(text=key)

    # ── Hotkey dialog ─────────────────────────────────────────────────────────
    def _open_hotkey_dialog(self):
        """Open a modal dialog that waits for a keypress then shows Ok/Cancel."""
        prev_key = self._hotkey_var.get()

        dlg = tk.Toplevel(self)
        dlg.title("Hotkey Setting")
        dlg.configure(bg=BG2)
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()
        dlg.wm_attributes("-topmost", self._topmost_var.get())

        self.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width()  - 260) // 2
        y = self.winfo_rooty() + (self.winfo_height() - 110) // 2
        dlg.geometry(f"260x110+{x}+{y}")

        captured_key   = [None]
        is_listening   = [False]   # True while waiting for a keypress
        capture_stop   = [False]   # signal capture thread to abort

        top = tk.Frame(dlg, bg=BG2, padx=12, pady=10)
        top.pack(fill="x")

        press_btn = tk.Button(
            top, text="Start / Stop", font=("Consolas", 9, "bold"),
            bg=BG3, fg=TEXT, activebackground=DIM, activeforeground=ACCENT,
            relief="flat", bd=0, padx=10, pady=6, cursor="hand2")
        press_btn.pack(side="left", padx=(0, 8))

        key_lbl_var = tk.StringVar(value=prev_key if prev_key else "...")
        key_lbl = tk.Label(
            top, textvariable=key_lbl_var,
            font=("Consolas", 15, "bold"), bg=DIM, fg=ACCENT,
            width=9, anchor="center", pady=4, relief="flat")
        key_lbl.pack(side="left", fill="x", expand=True)

        bot = tk.Frame(dlg, bg=BG2, padx=12, pady=6)
        bot.pack(fill="x")

        ok_btn = tk.Button(bot, text="Ok", font=FONT_MONO,
                           bg=DIM, fg=TEXT, activebackground=ACCENT,
                           activeforeground=BG, relief="flat", bd=0,
                           padx=16, pady=5, cursor="hand2",
                           state="normal" if prev_key else "disabled")
        cancel_btn = tk.Button(bot, text="Cancel", font=FONT_MONO,
                               bg=DIM, fg=TEXT, activebackground=RED,
                               activeforeground="white", relief="flat", bd=0,
                               padx=16, pady=5, cursor="hand2")
        ok_btn.pack(side="left", padx=(0, 6))
        cancel_btn.pack(side="left")

        # ── visual states ──────────────────────────────────────────────────────
        def _set_waiting():
            """Dim everything — awaiting keypress."""
            key_lbl_var.set("?  ?  ?")
            key_lbl.config(fg=TEXT_DIM, bg=BG3)
            press_btn.config(state="disabled", fg=TEXT_DIM, bg=BG3)
            ok_btn.config(state="disabled")

        def _set_captured(display):
            """Restore UI after a key is captured."""
            key_lbl_var.set(display)
            key_lbl.config(fg=ACCENT, bg=DIM)
            press_btn.config(state="normal", fg=TEXT, bg=BG3)
            ok_btn.config(state="normal")

        # ── capture thread ─────────────────────────────────────────────────────
        def _capture():
            try:
                import keyboard as kb
                while True:
                    event = kb.read_event(suppress=True)
                    if capture_stop[0]:
                        return
                    if not is_listening[0]:
                        continue
                    if event.event_type == 'down':
                        name    = event.name
                        display = name.upper() if len(name) <= 3 else name.title()
                        captured_key[0] = display
                        is_listening[0] = False
                        dlg.after(0, lambda d=display: _set_captured(d))
                        # stay alive so Start/Stop can re-trigger
            except Exception:
                pass

        capture_thread = threading.Thread(target=_capture, daemon=True)
        capture_thread.start()

        # ── Start/Stop button handler ──────────────────────────────────────────
        def _start_listening():
            if is_listening[0]:
                return   # already waiting
            is_listening[0] = True
            _set_waiting()

        press_btn.config(command=_start_listening)

        # ── Ok / Cancel ────────────────────────────────────────────────────────
        def _ok():
            capture_stop[0] = True
            is_listening[0] = False
            if captured_key[0]:
                self._hotkey_var.set(captured_key[0])
                self._apply_hotkey()
            dlg.destroy()

        def _cancel():
            capture_stop[0] = True
            is_listening[0] = False
            self._hotkey_var.set(prev_key)
            dlg.destroy()

        ok_btn.config(command=_ok)
        cancel_btn.config(command=_cancel)
        dlg.protocol("WM_DELETE_WINDOW", _cancel)

        # Start listening immediately on open
        _start_listening()

    # ── Hotkey management ─────────────────────────────────────────────────────
    def _refresh_processes(self):
        self._proc_status.config(text="Scanning...", fg=YELLOW)
        self.update_idletasks()
        def _scan():
            procs = get_windowed_processes()
            def _apply():
                current = self._process_var.get()
                self._proc_combo["values"] = procs
                if current in procs:
                    self._process_var.set(current)
                elif procs:
                    default = next((p for p in procs if "htgame" in p.lower()), procs[0])
                    self._process_var.set(default)
                self._proc_status.config(
                    text=f"Found {len(procs)} processes", fg=TEXT_DIM)
            self.after(0, _apply)
        threading.Thread(target=_scan, daemon=True).start()

    def _apply_hotkey(self):
        self._hotkey_stop.set()
        if self._hotkey_thread and self._hotkey_thread.is_alive():
            self._hotkey_thread.join(timeout=0.5)
        self._hotkey_stop.clear()
        self._start_hotkey_listener()

    def _start_hotkey_listener(self):
        key = self._hotkey_var.get().strip() or "F6"
        self._hotkey_var.set(key)

        def _listener():
            try:
                import keyboard as kb
                # Use kb.on_press_key for broad compatibility with all keys.
                # Normalise to lower-case as required by the keyboard library.
                key_norm = key.lower()
                handler_id = kb.on_press_key(key_norm, lambda _: self.after(0, self._toggle),
                                             suppress=False)
                self.after(0, lambda: self._hotkey_status.config(
                    text=f"● Listening for [{key}]", fg=ACCENT))
                self._hotkey_stop.wait()
                kb.unhook(handler_id)
            except ImportError:
                self.after(0, lambda: self._hotkey_status.config(
                    text="✖ Install 'keyboard' pip pkg", fg=RED))
            except Exception as e:
                self.after(0, lambda: self._hotkey_status.config(
                    text=f"✖ {e}", fg=RED))

        self._hotkey_thread = threading.Thread(target=_listener, daemon=True)
        self._hotkey_thread.start()

    # ── Exception handler ─────────────────────────────────────────────────────
    def _tk_exception_handler(self, exc_type, exc_val, exc_tb):
        msg = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
        self._append_log(f"[{time.strftime('%H:%M:%S')}] ERR {exc_val}", "red")
        for line in msg.strip().splitlines():
            self._append_log(f"  {line}", "red")

    # ── Log ───────────────────────────────────────────────────────────────────
    def _append_log(self, msg: str, tag: str = None):
        if tag is None:
            if "ERR" in msg or "crash" in msg.lower() or "fatal" in msg.lower():
                tag = "red"
            elif "Catch" in msg or "Found" in msg or "detected" in msg:
                tag = "green"
            elif "timeout" in msg.lower() or "restart" in msg.lower():
                tag = "yellow"
            else:
                tag = "dim"
        self._log_text.config(state="normal")
        self._log_text.insert("end", msg + "\n", tag)
        self._log_text.see("end")
        self._log_text.config(state="disabled")

    def _set_status(self, state: str):
        m = {
            "IDLE":       (TEXT_DIM, "o"),
            "SEARCHING":  (YELLOW,   "o"),
            "REELING":    (ACCENT,   "●"),
            "RESTARTING": (YELLOW,   "o"),
            "STOPPED":    (RED,      "●"),
        }
        fg, dot = m.get(state, (TEXT_DIM, "o"))
        self._status_lbl.config(text=state, fg=fg)
        self._status_dot.config(text=dot,   fg=fg)

    # ── Config builder ────────────────────────────────────────────────────────
    def _build_config(self) -> dict:
        v = self._vars
        return {
            "process":        self._process_var.get().strip(),
            "key_left":       v["key_left"].get().strip()  or "a",
            "key_right":      v["key_right"].get().strip() or "d",
            "center_tol":     int(float(v["center_tol"].get())),
            "predict_time":   float(v["predict_time"].get()),
            "morph_kernel":   int(float(v["morph_kernel"].get())),
            "green_min_area": int(float(v["green_min_area"].get())),
            "state_timeout":  float(v["state_timeout"].get()),
            "idle_timeout":   float(v["idle_timeout"].get()),
            "show_debug":     self._debug_var.get(),
            "slider_roi":     (608, 65, 713, 20),
            "green_lower":    np.array([70, 190,   0]),
            "green_upper":    np.array([90, 255, 255]),
            "yellow_lower":   np.array([ 0,   0, 215]),
            "yellow_upper":   np.array([60, 160, 255]),
        }

    # ── Controls ──────────────────────────────────────────────────────────────
    def _toggle(self):
        if not self._running:
            self._start()
        else:
            self._stop()

    def _start(self):
        try:
            cfg = self._build_config()
        except Exception as e:
            self._append_log(f"[{time.strftime('%H:%M:%S')}] ERR Config error: {e}", "red")
            return

        stop_event.clear()
        threading.Thread(target=macro_runner, args=(cfg,), daemon=True).start()

        self._running         = True
        self._start_time      = time.time()
        self._catches         = 0
        self._restarts        = 0
        self._catch_durations = []

        self._start_btn.config(text="STOP", bg=RED,
                               activebackground="#cc0000",
                               fg="white", activeforeground="white")
        self._set_status("SEARCHING")
        self._append_log(f"[{time.strftime('%H:%M:%S')}] Started -> {cfg['process']}", "green")
        self._show_main()   # auto-switch back to main when starting

    def _stop(self):
        stop_event.set()
        self._running = False
        self._start_btn.config(text="START", bg=ACCENT,
                               activebackground=ACCENT2,
                               fg=BG, activeforeground=BG)
        self._set_status("STOPPED")
        self._append_log(f"[{time.strftime('%H:%M:%S')}] Stopped by user", "yellow")

    def _on_close(self):
        self._save_settings()
        self._hotkey_stop.set()
        stop_event.set()
        self.destroy()
        sys.exit(0)

    # ── Poll loop ─────────────────────────────────────────────────────────────
    def _poll(self):
        try:
            while True:
                self._append_log(log_queue.get_nowait())
        except queue.Empty:
            pass

        last = None
        try:
            while True:
                last = state_queue.get_nowait()
        except queue.Empty:
            pass

        if last:
            state, catches, restarts, catch_durations = last
            self._catches         = catches
            self._restarts        = restarts
            self._catch_durations = catch_durations
            self._catches_var.set(str(catches))
            self._restarts_var.set(str(restarts))
            self._set_status(state)
            if state == "STOPPED" and self._running:
                self._running = False
                self._start_btn.config(text="START", bg=ACCENT,
                                       activebackground=ACCENT2,
                                       fg=BG, activeforeground=BG)

        if self._running and self._start_time:
            elapsed = time.time() - self._start_time
            self._runtime_var.set(str(timedelta(seconds=int(elapsed))))
            catch_durations = getattr(self, '_catch_durations', [])
            if len(catch_durations) >= 2:
                avg_secs = sum(catch_durations) / len(catch_durations)
                self._cpm_var.set(f"{3600 / avg_secs:.0f}")
            elif elapsed >= 60 and self._catches > 0:
                self._cpm_var.set(f"{self._catches / (elapsed / 3600):.0f}")
            else:
                self._cpm_var.set("--")

        self.after(150, self._poll)


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = FishingApp()
    app._start_hotkey_listener()   # start default hotkey (F6) on launch
    app.mainloop()
