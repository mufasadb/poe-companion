# PoE Companion — design & roadmap

The single source of truth for how the pieces fit. Decisions here are **locked** unless we revisit them explicitly.

## Goal

While leveling in PoE 1, use the **right encoder on the wireless Sofle** to scroll a list of
search-bar regexes shown on the **portrait monitor**, and click to **type the selected regex**
straight into the game's vendor/stash search box. Plus a progressive gem checklist you can mark
off from the keyboard.

## Locked decisions

| Decision | Choice | Why |
|---|---|---|
| Live in-game part | **Installed local app**, not a web app | Browsers can't read an encoder globally, draw over/near a game, or inject keystrokes |
| HUD location | **Portrait monitor `HDMI-A-1`** (1080×1920 @ 0,0) | Tall/narrow = perfect for a vertical list; never overlaps the game → dodges Wayland game-overlay pain entirely |
| Input path | **evdev**, reading only the Sofle device | Reliable over a focused Proton game; distinguishes the Sofle from other keyboards |
| Typing into PoE | **ydotool** (uinput) | Already running (`ydotoold` on `/run/user/1000/.ydotool_socket`); Proton sees it as a real keyboard |
| GUI toolkit | **PyQt5** | Only Qt binding importable on this machine; run under XWayland (`QT_QPA_PLATFORM=xcb`) so positioning + always-on-top just work |
| Editor | The existing `index.html` tool | Curate regexes there → exports `regexes.json` the app reads |

## Architecture

```
  ┌─────────────── wireless Sofle (ZMK) ───────────────┐
  │  PoE layer (toggle on):                            │
  │    right encoder  CW → F14 (next) · CCW → F13 (prev)│
  │    thumb key      → F15 (select / type)            │
  │    thumb key      → F16 (mark next gem done)        │
  └───────────────────────┬────────────────────────────┘
                          │ HID (USB/BT) — F13..F16 only sent on PoE layer
                          ▼
  ┌──────────────── poe_selector.py (PyQt5) ───────────┐
  │  evdev thread ── reads ONLY the Sofle device       │
  │       │ emits prev/next/select/gem-done            │
  │       ▼                                            │
  │  selection state over regexes.json                 │
  │       │                                            │
  │       ├─▶ HUD window on HDMI-A-1 (list, current     │
  │       │    highlighted ± neighbours; hides on idle) │
  │       └─▶ on select → ydotool types the regex       │
  └────────────────────────────────────────────────────┘
```

## Data (`~/.config/poe-companion/`)

- `config.json` — device path, monitor rect, key map (F13..F16), ydotool socket, timings.
- `regexes.json` — `[{ "label": "...", "rx": "..." }, …]` (order = scroll order).
- `gems.json`  — `[{ "label": "...", "act": "A1", "source": "reward|buy", "done": false }, …]`.

The app writes sensible defaults on first run if these are missing.

## ZMK signal contract

The firmware sends nothing new during normal use (encoder stays **volume** = "home"). Only on the
**PoE layer** does the right encoder emit `F13`/`F14` and the select/gem keys emit `F15`/`F16`.
Those F-keys are otherwise unused system-wide, so there's zero collision. See `zmk/poe-layer.md`.

## Testing ladder (each step verifiable before the next)

1. `python app/poe_selector.py --list-devices` → confirms the Sofle is found.
2. `python app/poe_selector.py --watch` → turn knob, see raw key events (proves evdev read works — will show `VOLUMEUP/DOWN` *before* firmware change).
3. Flash the PoE layer → `--watch` now shows `F13/F14/F15` on that layer.
4. `python app/poe_selector.py` → HUD on portrait screen; knob scrolls; select types into focused field.

## Roadmap

- [x] Static HTML regex library + ZMK macro export
- [x] Standalone git repo
- [ ] **Phase 1 — spike:** evdev read + PyQt5 HUD + ydotool type (this commit; needs `python-evdev` + `input` group)
- [ ] Phase 2 — ZMK PoE layer flashed & verified end-to-end
- [ ] Phase 3 — gem checklist UX (mark-done key, progressive order)
- [ ] Phase 4 — polish: systemd --user unit, tray icon, HTML→`regexes.json` one-click sync
- [ ] Stretch — true on-game overlay (gtk-layer-shell), verify tiers in-game
