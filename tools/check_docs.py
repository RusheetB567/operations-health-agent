"""Check relative Markdown file links in repository documentation."""
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def check():
    failures = []
    files = sorted(ROOT.glob("*.md")) + sorted((ROOT / "docs").rglob("*.md"))
    links = 0
    for source in files:
        for match in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", source.read_text(encoding="utf-8")):
            target = match.group(1).strip().strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or target.startswith("#"):
                continue
            links += 1
            resolved = (source.parent / unquote(parsed.path)).resolve()
            if not resolved.is_relative_to(ROOT) or not resolved.exists():
                failures.append({"file": source.relative_to(ROOT).as_posix(), "target": target})
    print(json.dumps({"documents": len(files), "local_links": links, "broken_links": failures}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(check())
