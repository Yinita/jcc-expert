"""Publication checks for both static tools and the generated-only boundary."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

_path = Path(__file__).resolve().parents[1] / "scripts/build_pages.py"
_spec = importlib.util.spec_from_file_location("pages_builder", _path)
_builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_builder)


class PagesBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.static = self.root / "app/static"
        self.static.mkdir(parents=True)
        asset = self.root / "app/assets/nature/heros/1.png"
        asset.parent.mkdir(parents=True)
        asset.write_bytes(b"fixture-reference-image")
        manifest = {"assets": [{"kind": "hero", "path": "nature/heros/1.png",
                                "sha256": hashlib.sha256(asset.read_bytes()).hexdigest()}]}
        (self.root / "app/assets/manifest.json").write_text(json.dumps(manifest))
        (self.static / "pages-home.html").write_text('<a href="./strategy/">运营</a>')
        for bundle in ("guide", "strategy"):
            sibling = "strategy" if bundle == "guide" else "guide"
            (self.static / f"{bundle}.html").write_text(
                f'<link href="./{bundle}.css"><script src="./{bundle}.js"></script>'
                f'<a href="./{sibling}.html#nature">另一工具</a>')
            (self.static / f"{bundle}.css").write_text("body{color:white}")
            (self.static / f"{bundle}.js").write_text(f'const tool="{bundle}";')
            (self.static / f"{bundle}-data.json").write_text(json.dumps({"icon": "assets/nature/heros/1.png"}))
        (self.root / "var/screenshots").mkdir(parents=True)
        (self.root / "var/screenshots/private.png").write_bytes(b"private upload")
        self.root_patch = patch.object(_builder, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def test_both_tools_have_project_relative_links_and_no_runtime_files(self):
        _builder.build()
        docs = self.root / "docs"
        report = json.loads((docs / "build-manifest.json").read_text())
        for bundle, sibling in (("guide", "strategy"), ("strategy", "guide")):
            html = (docs / bundle / "index.html").read_text()
            self.assertIn(f'"../{sibling}/#nature"', html)
            self.assertIn(f'{bundle}.js?v={report[bundle + "_revision"]}', html)
            self.assertIn(f'{bundle}.css?v={report[bundle + "_revision"]}', html)
            self.assertTrue((docs / bundle / f"{bundle}-data.json").is_file())
        self.assertTrue((docs / "assets/nature/heros/1.png").is_file())
        self.assertFalse((docs / "var").exists())
        self.assertFalse(any(p.name == "private.png" for p in docs.rglob("*")))

    def test_missing_input_or_icon_keeps_previous_publication(self):
        _builder.build()
        home = self.root / "docs/index.html"
        previous = home.read_bytes()
        missing = self.static / "strategy.js"
        missing.unlink()
        with self.assertRaises(FileNotFoundError):
            _builder.build()
        self.assertEqual(home.read_bytes(), previous)
        missing.write_text("// restored")
        (self.static / "strategy-data.json").write_text('{"icon":"assets/missing.png"}')
        with self.assertRaises(FileNotFoundError):
            _builder.build()
        self.assertEqual(home.read_bytes(), previous)

    def test_rebuild_removes_stale_output_and_rejects_source_directories(self):
        _builder.build()
        stale = self.root / "docs/old-page.html"
        stale.write_text("obsolete")
        _builder.build()
        self.assertFalse(stale.exists())
        for unsafe in (self.root, self.root.parent, self.root / "app", self.static):
            with self.subTest(path=unsafe), self.assertRaises(ValueError):
                _builder.build(unsafe)
