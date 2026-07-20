#!/usr/bin/env python3
"""
PoE Companion — encoder-driven regex selector.

Reads the wireless Sofle's PoE-layer keys via evdev, shows a scrolling regex
list on the portrait monitor, and types the chosen regex into the focused
window via ydotool.

Usage:
    poe_selector.py --list-devices   # show input devices, find the Sofle
    poe_selector.py --watch          # print raw key events from the Sofle
    poe_selector.py                  # run the HUD daemon

Config lives in ~/.config/poe-companion/ (written with defaults on first run).
Needs: python-evdev, PyQt5, and membership of the `input` group.
"""
import os, sys, json, argparse, subprocess, shutil, html, time
from pathlib import Path

# Run the Qt HUD under XWayland so we can self-position + stay-on-top reliably.
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "poe-companion"
REPO_DIR = Path(__file__).resolve().parent.parent
PLANNER_HTML = REPO_DIR / "index.html"

GEM_HEX = {"red": "#d05b5b", "green": "#7bb662", "blue": "#6fa8dc", "white": "#e8e0d0"}

DEFAULT_CONFIG = {
    # Exact by-id path is most stable; if it's missing we fall back to name match.
    "device": "/dev/input/by-id/usb-ZMK_Project_Sofle_4CF2344BAFA2C7BE-event-kbd",
    "device_name_contains": "Sofle",
    "monitor": {"x": 0, "y": 0, "w": 1080, "h": 1920},   # HDMI-A-1 portrait
    "keys": {"prev": "KEY_F18", "next": "KEY_F14", "select": "KEY_F15", "gem_done": "KEY_F16"},
    "ydotool_socket": f"/run/user/{os.getuid()}/.ydotool_socket",
    "key_delay_ms": 6,
    "idle_hide_ms": 4000,
    "visible_rows": 5,          # rows shown above & below the current one
    "idle_height": 118,         # px height of the idle next-gem strip
    "idle_gem_size": 38,        # px font size of the gem name in the idle strip (~3x)
    "hud_top": 1140,            # px from monitor top where the HUD top edge sits (meets Discord's bottom)
    "hud_right_margin": 12,     # px gap between the HUD and the screen's right edge
    "gem_done_underscore": True,# underscore (Shift+Minus, i.e. lower-layer T) also fires gem_done
    "regex_ctrl_f": True,       # regex entries: press Ctrl+F before typing
    "action_gap_ms": 40,        # pause between a key-combo and typing (ms)
}

DEFAULT_REGEXES = [
    {"cat": "Movement",   "label": "MS boots (any)",  "rx": "ovement"},
    {"cat": "Movement",   "label": "MS boots 25%+",   "rx": "2[5-9]%.*ovem|3.%.*ovem"},
    {"cat": "Defence",    "label": "Life",            "rx": "imum Life"},
    {"cat": "Defence",    "label": "Any resistance",  "rx": "esistance"},
    {"cat": "Defence",    "label": "Life + Fire res", "rx": "imum Life.*|o Fire Res.*"},
    {"cat": "Attributes", "label": "Any attribute",   "rx": "trength|exterity|ligence"},
    {"cat": "Caster wpn", "label": "Spell damage %",  "rx": "pell Damage"},
    {"cat": "Caster wpn", "label": "Cast speed",      "rx": "ast Speed"},
    {"cat": "Caster wpn", "label": "+1 gem level",    "rx": "evel of all"},
    {"cat": "Attack wpn", "label": "Phys damage %",   "rx": "ncreased Phys"},
    {"cat": "Attack wpn", "label": "Attack speed",    "rx": "ttack Speed"},
    {"cat": "Utility",    "label": "Rarity of items", "rx": "arity of Items"},
]

DEFAULT_GEMS = [
    {"label": "example: your first skill", "act": "A1", "source": "reward", "done": False},
]


