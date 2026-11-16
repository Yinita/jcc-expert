#!/usr/bin/env python3
"""Cache official portrait/card assets for the local recognizer.

Default: download 30 portraits as a small, reviewable starter cache.
Use --mode all --kind all --limit 0 to download all assets listed in facts.
This downloads images only; it does not read a running game or require a key.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PIL import Image

OFFICIAL_HOST = "game.gtimg.cn"
MAX_BYTES = 4 * 1024 * 1024
_throttle = threading.Lock()
_last_request = 0.0


def validate_url(url: str) -> str:
    p = urlparse(url)
    if (p.scheme != "https" or p.hostname != OFFICIAL_HOST or p.port not in (None, 443)
            or p.username or p.password or not p.path.startswith("/images/lol/act/jkzlk/")):
        raise ValueError("Only known official HTTPS game assets are allowed")
    return url


class OfficialRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def image_is_valid(raw: bytes) -> bool:
    try:
        with Image.open(BytesIO(raw)) as im:
            if im.width > 8192 or im.height > 8192 or im.width * im.height > 16_000_000:
                return False
            im.verify()
        return True
    except Exception:
        return False


def collect_assets(data_dir: Path, modes=("nature", "orange"), kind="all") -> list[dict]:
    result = []
    for mode in modes:
        filename = "nature_facts.json" if mode == "nature" else "orange_base_facts.json"
        p = data_dir / filename
        if not p.exists():
            continue
        facts = json.loads(p.read_text(encoding="utf-8"))
        if kind in ("all", "hero"):
            for row in facts.get("champion_star_form_records", []):
                if row.get("observed_star_level") != 1 or not row.get("shows_in_official_gallery"):
                    continue
                result.append({"mode": mode, "kind": "hero", "entity_id": str(row["official_id"]),
                               "name": row["name"], "source_url": row.get("icon_url")})
        if kind in ("all", "item"):
            for row in facts.get("items", []):
                if row.get("icon_url"):
                    result.append({"mode": mode, "kind": "item", "entity_id": str(row["id"]),
                                   "name": row["name"], "source_url": row["icon_url"]})
        if kind in ("all", "card"):
            cards = facts.get("time_cards", [])
            if mode == "orange" and not cards:
                p = data_dir / "orange_official_facts.json"
                cards = json.loads(p.read_text(encoding="utf-8")).get("cards", []) if p.exists() else []
            for row in cards:
                result.append({"mode": mode, "kind": "card", "entity_id": str(row["id"]),
                               "name": row.get("name_zh", row.get("name")), "source_url": row.get("icon_url")})
    unique = {}
    for row in result:
        if not row.get("source_url") or not re.fullmatch(r"[A-Za-z0-9_-]+", row["entity_id"]):
            continue
        validate_url(row["source_url"])
        unique[(row["mode"], row["kind"], row["entity_id"])] = row
    return list(unique.values())


def download_assets(data_dir: Path, assets_dir: Path, *, modes=("nature", "orange"), kind="all",
                    limit=30, workers=2, delay=0.15) -> dict:
    assets_dir.mkdir(parents=True, exist_ok=True)
    rows = collect_assets(data_dir, modes, kind)
    if limit:
        rows = rows[:limit]
    manifest_path = assets_dir / "manifest.json"
    old = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    cache = {(r["mode"], r["kind"], r["entity_id"]): r for r in old.get("assets", [])}

    def fetch(row):
        global _last_request
        row = dict(row)
        relative = Path(row["mode"]) / (row["kind"] + "s") / (row["entity_id"] + ".png")
        destination = assets_dir / relative
        try:
            raw = destination.read_bytes() if destination.exists() else b""
            if not raw or len(raw) > MAX_BYTES or not image_is_valid(raw):
                with _throttle:
                    time.sleep(max(0.0, delay - (time.monotonic() - _last_request)))
                    _last_request = time.monotonic()
                req = Request(validate_url(row["source_url"]), headers={"User-Agent": "JCC-Local-Research/0.1"})
                with build_opener(OfficialRedirects).open(req, timeout=20) as response:
                    validate_url(response.geturl())
                    raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES or not image_is_valid(raw):
                    raise ValueError("Response is too large or is not a valid bounded image")
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_suffix(".part")
                temporary.write_bytes(raw)
                temporary.replace(destination)
            row.update(path=relative.as_posix(), sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
            return row, None
        except Exception as exc:
            return None, {"entity_id": row["entity_id"], "mode": row["mode"], "kind": row["kind"],
                          "source_url": row["source_url"], "error": str(exc)[:200]}

    errors = []
    with ThreadPoolExecutor(max_workers=max(1, min(4, workers))) as pool:
        for row, error in pool.map(fetch, rows):
            if row:
                cache[(row["mode"], row["kind"], row["entity_id"])] = row
            if error:
                errors.append(error)
    unresolved = {(r.get("mode"), r.get("kind"), r.get("entity_id")): r for r in old.get("errors", [])}
    for key in cache:
        unresolved.pop(key, None)
    for row in errors:
        unresolved[(row["mode"], row["kind"], row["entity_id"])] = row
    manifest = {"schema_version": 1, "updated_at": datetime.now(timezone.utc).isoformat(),
                "notice": "Official image cache; recognition scores are similarity scores, not calibrated accuracy.",
                "assets": sorted(cache.values(), key=lambda r: (r["mode"], r["kind"], r["entity_id"])),
                "errors": list(unresolved.values())}
    temp = manifest_path.with_suffix(".tmp")
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(manifest_path)
    return {"requested": len(rows), "cached_total": len(cache), "errors": errors}


def main():
    base = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=base / "app/data")
    parser.add_argument("--assets-dir", type=Path, default=base / "app/assets")
    parser.add_argument("--mode", choices=["all", "nature", "orange"], default="all")
    parser.add_argument("--kind", choices=["all", "hero", "card", "item"], default="hero")
    parser.add_argument("--limit", type=int, default=30, help="0 downloads all available records")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--delay", type=float, default=0.15, help="Minimum seconds between network requests")
    args = parser.parse_args()
    result = download_assets(args.data_dir, args.assets_dir, modes=("nature", "orange") if args.mode == "all" else (args.mode,),
                             kind=args.kind, limit=max(0, args.limit), workers=args.workers, delay=max(0.1, args.delay))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
