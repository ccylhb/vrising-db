#!/usr/bin/env python3
"""Scrape V Rising wiki (vrising.fandom.com) into category databases.

Boards (v1): vblood (Category:V Blood Carriers), weapons (Category:Weapons),
             armor (Category:Armours), consumables (Category:Consumables).
Every page keeps its raw wikitext in cache/wikitexts.json for later expansion.
Infobox families parsed:
  vblood      -> Boss Infobox (level/location/unlock + ==Loot== drop rates + ==Attacks==)
  weapons     -> WeaponInfobox (weapon_type/gear_level/physical_power/stats)
  armor       -> EquipmentInfobox (gear_level/stats/set_bonus; image=<gallery> possible)
  consumables -> ItemInfobox (category/type/stack_size/description)
Pages tagged [[Category:Removed]] are dropped (Update 1.0 removed old armour tiers).
"""
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "src" / "data"
CACHE = Path(__file__).resolve().parent / "cache"
CACHE.mkdir(parents=True, exist_ok=True)
WT_CACHE = CACHE / "wikitexts.json"
META_CACHE = CACHE / "board_titles.json"
UA = "VRisingDB/1.0 (site: vrising-db.pages.dev; fan database)"
API = "https://vrising.fandom.com/api.php"
DELAY = 0.4

BOARDS = {
    "vblood": "Category:V Blood Carriers",
    "weapons": "Category:Weapons",
    "armor": "Category:Armours",
    "consumables": "Category:Consumables",
}

# template names whose presence marks a "real data page" for each board
KEEP_BY_BOARD = {
    "vblood": ["Boss Infobox"],
    "weapons": ["WeaponInfobox"],
    "armor": ["EquipmentInfobox"],
    "consumables": ["ItemInfobox"],
}
ALL_KEEP = sorted({t for ts in KEEP_BY_BOARD.values() for t in ts})
IMG_TMPL_KEYS = ("image", "icon")


def api(p, tries=4):
    url = API + "?" + urllib.parse.urlencode({**p, "format": "json"})
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return json.load(urllib.request.urlopen(req, timeout=30))
        except Exception as e:
            if i == tries - 1:
                return {"_err": str(e)[:80]}
            time.sleep(1.5 * (i + 1))


def cat_members(cat):
    out, cont = [], {}
    while True:
        r = api({"action": "query", "list": "categorymembers", "cmtitle": cat,
                 "cmtype": "page", "cmnamespace": "0", "cmlimit": "500", **cont})
        out += [m["title"] for m in r.get("query", {}).get("categorymembers", [])]
        cont = r.get("continue") or {}
        if not cont:
            break
        time.sleep(DELAY)
    return out


def fetch_wikitexts(titles):
    out = {}
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        r = api({"action": "query", "prop": "revisions", "rvprop": "content",
                 "rvslots": "main", "titles": "|".join(chunk)})
        for pg in r.get("query", {}).get("pages", {}).values():
            t = pg.get("title", "?")
            rev = pg.get("revisions") or []
            txt = ""
            if rev:
                txt = (rev[0].get("slots", {}).get("main", {}) or {}).get("*", "")
            out[t] = txt
        time.sleep(DELAY)
    return out


def strip_comments(s):
    return re.sub(r"<!--.*?-->", "", s, flags=re.S)


def match_infobox(text, tpl):
    # template name may use spaces OR underscores interchangeably ({{Boss Infobox}}
    # and {{Boss_Infobox}} both occur) -> build a flexible search pattern.
    # tpl contains only letters/spaces/underscores/slashes -> safe as raw regex.
    pat = "{{" + re.sub(r"[ _]+", "[ _]", tpl)
    m = re.search(pat, text)
    if not m:
        return None
    start = m.start()
    if start < 0:
        return None
    i = text.find("{", start)
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    return None