def load_json(name, default):
    p = CONFIG_DIR / name
    if not p.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(default, indent=2))
        print(f"[poe] wrote defaults → {p}")
        return default
    try:
        return json.loads(p.read_text())
    except Exception as e:
        print(f"[poe] {p} is invalid ({e}); using defaults", file=sys.stderr)
        return default


def save_json(name, data):
    (CONFIG_DIR / name).write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------- evdev helpers
def find_device(cfg):
    import evdev
    path = cfg.get("device")
    if path and Path(path).exists():
        return path
    needle = (cfg.get("device_name_contains") or "").lower()
    for p in evdev.list_devices():
        try:
            d = evdev.InputDevice(p)
        except Exception:
            continue
        if needle and needle in d.name.lower():
            return d.path
    return None


def cmd_list_devices():
    import evdev
    for p in evdev.list_devices():
        try:
            d = evdev.InputDevice(p)
            print(f"{p:40}  {d.name}")
        except PermissionError:
            print(f"{p:40}  <permission denied — add yourself to the 'input' group>")
    return 0


def cmd_watch(cfg):
    import evdev
    from evdev import categorize, ecodes
    path = find_device(cfg)
    if not path:
        print("[poe] Sofle device not found. Try --list-devices.", file=sys.stderr)
        return 1
    dev = evdev.InputDevice(path)
    print(f"[poe] watching {path}  ({dev.name}). Turn the knob / press keys. Ctrl-C to stop.")
    for ev in dev.read_loop():
        if ev.type == ecodes.EV_KEY:
            k = categorize(ev)
            state = {0: "up", 1: "down", 2: "repeat"}.get(ev.value, ev.value)
            print(f"  {k.keycode:20} {state}")
    return 0


