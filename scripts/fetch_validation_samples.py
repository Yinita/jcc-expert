#!/usr/bin/env python3
"""Rehydrate curated public fixtures for local evaluation; verify original hashes.

No images are copied into the distributed report. Run explicitly to download
the selected publisher files, respecting their availability and terms.
"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest = args.manifest.resolve()
    failures = []
    for sample in json.loads(manifest.read_text())["samples"]:
        target = (manifest.parent / sample["file"]).resolve()
        if not target.is_relative_to(manifest.parent):
            raise ValueError("Fixture paths must stay within the manifest directory")
        expected = sample["file_sha256"]
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
            print(f"verified {sample['id']}", flush=True)
            continue
        try:
            url = sample["source_image_url"]
            if urlsplit(url).scheme != "https":
                raise ValueError("Only HTTPS publisher images are supported")
            headers = {"User-Agent": "Mozilla/5.0 JCC-local-evaluation/0.2"}
            if sample.get("source_url"):
                headers["Referer"] = sample["source_url"]
            with urlopen(Request(url, headers=headers), timeout=30) as response:
                data = response.read(20 * 1024 * 1024 + 1)
            if len(data) > 20 * 1024 * 1024:
                raise ValueError("Image exceeds 20 MiB")
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError("Publisher bytes changed; keep the frozen labels unchanged and re-curate separately")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".part")
            temporary.write_bytes(data)
            temporary.replace(target)
            print(f"downloaded and verified {sample['id']}", flush=True)
        except Exception as exc:
            failures.append({"id": sample["id"], "error": str(exc)})
            print(f"unavailable {sample['id']}: {exc}", flush=True)
    if failures:
        print(json.dumps({"unavailable": failures}, ensure_ascii=False, indent=2))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
