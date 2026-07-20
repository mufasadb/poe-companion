#!/usr/bin/env python3
"""
Transform Exile Leveling's data (MIT, (c) HeartofPhos) into a compact bundle the
web GUI loads via <script src="gemdata.js">. Keeps only what the gem planner needs.

    python tools/build_gem_data.py   # writes ./gemdata.js
"""
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "vendor" / "exile-leveling"

gems = json.loads((SRC / "gems.json").read_text())
quests = json.loads((SRC / "quests.json").read_text())
chars = json.loads((SRC / "characters.json").read_text())

COLOR = {"strength": "red", "dexterity": "green", "intelligence": "blue", "none": "white"}

def q_sort_key(qid, act):
    m = re.match(r"a(\d+)q(\d+)([a-z]*)", qid)
    if m:
        return (int(m.group(1)), int(m.group(2)), m.group(3))
    return (int(act or 99), 99, qid)

# --- gems: only those referenced by a quest/vendor offer ---
referenced = set()
out_quests = []
for qid, q in quests.items():
    offers = []
    for oid, off in (q.get("reward_offers") or {}).items():
        rewards, vendors = [], []
        for gid, meta in (off.get("quest") or {}).items():
            if gid in gems:
                referenced.add(gid)
                rewards.append([gid, meta.get("classes", [])])
        for gid, meta in (off.get("vendor") or {}).items():
            if gid in gems:
                referenced.add(gid)
                vendors.append([gid, meta.get("classes", []), meta.get("npc", "")])
        if rewards or vendors:
            offers.append({"npc": off.get("quest_npc", ""), "r": rewards, "v": vendors})
    if offers:
        out_quests.append({
            "id": qid, "act": q.get("act", ""), "name": q.get("name", qid),
            "offers": offers,
        })

# The upstream dict order IS the campaign progression order — preserve it.
# (Do NOT sort by quest id: a1q2 "The Caged Brute" comes long after a1q5 "Mercy Mission".)

out_gems = {}
for gid in referenced:
    g = gems[gid]
    out_gems[gid] = {
        "n": g["name"],
        "c": COLOR.get(g.get("primary_attribute", "none"), "white"),
        "l": g.get("required_level", 1),
        "s": bool(g.get("is_support")),
    }

data = {
    "classes": list(chars.keys()),
    "gems": out_gems,
    "quests": out_quests,
}

banner = ("// Gem/quest data derived from Exile Leveling (https://github.com/heartofphos/exile-leveling)\n"
          "// MIT License, Copyright (c) 2025 HeartofPhos. Regenerate with tools/build_gem_data.py\n")
out = ROOT / "gemdata.js"
out.write_text(banner + "window.POE_DATA = " + json.dumps(data, separators=(",", ":")) + ";\n")
print(f"wrote {out}  ({out.stat().st_size} bytes)")
print(f"  classes={len(data['classes'])} gems={len(out_gems)} quests={len(out_quests)}")
