# PoE Leveling Companion

A **Path of Exile (PoE 1)** leveling helper for a Linux / KDE-Wayland desktop with a
wireless Sofle (ZMK) keyboard. Two parts:

1. **`index.html`** — an offline tool to curate search-bar regexes (with copy buttons) and
   export ZMK macros. This is also the *editor* for the app below.
2. **`app/poe_selector.py`** — a background app: scroll the Sofle's right encoder to pick a
   regex from a list shown on your portrait monitor, click to type it into PoE.

See **[DESIGN.md](DESIGN.md)** for the full architecture and roadmap, and
**[zmk/poe-layer.md](zmk/poe-layer.md)** for the firmware edit.

## The HTML tool

- **Search Regex** — a curated, editable library of vendor/stash **search-bar** regex
  (movement boots, life, resists, attributes, weapon mods…), each with one-click copy.
  Edits persist in the browser (`localStorage`).
- **Keyboard Export** — tick the regexes you want on your keyboard and it generates a
  paste-ready [ZMK](https://zmk.dev) `macros { }` block (correct keycodes, including
  shifted symbols like `"` `|` `+`) plus the `&poe_*` references and flash steps.
- **Gems & Notes** — links to [Exile Leveling](https://heartofphos.github.io/exile-leveling)
  for gem/route/swap planning, plus a persistent scratchpad.

## Use

```sh
xdg-open index.html      # or just open the file in any browser
```

## Notes / scope

- Regexes are for PoE's **search bar** (they highlight items) — not loot `.filter` files.
- The starter regex set is sensible defaults, **not verified against live game text** —
  tweak inline as you go; PoE mod strings are finicky.
- Socket-link / socket-color searches are intentionally omitted (PoE's search bar can't
  match those from mod text).

## Keyboard target

Wireless Sofle · nice!nano v2 · ZMK — firmware repo:
[`mufasadb/wireless-keyboard`](https://github.com/mufasadb/wireless-keyboard).