def split_param_lines(text):
    """Split a template body into key lines at top-level pipes,
    ignoring pipes inside {{...}} templates and [[...]] links."""
    lines, cur, i, n = [], [], 0, len(text)
    depth = 0
    while i < n:
        if text.startswith("{{", i):
            depth += 1
            cur.append("{{")
            i += 2
            continue
        if text.startswith("}}", i):
            depth = max(0, depth - 1)
            cur.append("}}")
            i += 2
            continue
        if text[i] == "[":
            if text.startswith("[[", i):
                j = text.find("]]", i)
                if j < 0:
                    cur.append(text[i:])
                    break
                cur.append(text[i:j + 2])
                i = j + 2
                continue
            # single [ = external link [url label] -> scan to its closing ]
            j = text.find("]", i)
            if j < 0:
                cur.append(text[i:])
                break
            cur.append(text[i:j + 1])
            i = j + 1
            continue
        if text[i] == "|" and depth == 0:
            lines.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(text[i])
        i += 1
    lines.append("".join(cur))
    return [ln.strip() for ln in lines if ln.strip()]


def parse_params(block):
    """Parse {{tpl ...}} block into {key: value} via top-level-pipe splitting."""
    body = block[2:]  # cut '{{'
    body = re.sub(r"^[A-Za-z0-9 /_-]+", "", body, count=1)
    body = body.rstrip()
    if body.endswith("}}"):
        body = body[:-2]
    params = {}
    cur_key, cur_val = None, []
    for ln in split_param_lines(body):
        if "=" in ln:
            k, _, v = ln.partition("=")
            k = k.strip().lower()
            if cur_key and cur_key not in params:
                params[cur_key] = "\n".join(cur_val).strip()
            cur_key, cur_val = k, [v.strip()]
        elif cur_key is not None:
            cur_val.append(ln.strip())
    if cur_key and cur_key not in params:
        params[cur_key] = "\n".join(cur_val).strip()
    return params


def clean(s):
    if not s:
        return ""
    s = strip_comments(s)
    # item-frame / ability / plain link templates -> first plain arg
    s = re.sub(r"\{\{\s*[Ii]temFrame\s*\|\s*([^|}]+)(?:\|[^}]*)?\}\}", r"\1", s)
    s = re.sub(r"\{\{\s*[Aa]bility\s*\|\s*([^|}]+)[^}]*\}\}", r"\1", s)
    s = re.sub(r"\{\{\s*[Pp]AGENAME\s*\}\}", "VRISINGPAGE", s)
    s = re.sub(r"\{\{\s*[Ii]tem icon\s*\|\s*([^}|]+)[^}]*\}\}", r"\1", s)  # {{Item icon|X}} -> X
    s = re.sub(r"\[\[(?:File|Image):[^\]]*\]\]", "", s)
    s = re.sub(r"\[\[([^\]|]*)\|([^\]]*)\]\]", r"\2", s)
    s = re.sub(r"\[\[([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\[https?://[^\s\]]+\s+([^\]]+)\]", r"\1", s)   # external [url Label] -> Label
    s = re.sub(r"\[https?://[^\s\]]*\]", "", s)
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    i = s.find("{{")
    if i >= 0:
        s = s[:i]  # drop any mangled leftover template
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("'''", "").replace("''", "").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", s).strip()


def num(s):
    m = re.search(r"-?\d+(?:\.\d+)?", str(s or ""))
    return float(m.group(0)) if m else None


def slug(t):
    s = re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-").lower()
    return s or "item"


def find_intro(wt):
    """First paragraph(s) of the prose body (after lead templates / section headers)."""
    txt = strip_comments(wt)
    while True:
        m = re.search(r"\{\{", txt)
        if not m or txt[:m.start()].strip():
            break
        i = m.start()
        depth = 0
        for j in range(i, len(txt)):
            if txt[j] == "{":
                depth += 1
            elif txt[j] == "}":
                depth -= 1
                if depth == 0:
                    txt = txt[:i] + txt[j + 1:]
                    break
        else:
            break
    parts = re.split(r"^={2,}", txt, flags=re.M)
    for part in parts[1:]:
        lines = [clean(l) for l in part.split("\n")
                 if clean(l) and not l.strip().startswith("|")
                 and not l.strip().startswith("{{") and not l.strip().startswith("[[")
                 and "==" not in l and "{|" not in l]
        if lines:
            return " ".join(lines)[:600]
    return ""


def find_section(wt, name):
    """Return raw section body between ==name== (any depth) and the next heading."""
    m = re.search(r"^=+\s*" + re.escape(name) + r"\s*=+\s*(.*?)(?=^=+\s*\S|\Z)",
                  wt, flags=re.M | re.S)
    return m.group(1).strip() if m else ""


