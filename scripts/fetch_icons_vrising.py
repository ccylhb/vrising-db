#!/usr/bin/env python3
"""VRisingDB icon fetch: probe candidate File: names (Fandom normalizes spaces)
and download via Fandom standard thumb URL. Datasets: vblood/weapons/armor/consumables."""
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path("C:/Users/梁会斌/Documents/Codex/vrising-db")
CACHE = ROOT / "scripts" / "cache" / "wikitexts.json"
DATA = ROOT / "src" / "data"
ICON_DIR = ROOT / "public" / "icons"
ICON_DIR.mkdir(parents=True, exist_ok=True)
UA = "VRisingDB/1.0 (site: vrising-db.pages.dev; contact franceiwhdbks865@gmail.com)"
API = "https://vrising.fandom.com/api.php"
DL_HOST = "https://static.wikia.nocookie.net/vrising"
DELAY = 0.35
BATCH = 30

def api(p, retries=3):
    url = API + "?" + urllib.parse.urlencode({**p, "format": "json"})
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return json.load(urllib.request.urlopen(req, timeout=30))
        except Exception:
            if i == retries - 1:
                return None
            time.sleep(2 * (i + 1))

def safe_name(t):
    return re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_") + ".png"

def norm_key(t):
    """Fandom normalizes file titles to spaces -> compare with spaces."""
    return re.sub(r"[ _]+", " ", t).strip()

def thumb_url(raw):
    m = re.search(r"images/(?:thumb/)?([0-9a-f]/[0-9a-f]{2}/[^/]+\.[a-z]+)", raw)
    if not m:
        return None
    rel = m.group(1)
    fname = rel.split("/")[-1]
    return f"{DL_HOST}/images/thumb/{rel}/120px-{urllib.parse.quote(fname)}"

def main():
    datasets = ["vblood", "weapons", "armor", "consumables"]
    flat = []
    for ds in datasets:
        d = json.load(open(DATA / f"vrising_{ds}.json", encoding="utf-8"))
        missing = [it for it in d if not it.get("icon")]
        print(f"{ds}: {len(d)} items, {len(missing)} missing")
        flat += [(ds, it) for it in missing]

    # collect all candidate File: names -> probe existence in one pass
    cand_of = {}          # slug -> ordered candidate file names
    probe = set()         # "File:Name" style (Fandom API uses spaces internally)
    for ds, it in flat:
        cands = []
        for c in it.get("images") or []:
            c = c.strip()
            if not c or c.lower().endswith((".gif", ".webp")) or "{" in c:
                continue
            cands.append("File:" + norm_key(c))
        cand_of[it["slug"]] = cands
        probe.update(cands)
    print(f"candidates: {len(probe)} unique files to probe")

    # probe File existence via imageinfo
    plist = sorted(probe)
    exists = set()
    rawmap = {}
    for start in range(0, len(plist), BATCH):
        chunk = plist[start:start + BATCH]
        r = api({"action": "query", "titles": "|".join(chunk),
                 "prop": "imageinfo", "iiprop": "url"})
        if r:
            for pg in r.get("query", {}).get("pages", {}).values():
                ii = pg.get("imageinfo")
                if ii and pg.get("title"):
                    k = norm_key(pg["title"].replace("File:", ""))
                    exists.add(k)
                    rawmap[k] = ii[0].get("url") or ""
        time.sleep(DELAY)
    print(f"existing files: {len(exists)}")

    # first-hit assign per slug
    hit = {}  # slug -> file key
    for slug, cands in cand_of.items():
        for c in cands:
            k = norm_key(c.replace("File:", ""))
            if k in exists:
                hit[slug] = k
                break
    print(f"resolved: {len(hit)}/{len(flat)}")

    # download
    fetched = 0
    for slug, key in hit.items():
        raw = rawmap.get(key, "")
        url = thumb_url(raw) if raw else None
        if not url:
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            b = urllib.request.urlopen(req, timeout=40).read()
            if len(b) > 300:
                (ICON_DIR / safe_name(slug)).write_bytes(b)
                fetched += 1
        except Exception:
            pass
        time.sleep(0.12)
    print(f"downloaded: {fetched}")

    # patch icons back into datasets
    for ds in datasets:
        d = json.load(open(DATA / f"vrising_{ds}.json", encoding="utf-8"))
        patched = 0
        for it in d:
            if it.get("icon"):
                continue
            fname = safe_name(it["slug"])
            if (ICON_DIR / fname).exists():
                it["icon"] = "/icons/" + fname
                patched += 1
        json.dump(d, open(DATA / f"vrising_{ds}.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        have = sum(1 for it in d if it.get("icon"))
        print(f"{ds}: now {have}/{len(d)} (+{patched})")

if __name__ == "__main__":
    main()
