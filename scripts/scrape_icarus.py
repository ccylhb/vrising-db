#!/usr/bin/env python3
"""Scrape ICARUS wiki (icarus.wiki.gg) into category databases.

Boards (v1): weapons (Category:Weapons), food (Category:Food), creatures (Category:Creatures).
Every page keeps its raw wikitext in cache/wikitexts.json for later board expansion.
Infobox families parsed:
  weapons -> Tool / Weapon Infobox Template / ItemData(Firearms) display blocks
  food    -> Consumables
  creatures-> Creature_infobox / Lifeform / CreatureMulti_infobox
ItemData data-layer fields (Itemable_*/Durable_*/GameplayTags) merged as a base layer.
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
UA = "IcarusDB/1.0 (site: icarus-db.pages.dev; fan database)"
API = "https://icarus.wiki.gg/api.php"
DELAY = 0.4

BOARDS = {
    "weapons": "Category:Weapons",
    "food": "Category:Food",
    "creatures": "Category:Creatures",
}

DISPLAY_BY_BOARD = {
    "weapons": ["Tool", "Weapon Infobox Template", "ItemData/Firearms"],
    "food": ["Consumables"],
    "creatures": ["Creature_infobox", "Creature infobox", "Lifeform", "CreatureMulti_infobox"],
}
ALL_DISPLAY = sorted({t for ts in DISPLAY_BY_BOARD.values() for t in ts})

IMG_TMPL_KEYS = ("image1", "image", "icon")


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
    pat = "{{" + tpl
    start = text.find(pat)
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
            j = text.find("]]", i)
            if j < 0:
                cur.append(text[i:])
                break
            cur.append(text[i:j + 2])
            i = j + 2
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
    # drop template name (up to first top-level pipe or newline-ish '}}' not needed)
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
    s = re.sub(r"\{\{\s*[Ii]tem icon\s*\|\s*([^}|]+)[^}]*\}\}", r"\1", s)  # {{Item icon|X}} -> X
    s = re.sub(r"\[\[(?:File|Image):[^\]]*\]\]", "", s)
    s = re.sub(r"\[\[([^\]|]*)\|([^\]]*)\]\]", r"\2", s)
    s = re.sub(r"\[\[([^\]]*)\]\]", r"\1", s)
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


def split_br(s):
    if not s:
        return []
    return [clean(p) for p in re.split(r"<br\s*/?>", s, flags=re.I) if clean(p)]


def split_slash_multi(s):
    if not s:
        return []
    return [float(x) for x in re.split(r"\s*/\s*", str(s)) if re.search(r"\d", x)]


def find_intro(wt):
    """First paragraph(s) of the prose body (after lead templates / section headers)."""
    txt = strip_comments(wt)
    # drop every leading {{...}} block until prose or a section header shows up
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
    # parts[0] = text before first header (often empty); take the next non-empty one
    for part in parts[1:]:
        lines = [clean(l) for l in part.split("\n")
                 if clean(l) and not l.strip().startswith("|")
                 and not l.strip().startswith("{{") and not l.strip().startswith("[[")
                 and "==" not in l and "{|" not in l]
        if lines:
            return " ".join(lines)[:600]
    return ""


# ---------------- extraction helpers ----------------

def extract_itemdata(wt):
    """Merge fields from the ItemData / ItemData/Firearms data-layer block(s)."""
    out = {}
    for blk in (match_infobox(wt, "ItemData"), match_infobox(wt, "ItemData/Firearms")):
        if not blk:
            continue
        p = parse_params(blk)
        for k, v in p.items():
            if k.startswith(("itemable_", "durable_")) or k in (
                    "gameplaytags", "additionalstats", "categories", "craftedat",
                    "techlevelunlock", "techlevelneeded", "prerequisite"):
                out[k] = clean(v)
    return out


def extract_display(wt, tpls):
    """Return params of the first display block that actually exists."""
    for tpl in tpls:
        blk = match_infobox(wt, tpl)
        if blk:
            return parse_params(blk), tpl
    return {}, ""


def comment_file_hints(wt):
    """Real icon filenames are often left in <!-- ITEM_X.png --> comments."""
    hints = re.findall(r"<!--\s*([A-Za-z0-9_ ./-]+\.(?:png|webp|jpg|jpeg|gif))\s*-->", wt)
    return [h for h in hints if "_" in h or h.lower().startswith(("item_", "t_item_", "cre_", "t_bestiary_"))]


def image_candidates(wt, title, itemable_name):
    """Ordered candidate icon file names (real name wins over template default)."""
    cands = []
    # 1) display-block image1/image/icon values (usually hand-filled real files)
    for tpl in ALL_DISPLAY:
        blk = match_infobox(wt, tpl)
        if blk:
            for k in IMG_TMPL_KEYS:
                v = parse_params(blk).get(k)
                if v:
                    cands.append(v.replace("{{PAGENAME}}", title).strip())
    # 2) filenames hidden in comments (authoritative)
    cands += comment_file_hints(wt)
    # 3) systematic title/itemable-name variants
    for base in (itemable_name or "", title):
        b = re.sub(r"\s+", "_", base)
        if b:
            for pre in ("ITEM_", "T_ITEM_", "CRE_", "T_Bestiary_"):
                cands.append(pre + b + ".png")
    # normalize: strip wiki markup noise, dedupe, drop empties
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


# ---------------- board parsers ----------------

def scrape_weapons(titles, wts):
    out = []
    for t in titles:
        wt = wts.get(t, "")
        if not wt:
            continue
        p, itype = extract_display(wt, DISPLAY_BY_BOARD["weapons"])
        itemd = extract_itemdata(wt)
        if not p and not itemd:
            continue  # category index / prose page, no data
        stats = {}
        for k in ("melee_dmg", "melee_damage", "rangeDMG", "range_dmg", "dmg_var",
                  "dmg_type", "damage_type", "mining_rad", "miningeff", "swing_rate",
                  "fire_rate", "attack_speed", "rpm", "roundsperminute", "reloadtime",
                  "reload_speed", "launchforce", "hipaccuracyx", "hipaccuracyy",
                  "aimaccuracyx", "aimaccuracyy", "staminachargecost", "ammo_capacity",
                  "crit_damage", "crit_hit", "block", "parry", "backstab", "attributes",
                  "category", "techlvl", "tech", "xp", "level", "durability",
                  "element", "damage", "yield", "repair", "bench"):
            if p.get(k):
                stats[k] = clean(p[k])
        out.append({
            "title": t, "slug": slug(t), "category": "Weapons",
            "infobox": itype, "images": image_candidates(wt, t, itemd.get("itemable_name", "")),
            "intro": find_intro(wt),
            "itemable_name": itemd.get("itemable_name", ""),
            "flavor": itemd.get("itemable_flavortext", ""),
            "description": (clean(p.get("description", "")) or
                            itemd.get("itemable_description", "")),
            "tags": [x.strip() for x in itemd.get("gameplaytags", "").split(",") if x.strip()],
            "durability": num(p.get("durability")) or num(itemd.get("durable_maxdurability")),
            "weight": clean(p.get("weight", "")) or itemd.get("itemable_weight", ""),
            "bench": clean(p.get("bench", "")),
            "repair": clean(p.get("repair", "")) or itemd.get("itemsforrepair", ""),
            "stats": stats,
            "weapon_type": (clean(p.get("category", "")) or
                            next((x for x in itemd.get("categories", "").split(",") if x.strip()), "")),
        })
    return out


def scrape_food(titles, wts):
    out = []
    for t in titles:
        wt = wts.get(t, "")
        if not wt:
            continue
        p, itype = extract_display(wt, DISPLAY_BY_BOARD["food"])
        itemd = extract_itemdata(wt)
        if not p and not itemd:
            continue
        out.append({
            "title": t, "slug": slug(t), "category": "Food",
            "infobox": itype, "images": image_candidates(wt, t, itemd.get("itemable_name", "")),
            "intro": find_intro(wt),
            "itemable_name": itemd.get("itemable_name", ""),
            "flavor": itemd.get("itemable_flavortext", ""),
            "description": (clean(p.get("description", "")) or
                            itemd.get("itemable_description", "")),
            "tags": [x.strip() for x in itemd.get("gameplaytags", "").split(",") if x.strip()],
            "duration": clean(p.get("duration", "")),
            "decay": clean(p.get("decay", "")),
            "stack": clean(p.get("stack", "")) or itemd.get("itemable_maxstack", ""),
            "weight": clean(p.get("weight", "")) or itemd.get("itemable_weight", ""),
            "bench": clean(p.get("bench", "")),
            "buffs": split_br(p.get("attributes", "")),
        })
    return out


def scrape_creatures(titles, wts):
    out = []
    for t in titles:
        wt = wts.get(t, "")
        if not wt:
            continue
        p, itype = extract_display(wt, DISPLAY_BY_BOARD["creatures"])
        if not p:
            continue
        lv = p.get("stat_levels", "")
        entry = {
            "title": t, "slug": slug(t), "category": "Creatures",
            "infobox": itype, "images": image_candidates(wt, t, ""),
            "intro": find_intro(wt),
            "tameable": clean(p.get("tameable", "")),
            "behavior": clean(p.get("behavior", "")),
            "diet": clean(p.get("diet", "")),
            "map": clean(p.get("map", "")),
            "atmosphere": clean(p.get("atmosphere", "")),
            "biome": clean(p.get("biome", "")) or clean(p.get("location", "")),
            "levels": [clean(x) for x in lv.split("/") if x.strip()] or None,
            "health": split_slash_multi(p.get("health", "")),
            "damage": split_slash_multi(p.get("damage", "")),
            "speed_run": num(p.get("speed_run")),
            "speed_sprint": num(p.get("speed_sprint")),
            "resource": clean(p.get("resource", "")),
            "origin": clean(p.get("origin", "")),
        }
        for k in ("xp", "penalty", "weakness", "resistance", "drops"):
            if p.get(k):
                entry[k] = clean(p[k])
        out.append(entry)
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

    parsers = {"weapons": scrape_weapons, "food": scrape_food, "creatures": scrape_creatures}
    for board in BOARDS:
        items = parsers[board](board_titles[board], cache)
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / f"icarus_{board}.json").write_text(
            json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[out] {board}: {len(items)} items -> src/data/icarus_{board}.json")


if __name__ == "__main__":
    main()
