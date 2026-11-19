"""Keeps launch and design rules enforceable: they fail the build if someone reintroduces a risky pattern."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "frontend-react" / "src"
DASH = re.compile("[\u2014\u2013]|&mdash;|&ndash;")
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50]")


def _src(suffixes=(".tsx", ".ts", ".css", ".html")):
    return [p for p in list(SRC.rglob("*")) + [ROOT / "frontend-react" / "index.html"] if p.is_file() and p.suffix in suffixes]


def test_no_unsafe_dom_or_browser_storage_in_frontend():
    bad = ("dangerouslySetInnerHTML", "innerHTML", "outerHTML", "document.write", "eval(", "new Function", "localStorage", "sessionStorage")
    hits = [f"{p.name}: {b}" for p in _src() for b in bad if b in p.read_text(encoding="utf8")]
    assert hits == []


def test_design_rules_no_dashes_emoji_gradients_or_pill_shapes():
    hits = []
    for p in _src():
        t = p.read_text(encoding="utf8")
        if DASH.search(t): hits.append(f"{p.name}: em/en dash")
        if EMOJI.search(t): hits.append(f"{p.name}: emoji")
        if p.suffix == ".css" and re.search(r"gradient|border-radius:\s*(999|9999|50%)", t): hits.append(f"{p.name}: gradient or pill radius")
    assert hits == []


def test_no_env_files_or_source_maps_or_legacy_ui_ship():
    assert not [p for p in ROOT.rglob(".env*") if p.name != ".env.example" and "node_modules" not in p.parts and ".venv" not in p.parts]
    assert not list((ROOT / "frontend" / "dist").rglob("*.map"))
    assert not (ROOT / "frontend-legacy").exists()


def test_built_bundle_contains_no_secret_shaped_strings():
    for p in (ROOT / "frontend" / "dist").rglob("*.js"):
        t = p.read_text(encoding="utf8", errors="ignore")
        assert not re.search(r"sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|BEGIN (RSA|EC|PRIVATE)", t)


def test_favicon_is_not_the_vite_default_and_is_declared():
    html = (ROOT / "frontend" / "dist" / "index.html").read_text()
    assert 'rel="icon"' in html and "vite.svg" not in html
    assert (ROOT / "frontend" / "dist" / "favicon.ico").stat().st_size > 0
