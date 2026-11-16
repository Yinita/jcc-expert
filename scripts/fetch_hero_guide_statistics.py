#!/usr/bin/env python3
"""Fetch a small, attributed snapshot of public hero three-item observations.

Uses exactly the public site's web endpoints and verifies hero ID + name against
its public hero table. No login, private API, or authentication bypass is used.
Only up to three observations with >=100 samples per mapped hero are published.
Full responses stay in the caller's local cache for auditing, outside the site.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parents[1]
ROOT_URL = "https://www.dataj.cc"
_lock = threading.Lock()
_last = 0.0


def fetch(url):
    global _last
    with _lock:
        time.sleep(max(0.0, 1.0 - (time.monotonic() - _last)))
        _last = time.monotonic()
    req = Request(url, headers={"User-Agent": "JCC-Guide-Public-Source-Check/1.0", "Accept": "application/json,text/html"})
    with urlopen(req, timeout=30) as response:
        data = response.read(4_000_001)
        if len(data) > 4_000_000:
            raise ValueError("Response exceeds bounded snapshot limit")
        return data


def parse_hero_table(html):
    strings = []
    for script in re.findall(r"<script[^>]*>(.*?)</script>", html, re.S):
        if not script.startswith("self.__next_f.push("):
            continue
        try:
            value = json.loads(script[len("self.__next_f.push("):-1])
        except (ValueError, TypeError):
            continue
        if len(value) > 1 and isinstance(value[1], str):
            strings.append(value[1])
    combined = "".join(strings)
    marker = '"initialRows":'
    if marker not in combined:
        raise ValueError("No strict-JSON public hero table found")
    rows = json.JSONDecoder().raw_decode(combined.split(marker, 1)[1])[0]
    return {str(row["heroId"]): row for row in rows}


def select_combos(rows, allowed_items, minimum=100):
    selected = []
    for row in rows:
        ids = [str(e["id"]) for e in row.get("equips", [])]
        n = row.get("sampleCount")
        rates = [row.get(k) for k in ("topRate", "top4Rate")]
        place = row.get("avgPlacement")
        if len(ids) != 3 or not set(ids) <= allowed_items or isinstance(n, bool) or not isinstance(n, int) or n < minimum:
            continue
        if any(isinstance(r, bool) or not isinstance(r, (int, float)) or not 0 <= r <= 100 for r in rates):
            continue
        if rates[0] > rates[1] or isinstance(place, bool) or not isinstance(place, (int, float)) or not 1 <= place <= 8:
            continue
        selected.append({"id": str(row["id"]), "item_ids": ids, "sample_count": n,
                         "first_rate": rates[0], "top4_rate": rates[1], "avg_placement": place})
    # Observed first-place rate, restricted to a stated sample floor. No causal
    # interpretation, significance claim, or fabricated confidence is attached.
    selected.sort(key=lambda r: (-r["first_rate"], r["avg_placement"], -r["sample_count"], r["id"]))
    return selected[:3]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=BASE / "app/data/hero_guide_statistics.json")
    p.add_argument("--cache", type=Path, default=BASE / "var/hero-guide-source-cache")
    p.add_argument("--minimum-samples", type=int, default=100)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--retry-unavailable", action="store_true", help="Retry only failed reads from the existing output snapshot")
    args = p.parse_args()
    if args.minimum_samples < 100:
        p.error("A source snapshot must keep the documented >=100 sample floor")
    args.cache.mkdir(parents=True, exist_ok=True)
    previous = json.loads(args.output.read_text()) if args.retry_unavailable and args.output.is_file() else None
    html_path = args.cache / "hero.html"
    if previous and html_path.is_file():
        raw = html_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != previous["source"]["hero_table_sha256"]:
            raise ValueError("Retry cache does not match the verified original hero table")
    else:
        raw = fetch(ROOT_URL + "/hero")
        html_path.write_bytes(raw)
    table = parse_hero_table(raw.decode("utf-8"))
    facts = json.loads((BASE / "app/data/nature_facts.json").read_text())
    allowed = {str(i["id"]) for i in facts["items"]}
    heroes = [h for h in facts["champion_star_form_records"] if h.get("observed_star_level") == 1 and h.get("shows_in_official_gallery")]
    if previous:
        heroes = [h for h in heroes if previous["heroes"].get(str(h["official_id"]), {}).get("status") == "unavailable"]
    as_of = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    source = {"title": "金铲铲大数据 · 英雄三件套公开统计", "url": ROOT_URL + "/hero", "patch": "18.6", "set_id": 18,
              "retrieved_at": as_of, "hero_table_sha256": hashlib.sha256(raw).hexdigest(), "provider": "third_party",
              "method": "Public same-site web endpoints, hero ID and name verified against public table, no login.",
              "rate_unit": "percent_0_100", "population": "站点称高分段；具体队列、段位边界、时间窗、去重及星级混合口径未披露。"}
    def one(hero):
        official_id = str(hero["official_id"])
        provider_id = str(hero["base_form_id"])
        match = table.get(provider_id)
        entry = {"official_hero_id": official_id, "name": hero["name"], "provider_hero_id": provider_id, "combos": []}
        if not match or match.get("name") != hero["name"]:
            return official_id, {**entry, "status": "unmapped", "reason": "公开表的英雄ID与名称未同时对应，未抓取该英雄组合。"}
        url = ROOT_URL + f"/api/web/stats/hero/{provider_id}/three-equip-combos?setId=18&gameVersion=18.6"
        entry["source_url"] = url
        try:
            cache = args.cache / (official_id + "-combos.json")
            data = fetch(url)
            cache.write_bytes(data)
            entry["retrieved_at"] = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
            payload = json.loads(data)
            if payload.get("success") is not True or not isinstance(payload.get("data"), list):
                raise ValueError("Public endpoint returned unsuccessful or unsupported data")
            entry.update(response_sha256=hashlib.sha256(data).hexdigest(), rows_received=len(payload["data"]),
                         combos=select_combos(payload["data"], allowed, args.minimum_samples))
            entry["status"] = "observations" if entry["combos"] else "insufficient_samples"
            if not entry["combos"]:
                entry["reason"] = "没有达到100样本且装备可映射的三件套；不展示低样本高第一率。"
        except Exception as exc:
            entry.update(status="unavailable", reason=f"公开统计本次未能读取：{type(exc).__name__}")
        print(json.dumps({"hero": hero["name"], "status": entry["status"], "published_combos": len(entry["combos"])}, ensure_ascii=False), flush=True)
        return official_id, entry
    records = dict(previous["heroes"]) if previous else {}
    records.update(dict(ThreadPoolExecutor(max_workers=max(1, min(args.workers, 2))).map(one, heroes)))
    output = {"schema_version": "hero-guide-statistics-v1", "source": source, "minimum_sample_count": args.minimum_samples,
              "notice": "第三方18.6历史观察，未独立核验。高第一率可能来自星级、阵容、成型时机与玩家选择，不能证明装备带来因果胜率提升。", "heroes": records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"heroes": len(records), "heroes_with_combos": sum(bool(v["combos"]) for v in records.values()), "published_combos": sum(len(v["combos"]) for v in records.values())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
