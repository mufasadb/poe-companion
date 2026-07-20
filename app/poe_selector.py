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
import os, sys, json, argparse, subprocess, shutil
from pathlib import Path

# Run the Qt HUD under XWayland so we can self-position + stay-on-top reliably.
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "poe-companion"

DEFAULT_CONFIG = {
    # Exact by-id path is most stable; if it's missing we fall back to name match.
    "device": "/dev/input/by-id/usb-ZMK_Project_Sofle_4CF2344BAFA2C7BE-event-kbd",
    "device_name_contains": "Sofle",
    "monitor": {"x": 0, "y": 0, "w": 1080, "h": 1920},   # HDMI-A-1 portrait
    "keys": {"prev": "KEY_F13", "next": "KEY_F14", "select": "KEY_F15", "gem_done": "KEY_F16"},
    "ydotool_socket": f"/run/user/{os.getuid()}/.ydotool_socket",
    "key_delay_ms": 6,
    "idle_hide_ms": 4000,
    "visible_rows": 5,          # rows shown above & below the current one
}

DEFAULT_REGEXES = [
    {"label": "MS boots (any)",  "rx": "ovement"},
    {"label": "MS boots 25%+",   "rx": "2[5-9]%.*ovem|3.%.*ovem"},
    {"label": "Life",            "rx": "imum Life"},
    {"label": "Any resistance",  "rx": "esistance"},
    {"label": "Life + Fire res", "rx": "imum Life.*|o Fire Res.*"},
    {"label": "Any attribute",   "rx": "trength|exterity|ligence"},
    {"label": "Spell damage %",  "rx": "pell Damage"},
    {"label": "Cast speed",      "rx": "ast Speed"},
    {"label": "+1 gem level",    "rx": "evel of all"},
    {"label": "Phys damage %",   "rx": "ncreased Phys"},
    {"label": "Attack speed",    "rx": "ttack Speed"},
    {"label": "Rarity of items", "rx": "arity of Items"},
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

    class Reader(QtCore.QThread):
        action = QtCore.pyqtSignal(str)
        error = QtCore.pyqtSignal(str)

        def run(self):
            try:
                dev = evdev.InputDevice(path)
            except PermissionError:
                self.error.emit("Permission denied reading the keyboard.\nAdd yourself to the 'input' group and re-login.")
                return
            for ev in dev.read_loop():
                if ev.type == ecodes.EV_KEY and ev.value == 1:   # key-down only
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
            self.socket = cfg["ydotool_socket"]
            self.rows = int(cfg.get("visible_rows", 5))

            self.frame = QtWidgets.QFrame(self)
            self.frame.setObjectName("frame")
            lay = QtWidgets.QVBoxLayout(self.frame)
            lay.setContentsMargins(22, 22, 22, 22)
            lay.setSpacing(6)
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
            lay.addWidget(self.gemline)

            self.setStyleSheet("""
                #frame { background: rgba(20,17,12,0.94); border:1px solid #c8aa6e; border-radius:16px; }
                #title { color:#c8aa6e; font:bold 22px 'sans-serif'; padding-bottom:6px; }
                #row   { color:#9a9082; font:18px monospace; padding:6px 10px; border-radius:8px; }
                #row[cur="true"] { color:#20180a; background:#c8aa6e; font:bold 19px monospace; }
                #gem   { color:#7bb662; font:15px 'sans-serif'; padding-top:10px; }
            """)

            outer = QtWidgets.QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.addWidget(self.frame)

            m = cfg["monitor"]
            w = min(940, m["w"] - 40)
            self.setFixedWidth(w + 0)
            self.frame.setFixedWidth(w)
            self.redraw()
            self.adjustSize()
            self.move(m["x"] + (m["w"] - self.width()) // 2,
                      m["y"] + (m["h"] - self.height()) // 2)

            self.hide_timer = QtCore.QTimer(self, singleShot=True)
            self.hide_timer.timeout.connect(self.hide)

        # --- rendering ---
        def redraw(self):
            n = len(regexes)
            for i, lb in enumerate(self.labels):
                off = i - self.rows
                if n == 0:
                    lb.setText(""); continue
                j = (self.idx + off) % n
                r = regexes[j]
                cur = (off == 0)
                prefix = "▶ " if cur else "   "
                lb.setText(f"{prefix}{r['label']:<18} {r['rx']}")
                lb.setProperty("cur", "true" if cur else "false")
                lb.style().unpolish(lb); lb.style().polish(lb)
            nxt = next((g for g in gems if not g.get("done")), None)
            self.gemline.setText(f"next gem · {nxt['act']} {nxt['label']} ({nxt['source']})" if nxt else "")

        def flash(self):
            self.redraw()
            self.show(); self.raise_()
            self.hide_timer.start(int(cfg.get("idle_hide_ms", 4000)))

        # --- actions ---
        def on_action(self, a):
            if not regexes and a in ("prev", "next", "select"):
                return
            if a == "next":
                self.idx = (self.idx + 1) % len(regexes); self.flash()
            elif a == "prev":
                self.idx = (self.idx - 1) % len(regexes); self.flash()
            elif a == "select":
                self.type_text(regexes[self.idx]["rx"]); self.flash()
            elif a == "gem_done":
                nxt = next((g for g in gems if not g.get("done")), None)
                if nxt:
                    nxt["done"] = True; save_json("gems.json", gems)
                self.flash()

        def type_text(self, text):
            if not shutil.which("ydotool"):
                print("[poe] ydotool not found", file=sys.stderr); return
            env = dict(os.environ, YDOTOOL_SOCKET=self.socket)
            try:
                subprocess.run(
                    ["ydotool", "type", "--key-delay", str(cfg.get("key_delay_ms", 6)), "--", text],
                    env=env, check=False)
            except Exception as e:
                print(f"[poe] ydotool failed: {e}", file=sys.stderr)

    app = QtWidgets.QApplication(sys.argv)
    hud = Hud()
    reader = Reader()
    reader.action.connect(hud.on_action)
    reader.error.connect(lambda msg: (print("[poe]", msg, file=sys.stderr),
                                      QtWidgets.QMessageBox.critical(None, "PoE Companion", msg)))
    reader.start()
    print(f"[poe] running. Listening on {path}. HUD on monitor {cfg['monitor']}.")
    hud.flash()   # show once at startup so you know it's alive
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