# ---------------- extraction helpers ----------------

def page_is_removed(wt):
    return bool(re.search(r"\[\[\s*Category\s*:\s*Removed\s*\]\]", wt))


def extract_image_candidates(wt, title):
    """Ordered candidate icon file names from infobox image fields + gallery."""
    cands = []
    for tpl in ALL_KEEP:
        blk = match_infobox(wt, tpl)
        if not blk:
            continue
        p = parse_params(blk)
        for k in IMG_TMPL_KEYS:
            v = p.get(k, "")
            if not v:
                continue
            v = v.replace("{{PAGENAME}}", title)
            if "<gallery>" in v:
                # gallery rows: 'Armour X.png|Chest' or 'File:X.png|Label'
                for row in re.findall(r"^\s*(?:File|Image):?\s*([^|\n]*\.(?:png|jpg|jpeg|webp))",
                                      v, flags=re.M | re.I):
                    cands.append(row.strip())
            else:
                m = re.search(r"(?:File|Image):\s*([^\n|]+)", v)
                cands.append(m.group(1).strip() if m else v.strip())
    # systematic title variants: V Rising uses 'Weapon <CamelCase>.png' for weapons
    # and 'Armour <X>.png' for equipment; keep the plain title too as a fallback.
    base = re.sub(r"\s+", "", title)
    camel = re.sub(r"[\s/]+", "", re.sub(r"\b\w", lambda m: m.group(0).upper(), title))
    for pre in ("Weapon ", "Item ", "Armour ", ""):
        cands.append(pre + camel + ".png")
    cands.append(base + ".png")
    # dedupe, drop empties / wiki markup
    out, seen = [], set()
    for c in cands:
        c = c.strip()
        if not c or "{{" in c or "}}" in c or c.lower().startswith("file:"):
            continue
        if c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def parse_loot(wt):
    """==Loot== / ==Rewards== section: * {{ItemFrame|Name|amount}} (chance%) -> list."""
    sec = find_section(wt, "Loot")
    if not sec:
        sec = find_section(wt, "Rewards")
    out = []
    if sec:
        for ln in sec.split("\n"):
            mm = re.search(r"\{\{[Ii]temFrame\|([^}]*?)\}\}", ln)
            if not mm or "ItemFrame" not in ln:
                continue
            parts = [x.strip() for x in mm.group(1).split("|")]
            name = parts[0] if parts else ""
            amount = None
            if len(parts) > 1 and parts[1].isdigit():
                amount = int(parts[1])
            cm = re.search(r"\((?:\s*'''?\s*)?([0-9.]+%?)", ln)
            out.append({"name": name, "amount": amount,
                        "chance": cm.group(1) if cm else "100%"})
    return out


def parse_attacks(wt):
    """==Attacks== section: * '''Name''' - description  -> list of (name, desc)."""
    sec = find_section(wt, "Attacks")
    out = []
    if sec:
        for ln in sec.split("\n"):
            m = re.match(r"^\s*\*+\s*'''([^']+)'''\s*(?:-\s*)?(.*)$", ln)
            if m:
                d = clean(m.group(2))
                if m.group(1).strip() and d:
                    out.append({"name": m.group(1).strip(), "desc": d})
    return out


# ---------------- board parsers ----------------

def scrape_vblood(titles, wts):
    out = []
    for t in titles:
        wt = wts.get(t, "")
        if not wt:
            continue
        blk = match_infobox(wt, "Boss Infobox")
        if not blk:
            continue  # index / redirect / prose page
        p = parse_params(blk)
        location = clean(p.get("location", ""))
        loc = re.sub(r"^Region of ", "", location)
        out.append({
            "title": t, "slug": slug(t), "category": "V Blood",
            "infobox": "Boss Infobox",
            "images": extract_image_candidates(wt, t),
            "intro": find_intro(wt),
            "level": num(p.get("level")),
            "unit_id": clean(p.get("unit_id", "")),
            "unlock": clean(p.get("unlocked_vampirepowers", "")),
            "location": loc,
            "description": clean(p.get("description", "")),
            "loot": parse_loot(wt),
            "attacks": parse_attacks(wt),
            "brutal": bool(find_section(wt, "Brutal Difficulty")),
        })
    return out


