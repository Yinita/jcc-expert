#!/usr/bin/env python3
"""Build the curated static GitHub Pages site; never copy uploads or runtime data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BUNDLES = {
    "guide": {"guide.html": "index.html", "guide.css": "guide.css",
              "guide.js": "guide.js", "guide-data.json": "guide-data.json"},
    "strategy": {"strategy.html": "index.html", "strategy.css": "strategy.css",
                 "strategy.js": "strategy.js", "strategy-data.json": "strategy-data.json"},
}


def build(destination: Path | None = None) -> dict:
    destination = Path(destination or ROOT / "docs").resolve()
    if ROOT.is_relative_to(destination) or destination.is_relative_to(ROOT / "app"):
        raise ValueError("The publication directory cannot replace the repository or application")
    if destination.exists() and any(destination.iterdir()) and not (destination / "build-manifest.json").is_file():
        raise ValueError("Refusing to replace an existing directory not created by this builder")
    static = ROOT / "app" / "static"
    for name in [*(name for files in BUNDLES.values() for name in files), "pages-home.html"]:
        if not (static / name).is_file():
            raise FileNotFoundError(f"Generate the guide first: {static / name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-build-", dir=destination.parent))
    try:
        report = _build_files(staging, static, BUNDLES)
        backup = destination.with_name(f".{destination.name}-previous")
        if backup.exists():
            raise ValueError(f"Previous publication backup exists; inspect it before retrying: {backup}")
        if destination.exists():
            destination.rename(backup)
        try:
            staging.rename(destination)
        except Exception:
            if backup.exists():
                backup.rename(destination)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        return {"output": str(destination), "asset_count": report["asset_count"]}
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _build_files(destination: Path, static: Path, bundles: dict) -> dict:
    revisions = {}
    for bundle, files in bundles.items():
        directory = destination / bundle
        directory.mkdir(parents=True, exist_ok=True)
        for source, target in files.items():
            shutil.copyfile(static / source, directory / target)
        revision = hashlib.sha256(b"".join((directory / name).read_bytes() for name in
                                         (f"{bundle}.css", f"{bundle}.js", f"{bundle}-data.json"))).hexdigest()[:12]
        revisions[bundle] = revision
        html = (directory / "index.html").read_text()
        for name in (f"{bundle}.css", f"{bundle}.js"):
            html = html.replace(f'"./{name}"', f'"./{name}?v={revision}"')
        for sibling in bundles:
            html = html.replace(f'"./{sibling}.html', f'"../{sibling}/')
        (directory / "index.html").write_text(html)
    shutil.copyfile(static / "pages-home.html", destination / "index.html")
    (destination / ".nojekyll").write_text("")
    asset_root = (ROOT / "app" / "assets").resolve()
    manifest = json.loads((asset_root / "manifest.json").read_text())
    copied = []
    for row in manifest["assets"]:
        if row.get("kind") not in {"hero", "item", "card"}:
            continue
        relative = Path(row["path"])
        source = (asset_root / relative).resolve()
        if relative.is_absolute() or not source.is_relative_to(asset_root):
            raise ValueError(f"Invalid asset path: {relative}")
        if not source.is_file():
            raise FileNotFoundError(f"Missing manifest asset: {relative}")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != row["sha256"]:
            raise ValueError(f"Asset hash mismatch: {relative}")
        target = destination / "assets" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied.append({"path": "assets/" + relative.as_posix(), "sha256": digest})
    paths = {row["path"] for row in copied}
    def check_icons(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"icon", "icon_url"} and isinstance(item, str) and item and not item.startswith("https://"):
                    icon = item.lstrip("/").removeprefix("../").removeprefix("assets/")
                    if "assets/" + icon not in paths:
                        raise FileNotFoundError(f"Guide references a missing local icon: {item}")
                else:
                    check_icons(item)
        elif isinstance(value, list):
            for item in value:
                check_icons(item)
    for bundle in bundles:
        check_icons(json.loads((destination / bundle / f"{bundle}-data.json").read_text()))
    report = {"schema_version": 1, "entry": "index.html", "guide": "guide/",
              "strategy": "strategy/", "guide_revision": revisions["guide"],
              "strategy_revision": revisions["strategy"],
              "publication": "GitHub Pages: main /docs",
              "assets": copied, "asset_count": len(copied),
              "excluded": ["uploads", "var", "databases", "access tokens", "source screenshots", "training"]}
    (destination / "build-manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.output), ensure_ascii=False))
