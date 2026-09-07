#!/usr/bin/env python3
"""IcarusDB icon fetcher — probe multi-candidate File names (from image1 /
comment hints / systematic ITEM_<name> variants) against icarus.wiki.gg,
download 120px thumbs to public/icons/, then patch icon into the board JSONs."""
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

WIKI = "https://icarus.wiki.gg/api.php"
UA = "IcarusDB/1.0 (site: icarus-db.pages.dev; fan database)"
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "src" / "data"
ICON_DIR = ROOT / "public" / "icons"
ICON_DIR.mkdir(parents=True, exist_ok=True)
DELAY = 0.35
BATCH = 50
BOARDS = ["weapons", "food", "creatures"]


def api(params: dict, retries: int = 4) -> dict:
    params = {**params, "format": "json"}
    url = WIKI + "?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            if attempt == retries - 1:
                print(f"  api fail: {e}")
                return {}
            time.sleep(2 * (attempt + 1))


def imageinfo_urls(file_titles: list[str]) -> dict[str, str]:
    """File:<X> -> thumb url (only for existing files). Keys normalized to underscores."""
    urls = {}
    for start in range(0, len(file_titles), BATCH):
        chunk = file_titles[start:start + BATCH]
        d = api({"action": "query", "titles": "|".join(chunk),
                 "prop": "imageinfo", "iiprop": "url", "iiurlwidth": "120"})
        for p in d.get("query", {}).get("pages", {}).values():
            ii = p.get("imageinfo")
            if ii:
                urls[p["title"].replace(" ", "_")] = ii[0].get("thumburl") or ii[0].get("url")
        time.sleep(DELAY)
    return urls


def download(url: str, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 500:
        return True
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        if len(data) < 200:
            return False
        dest.write_bytes(data)
        return True
    except Exception as e:
        print(f"  download fail {dest.name}: {e}")
        return False


def safe_name(slug: str) -> str:
    return slug + ".png"


def main() -> None:
    # collect per-slug candidate file names in priority order
    cand_slugs = []          # list of (slug, [cand,...])
    cand_files = {}          # file name -> list of slugs wanting it
    for board in BOARDS:
        for it in json.load(open(DATA / f"icarus_{board}.json", encoding="utf-8")):
            cands = it.get("images") or []
            slug = it["slug"]
            seen = set()
            ordered = []
            for c in cands:
                if c in seen:
                    continue
                seen.add(c)
                ordered.append(c)
            cand_slugs.append((slug, ordered))
            for c in ordered:
                cand_files.setdefault(c, set()).add(slug)
    all_files = ["File:" + c for c in cand_files]
    print(f"items: {len(cand_slugs)} | candidate files: {len(all_files)}")

    urls = imageinfo_urls(all_files)
    print(f"files existing: {len(urls)}")

    # assign first-hit candidate per slug (priority order preserved)
    hit_slug = {}
    for slug, ordered in cand_slugs:
        for c in ordered:
            f = "File:" + c.replace(" ", "_")
            if f in urls:
                hit_slug[slug] = (f, urls[f])
                break

    print(f"items with icon: {len(hit_slug)}/{len(cand_slugs)}")
    # download
    ok = 0
    for slug in sorted(hit_slug):
        f, url = hit_slug[slug]
        if download(url, ICON_DIR / safe_name(slug)):
            ok += 1
    print(f"downloaded: {ok}")

    # patch JSONs
    for board in BOARDS:
        path = DATA / f"icarus_{board}.json"
        data = json.load(open(path, encoding="utf-8"))
        hit = 0
        for it in data:
            url = hit_slug.get(it["slug"])
            it["icon"] = "/icons/" + safe_name(it["slug"]) if url else ""
            if it["icon"]:
                hit += 1
        json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"{board}: {hit}/{len(data)} icons")


if __name__ == "__main__":
    main()
