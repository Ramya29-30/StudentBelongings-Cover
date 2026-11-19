"""Builds StudentBelongingsCover_Complete.zip from the working tree.
Excludes virtual environments, node_modules, caches, databases/uploads, test outputs and any .env (secrets).
Run from the project root:  python scripts/make_release.py [output.zip]"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "StudentBelongingsCover_Complete.zip"
SKIP_DIRS = {".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".git", "test-results", "playwright-report", "data", ".mypy_cache", ".ruff_cache"}
SKIP_FILES = {"results.json", ".DS_Store", "Thumbs.db"}
SKIP_SUFFIX = {".pyc", ".pyo", ".log", ".zip"}
KEEP_ENV = {".env.example"}

def skip(p: Path) -> bool:
    rel = p.relative_to(ROOT)
    for part in rel.parts[:-1]:
        if part in SKIP_DIRS:
            if part == "data" and rel.parts[:2] == ("backend", "tests"):
                continue  # test fixtures folder is not the runtime data dir
            return True
    n = p.name
    if n in SKIP_FILES or p.suffix in SKIP_SUFFIX:
        return True
    if (n == ".env" or n.startswith(".env.")) and n not in KEEP_ENV:
        return True
    return False

count = 0
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted(ROOT.rglob("*")):
        if p.is_file() and not skip(p):
            z.write(p, Path("StudentBelongingsCover") / p.relative_to(ROOT))
            count += 1
print(f"{OUT} - {count} files, {OUT.stat().st_size/1024:.0f} KB")
