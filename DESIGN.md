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
  │  right encoder  CW → F14 (next) · CCW → F18 (prev) │
  │  hold RAISE/LOWER + push right knob → F15 (select) │
  │  hold RAISE/LOWER + push left  knob → F16 (gem done)│
  └───────────────────────┬────────────────────────────┘
                          │ HID (USB/BT) — F14/F18 encoder, F15/F16 on knob-push combos
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

## ZMK signal contract (implemented in `wireless-keyboard`)

| Action | Keycode | Gesture (Linux layers) |
|---|---|---|
| prev | `F18` | right encoder CCW (turn left) |
| next | `F14` | right encoder CW (turn right) |
| select | `F15` | hold RAISE **or** LOWER + push right knob |
| gem_done | `F16` | hold RAISE **or** LOWER + push left knob |

The right encoder is dedicated to regex scrolling on the Linux layers (F14/F18 always). Select
and gem-done need a modifier + knob-push, so they never fire during normal typing. These F-keys
are otherwise unused system-wide → zero collision. `zmk/poe-layer.md` is the earlier draft;
the live keymap lives in the `wireless-keyboard` repo.

## Testing ladder (each step verifiable before the next)

1. `python app/poe_selector.py --list-devices` → confirms the Sofle is found.
2. `python app/poe_selector.py --watch` → turn knob, see raw key events (proves evdev read works — will show `VOLUMEUP/DOWN` *before* firmware change).
3. Flash the PoE layer → `--watch` now shows `F18/F14` (knob) and `F15/F16` (knob-push combos).
4. `python app/poe_selector.py` → HUD on portrait screen; knob scrolls; select types into focused field.

## Roadmap

- [x] Static HTML regex library + ZMK macro export
- [x] Standalone git repo
- [x] **Phase 1 — spike:** evdev read + PyQt5 HUD + ydotool type — verified end-to-end (F18/F14/F15/F16)
- [x] Phase 2 — ZMK PoE layer (built in the `wireless-keyboard` repo)
- [x] Regex combo authoring + `regexes.json` export (Regex tab)
- [x] **Gem Planner GUI** — class → quest/vendor gems (Exile Leveling data) → ordered plan → `gems.json` export
- [ ] Phase 3b — in-app data sync (browser download → config dir is manual for now)
- [ ] Phase 4 — polish: systemd --user unit, tray icon, HUD gem-progress panel
- [ ] Stretch — true on-game overlay (gtk-layer-shell), verify regex tiers in-game

## Gem data

`gemdata.js` is generated from Exile Leveling (MIT, © HeartofPhos) by `tools/build_gem_data.py`
from `vendor/exile-leveling/*.json`. 458 gems, 14 quests with offers, 7 classes. Regenerate:
`python tools/build_gem_data.py`.
