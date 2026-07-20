"""
Check source consistency that is easy to miss during content edits.

Usage:
    uv run python tools/check_consistency.py
"""

import re
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
THEME_DIR = ROOT / "static" / "css" / "themes"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def css_selectors(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    selector_re = re.compile(r"(?s)(^|})\s*([^{}@][^{}]+?)\s*\{")
    return [" ".join(match.group(2).split()) for match in selector_re.finditer(text)]


def check_themes() -> list[str]:
    errors = []
    theme_paths = sorted(THEME_DIR.glob("*.css"))
    if not theme_paths:
        return ["No theme CSS files found."]

    reference = css_selectors(theme_paths[0])
    reference_name = theme_paths[0].name

    for path in theme_paths[1:]:
        selectors = css_selectors(path)
        if selectors != reference:
            missing = [selector for selector in reference if selector not in selectors]
            extra = [selector for selector in selectors if selector not in reference]
            if missing:
                errors.append(f"{path.name} is missing selector(s) from {reference_name}: {', '.join(missing)}")
            if extra:
                errors.append(f"{path.name} has extra selector(s) not in {reference_name}: {', '.join(extra)}")
            if not missing and not extra:
                errors.append(f"{path.name} has the same selectors as {reference_name}, but in a different order.")

    return errors


def main() -> int:
    errors = check_themes()
    if errors:
        print("Consistency check failed:")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("Consistency check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