def scrape_weapons(titles, wts):
    out = []
    for t in titles:
        wt = wts.get(t, "")
        if not wt:
            continue
        blk = match_infobox(wt, "WeaponInfobox")
        if not blk:
            continue
        p = parse_params(blk)
        out.append({
            "title": t, "slug": slug(t), "category": "Weapons",
            "infobox": "WeaponInfobox",
            "images": extract_image_candidates(wt, t),
            "intro": find_intro(wt),
            "description": clean(p.get("description", "")),
            "weapon_type": clean(p.get("weapon_type", "")),
            "gear_level": num(p.get("gear_level")),
            "physical_power": num(p.get("physical_power")),
            "stats": clean(p.get("stats", "")),
            "durability": num(p.get("durability")),
            "salvageable": clean(p.get("salvageable", "")),
            "tags": [x.strip() for x in re.split(r"\s*,\s*|\s+", p.get("weapon_type", "")) if x.strip()],
        })
    return out


def scrape_armor(titles, wts):
    out = []
    for t in titles:
        wt = wts.get(t, "")
        if not wt:
            continue
        if page_is_removed(wt):
            continue  # Update 1.0 removed old tiers; skip obsolete pages
        blk = match_infobox(wt, "EquipmentInfobox")
        if not blk:
            continue
        p = parse_params(blk)
        img = p.get("image", "")
        out.append({
            "title": t, "slug": slug(t), "category": "Armour",
            "infobox": "EquipmentInfobox",
            "images": extract_image_candidates(wt, t),
            "intro": find_intro(wt),
            "gear_level": num(p.get("gear_level")),
            "stats": clean(p.get("stats", "")),
            "set_bonus": clean(p.get("set_bonus", "")),
            "durability": num(p.get("durability")),
            "salvageable": clean(p.get("salvageable", "")),
            "is_set": bool(re.search(r"Set\b", t)) or "<gallery>" in img,
        })
    return out


def scrape_consumables(titles, wts):
    out = []
    for t in titles:
        wt = wts.get(t, "")
        if not wt:
            continue
        if page_is_removed(wt):
            continue
        blk = match_infobox(wt, "ItemInfobox")
        if not blk:
            continue
        p = parse_params(blk)
        out.append({
            "title": t, "slug": slug(t), "category": "Consumable",
            "infobox": "ItemInfobox",
            "images": extract_image_candidates(wt, t),
            "intro": find_intro(wt),
            "item_type": clean(p.get("category", "")) or clean(p.get("type", "")),
            "description": clean(p.get("description", "")),
            "stack_size": num(p.get("stack_size")),
            "teleportable": clean(p.get("teleportable", "")),
            "salvageable": clean(p.get("salvageable", "")),
            "tags": [x.strip() for x in
                     re.split(r"\s*,\s*", p.get("category2", "") or "") if x.strip()],
        })
    return out


def main():
    board_titles = {}
    all_titles = set()
    for board, cat in BOARDS.items():
        titles = cat_members(cat)
        board_titles[board] = titles
        all_titles.update(titles)
        print(f"[board] {board}: {len(titles)} titles")
    META_CACHE.write_text(json.dumps(board_titles, ensure_ascii=False, indent=1), encoding="utf-8")

    cache = {}
    if WT_CACHE.exists():
        cache = json.loads(WT_CACHE.read_text(encoding="utf-8"))
    fresh = sorted(t for t in all_titles if t not in cache)
    print(f"[fetch] {len(fresh)} pages to fetch ({len(cache)} cached)")
    for i in range(0, len(fresh), 50):
        chunk = fresh[i:i + 50]
        cache.update(fetch_wikitexts(chunk))
        WT_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        print(f"  ...{min(i + 50, len(fresh))}/{len(fresh)}")

    parsers = {"vblood": scrape_vblood, "weapons": scrape_weapons,
               "armor": scrape_armor, "consumables": scrape_consumables}
    for board in BOARDS:
        items = parsers[board](board_titles[board], cache)
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / f"vrising_{board}.json").write_text(
            json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[out] {board}: {len(items)} items -> src/data/vrising_{board}.json")


if __name__ == "__main__":
    main()