# ---------------------------------------------------------------- the HUD app
def run_daemon(cfg, regexes, gems):
    from PyQt5 import QtCore, QtGui, QtWidgets
    import evdev
    from evdev import ecodes

    path = find_device(cfg)
    if not path:
        print("[poe] Sofle device not found. Try --list-devices.", file=sys.stderr)
        return 1

    keymap = cfg["keys"]
    action_for = {getattr(ecodes, v): k for k, v in keymap.items()}  # keycode int -> action
    underscore_gem_done = bool(cfg.get("gem_done_underscore", True))

    class Reader(QtCore.QThread):
        action = QtCore.pyqtSignal(str)
        error = QtCore.pyqtSignal(str)

        def run(self):
            try:
                dev = evdev.InputDevice(path)
            except PermissionError:
                self.error.emit("Permission denied reading the keyboard.\nAdd yourself to the 'input' group and re-login.")
                return
            shift = False
            SHIFTS = (ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT)
            for ev in dev.read_loop():
                if ev.type != ecodes.EV_KEY:
                    continue
                if ev.code in SHIFTS:
                    shift = ev.value != 0          # track held shift (down/hold = True)
                    continue
                if ev.value != 1:                  # key-down only
                    continue
                # underscore (Shift+Minus = lower-layer T) mirrors the gem-done knob press
                if underscore_gem_done and ev.code == ecodes.KEY_MINUS and shift:
                    self.action.emit("gem_done"); continue
                a = action_for.get(ev.code)
                if a:
                    self.action.emit(a)

    class Hud(QtWidgets.QWidget):
        def __init__(self):
            super().__init__(None,
                QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.Tool)
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
            self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)   # never steal game focus
            self.idx = 0
            self.enabled = True
            self.socket = cfg["ydotool_socket"]
            self.rows = int(cfg.get("visible_rows", 5))

            self.frame = QtWidgets.QFrame(self)
            self.frame.setObjectName("frame")
            lay = QtWidgets.QVBoxLayout(self.frame)
            lay.setContentsMargins(14, 12, 14, 12)
            lay.setSpacing(4)
            self.title = QtWidgets.QLabel("⚔ PoE regex")
            self.title.setObjectName("title")
            lay.addWidget(self.title)
            self.labels = []
            for _ in range(self.rows * 2 + 1):
                lb = QtWidgets.QLabel("")
                lb.setObjectName("row")
                lay.addWidget(lb)
                self.labels.append(lb)
            self.gemline = QtWidgets.QLabel("")
            self.gemline.setObjectName("gem")
            self.gemline.setTextFormat(QtCore.Qt.RichText)
            self.gemline.setAlignment(QtCore.Qt.AlignCenter)
            lay.addStretch(1)
            lay.addWidget(self.gemline, 0, QtCore.Qt.AlignHCenter)   # centered; stretches keep it vertically centered too
            lay.addStretch(1)

            self.setStyleSheet("""
                #frame { background: rgba(20,17,12,0.94); border:1px solid #c8aa6e; border-radius:14px; }
                #title { color:#c8aa6e; font:bold 15px 'sans-serif'; padding-bottom:4px; }
                #row   { color:#9a9082; font:14px 'sans-serif'; padding:3px 8px; border-radius:6px; }
                #row[cur="true"] { color:#20180a; background:#c8aa6e; font:bold 14px 'sans-serif'; }
                #row[head="true"] { color:#8f7a4e; font:bold 10px 'sans-serif'; padding:9px 8px 1px; }
                #gem   { color:#7bb662; font:13px 'sans-serif'; padding-top:8px; }
            """)

            outer = QtWidgets.QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.addWidget(self.frame)

            self.mode = "idle"
            self.idle_h = int(cfg.get("idle_height", 96))
            self.hide_timer = QtCore.QTimer(self, singleShot=True)
            self.hide_timer.timeout.connect(self.show_idle)   # after scrolling stops, fall back to idle (not hidden)
            self.redraw()
            self.apply_mode("idle")

        # --- rendering ---
        def redraw(self):
            # display list: label only, with a category heading whenever the category changes
            disp, last_cat = [], None
            for j, r in enumerate(regexes):
                cat = r.get("cat", "")
                if cat and cat != last_cat:
                    disp.append(("head", cat))
                last_cat = cat or None
                disp.append(("item", r, j))
            cur_disp = next((k for k, d in enumerate(disp) if d[0] == "item" and d[2] == self.idx), 0)
            m = len(disp)
            for i, lb in enumerate(self.labels):
                off = i - self.rows
                head = cur = False
                if m == 0:
                    lb.setText("")
                else:
                    d = disp[(cur_disp + off) % m]
                    if d[0] == "head":
                        lb.setText(d[1].upper()); head = True
                    else:
                        cur = (d[2] == self.idx)
                        lb.setText(("▶ " if cur else "   ") + d[1].get("label", ""))
                lb.setProperty("head", "true" if head else "false")
                lb.setProperty("cur", "true" if cur else "false")
                lb.style().unpolish(lb); lb.style().polish(lb)
            nxt = next((g for g in gems if not g.get("done")), None)
            if nxt:
                c = GEM_HEX.get(nxt.get("color", "white"), GEM_HEX["white"])
                big = int(cfg.get("idle_gem_size", 38)) if self.mode == "idle" else 13
                self.gemline.setText(
                    f'<span style="color:#9a9082">next gem · {html.escape(str(nxt.get("act","")))} </span>'
                    f'<span style="color:{c};font-weight:bold;font-size:{big}px">{html.escape(str(nxt.get("label","")))}</span>'
                    f'<span style="color:#9a9082"> ({html.escape(str(nxt.get("source","")))})</span>')
            else:
                self.gemline.setText("")

        # Portrait monitor, hugged against its RIGHT edge.
        #  scroll: right half-width, bottom third (top edge sits 2/3 down)
        #  idle:   right half-width, compact strip whose top also sits 2/3 down
        def compute_geom(self, mode):
            m = cfg["monitor"]; w = m["w"] // 2
            x = m["x"] + m["w"] - w - int(cfg.get("hud_right_margin", 12))
            top = m["y"] + int(cfg.get("hud_top", (m["h"] * 2) // 3))
            if mode == "scroll":
                y = top; h = (m["y"] + m["h"]) - top   # from HUD top down to the screen bottom
            else:
                y = top; h = self.idle_h
            return x, y, w, h

        def apply_mode(self, mode):
            self.mode = mode
            scroll = (mode == "scroll")
            self.title.setVisible(scroll)
            for lb in self.labels:
                lb.setVisible(scroll)
            x, y, w, h = self.compute_geom(mode)
            self.setFixedSize(w, h)   # force exact size so idle actually collapses back to the strip
            self.move(x, y)

        def show_idle(self):
            self.mode = "idle"; self.redraw(); self.apply_mode("idle"); self.show()

        def show_scroll(self):
            self.mode = "scroll"; self.redraw(); self.apply_mode("scroll"); self.show(); self.raise_()
            self.hide_timer.start(int(cfg.get("idle_hide_ms", 4000)))

        def flash(self):        # "show now" == pop the scroll view
            self.show_scroll()

        # --- actions ---
        def on_action(self, a):
            if not self.enabled:
                return
            if not regexes and a in ("prev", "next", "select"):
                return
            if a == "next":
                self.idx = (self.idx + 1) % len(regexes); self.flash()
            elif a == "prev":
                self.idx = (self.idx - 1) % len(regexes); self.flash()
            elif a == "select":
                self.send_entry(regexes[self.idx]); self.flash()
            elif a == "gem_done":
                nxt = next((g for g in gems if not g.get("done")), None)
                if nxt:
                    nxt["done"] = True; save_json("gems.json", gems)
                (self.show_scroll() if self.mode == "scroll" else self.show_idle())

        def send_entry(self, entry):
            # regex → Ctrl+F then type; command → Enter, type, Enter (e.g. /hideout)
            if not shutil.which("ydotool"):
                print("[poe] ydotool not found", file=sys.stderr); return
            env = dict(os.environ, YDOTOOL_SOCKET=self.socket)
            gap = cfg.get("action_gap_ms", 40) / 1000.0

            def key(*codes):
                seq = [f"{c}:1" for c in codes] + [f"{c}:0" for c in reversed(codes)]
                subprocess.run(["ydotool", "key", *seq], env=env, check=False)

            def typ(text):
                subprocess.run(["ydotool", "type", "--key-delay", str(cfg.get("key_delay_ms", 6)), "--", text],
                               env=env, check=False)

            text = entry.get("rx", "")
            try:
                if entry.get("command"):
                    key(ecodes.KEY_ENTER); time.sleep(gap); typ(text); time.sleep(gap); key(ecodes.KEY_ENTER)
                else:
                    if cfg.get("regex_ctrl_f", True):
                        key(ecodes.KEY_LEFTCTRL, ecodes.KEY_F); time.sleep(gap)
                    typ(text)
            except Exception as e:
                print(f"[poe] ydotool failed: {e}", file=sys.stderr)

    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)   # tray keeps us alive when the HUD hides
    hud = Hud()

    def reload_data():
        nonlocal regexes, gems
        regexes = load_json("regexes.json", DEFAULT_REGEXES)
        gems = load_json("gems.json", DEFAULT_GEMS)
        hud.idx = 0
        hud.show_idle()
        print(f"[poe] reloaded: {len(regexes)} regexes, {len(gems)} gems")

    def tray_icon():
        pm = QtGui.QPixmap(64, 64); pm.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pm); p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setBrush(QtGui.QColor("#c8aa6e")); p.setPen(QtCore.Qt.NoPen); p.drawEllipse(4, 4, 56, 56)
        p.setPen(QtGui.QColor("#20180a")); f = p.font(); f.setBold(True); f.setPointSize(30); p.setFont(f)
        p.drawText(pm.rect(), QtCore.Qt.AlignCenter, "P"); p.end()
        return QtGui.QIcon(pm)

    def open_planner():
        subprocess.Popen(["xdg-open", str(PLANNER_HTML)])

    tray = QtWidgets.QSystemTrayIcon(tray_icon(), app)
    tray.setToolTip("PoE Companion")

    def set_enabled(on):
        hud.enabled = on
        tray.setToolTip("PoE Companion" + ("" if on else " (disabled)"))
        (hud.show_idle() if on else hud.hide())

    def grab_from_downloads():
        dl = Path.home() / "Downloads"
        copied = []
        for name in ("regexes.json", "gems.json", "config.json"):
            src = dl / name
            if src.exists():
                shutil.copy2(src, CONFIG_DIR / name); copied.append(name)
        if copied:
            reload_data()
            tray.showMessage("PoE Companion", "Grabbed from Downloads: " + ", ".join(copied), tray_icon(), 4000)
        else:
            tray.showMessage("PoE Companion", "No regexes.json / gems.json found in ~/Downloads", tray_icon(), 4000)

    def refresh_hud():
        (hud.show_scroll() if hud.mode == "scroll" else hud.show_idle())

    def step_gem_back():
        idx = next((i for i, g in enumerate(gems) if not g.get("done")), len(gems))
        if idx > 0:
            gems[idx - 1]["done"] = False; save_json("gems.json", gems); refresh_hud()

    def reset_gems():
        for g in gems:
            g["done"] = False
        save_json("gems.json", gems); refresh_hud()
        tray.showMessage("PoE Companion", "Gem progression reset", tray_icon(), 3000)

    menu = QtWidgets.QMenu()
    act_en = menu.addAction("Enabled"); act_en.setCheckable(True); act_en.setChecked(True)
    act_en.toggled.connect(set_enabled)
    menu.addSeparator()
    menu.addAction("Open companion app", open_planner)
    menu.addAction("Grab latest from Downloads", grab_from_downloads)
    menu.addAction("Reload regexes + gems", reload_data)
    menu.addAction("Show HUD now", hud.flash)
    menu.addSeparator()
    menu.addAction("Gem: step back", step_gem_back)
    menu.addAction("Gem: reset progression", reset_gems)
    menu.addSeparator()
    menu.addAction("Quit", app.quit)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda r: open_planner() if r == QtWidgets.QSystemTrayIcon.Trigger else None)
    tray.show()

    reader = Reader()
    reader.action.connect(hud.on_action)
    reader.error.connect(lambda msg: (print("[poe]", msg, file=sys.stderr),
                                      QtWidgets.QMessageBox.critical(None, "PoE Companion", msg)))
    reader.start()
    print(f"[poe] running. Tray active. Listening on {path}. HUD on monitor {cfg['monitor']}.")
    hud.show_idle()   # persistent next-gem strip; scrolling pops the full list
    return app.exec_()


# ---------------------------------------------------------------- entry
def main():
    ap = argparse.ArgumentParser(description="PoE Companion encoder regex selector")
    ap.add_argument("--list-devices", action="store_true", help="list input devices and exit")
    ap.add_argument("--watch", action="store_true", help="print raw key events from the Sofle")
    args = ap.parse_args()

    try:
        import evdev  # noqa: F401
    except ImportError:
        print("[poe] python-evdev is not installed.  sudo pamac install python-evdev", file=sys.stderr)
        return 2

    cfg = load_json("config.json", DEFAULT_CONFIG)
    if args.list_devices:
        return cmd_list_devices()
    if args.watch:
        return cmd_watch(cfg)

    regexes = load_json("regexes.json", DEFAULT_REGEXES)
    gems = load_json("gems.json", DEFAULT_GEMS)
    return run_daemon(cfg, regexes, gems)


if __name__ == "__main__":
    sys.exit(main())
