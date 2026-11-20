#!/usr/bin/env python3
"""Choose which skin your profile README shows.

  python3 scripts/use_skin.py            show the current choice
  python3 scripts/use_skin.py space        everyone sees space
  python3 scripts/use_skin.py frost        frost as the main skin: night in dark mode, day in light mode
  python3 scripts/use_skin.py frost-day    everyone sees frost by day
  python3 scripts/use_skin.py frost-night  everyone sees frost at night
  python3 scripts/use_skin.py auto         dark mode sees space, light mode sees frost by day
  python3 scripts/use_skin.py swap         dark mode sees frost at night, light mode sees space

Only README.md changes. Add, commit and push it afterwards to publish the switch.
"""
import re
import sys
from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"
START, END = "<!-- skin:start -->", "<!-- skin:end -->"
ALT = "Aws on GitHub: public repositories, contribution activity and languages."

# The daily workflow (.github/workflows/skins.yml) draws the skins and force-pushes
# them to the "skins" branch, not to main. The profile is served from main, so the
# images must be referenced by absolute URL on the skins branch -- a relative
# ./skins/ path would resolve to main's stale copy and the profile would never
# auto-update. Keep this in sync with README.md.
SKINS_BRANCH = "skins"
RAW = f"https://raw.githubusercontent.com/Aws-702/Aws-702/{SKINS_BRANCH}"

def src(name):
    return f"{RAW}/{name}.svg"


def img(name):
    return f'<img src="{src(name)}" width="100%" alt="{ALT}">'


def picture(dark, light, fallback):
    return ('<picture>\n'
            f'  <source media="(prefers-color-scheme: dark)" srcset="{src(dark)}">\n'
            f'  <source media="(prefers-color-scheme: light)" srcset="{src(light)}">\n'
            f'  {img(fallback)}\n'
            '</picture>')


MODES = {  # mode: (dark mode skin, light mode skin), equal when everyone sees the same one
    "space": ("space", "space"),
    "frost": ("frost-night", "frost"),
    "frost-day": ("frost", "frost"),
    "frost-night": ("frost-night", "frost-night"),
    "auto": ("space", "frost"),
    "swap": ("frost-night", "space"),
}
BLOCKS = {m: img(d) if d == l else picture(d, l, d) for m, (d, l) in MODES.items()}
NAMES = {"space": "space", "frost": "frost by day", "frost-night": "frost at night"}
DESCRIBE = {m: f"everyone sees {NAMES[d]}" if d == l else f"dark mode sees {NAMES[d]}, light mode sees {NAMES[l]}"
            for m, (d, l) in MODES.items()}


def find_block(text):
    """Return (start, end) of the skin block: the marked one, else a <picture>, else a lone skin <img>."""
    m = re.search(re.escape(START) + r".*?" + re.escape(END), text, re.S)
    if m:
        return m.span()
    m = re.search(r"<picture>.*?</picture>", text, re.S)
    if m:
        return m.span()
    m = re.search(r'<img[^>]*skins/(?:space|frost|frost-night)\.svg[^>]*>', text)
    if m:
        return m.span()
    return None


def current(text):
    span = find_block(text)
    if not span:
        return None
    block = text[span[0]:span[1]]
    name = r'/([\w-]+)\.svg"'  # anchor on the trailing slash so the filename is captured
    dark = re.search(r'prefers-color-scheme: dark\)"\s+srcset="[^"]*' + name, block)
    light = re.search(r'prefers-color-scheme: light\)"\s+srcset="[^"]*' + name, block)
    if dark and light:
        pair = (dark.group(1), light.group(1))
    else:
        one = re.search(r'(?:srcset|src)="[^"]*' + name, block)
        pair = (one.group(1), one.group(1)) if one else None
    for mode, skins in MODES.items():
        if skins == pair:
            return mode
    return None


def main():
    if not README.exists():
        sys.exit(f"README.md not found at {README}")
    text = README.read_text(encoding="utf-8")
    if len(sys.argv) == 1:
        mode = current(text)
        print(f"current: {mode} ({DESCRIBE[mode]})" if mode else "no skin found in README.md")
        print("switch with: python3 scripts/use_skin.py " + " | ".join(MODES))
        return
    mode = sys.argv[1].lower()
    if mode not in BLOCKS:
        sys.exit("choose one of: " + ", ".join(MODES))
    new_block = f"{START}\n{BLOCKS[mode]}\n{END}"
    span = find_block(text)
    text = text[:span[0]] + new_block + text[span[1]:] if span else new_block + "\n" + text
    README.write_text(text, encoding="utf-8")
    print(f"README.md now set to {mode}: {DESCRIBE[mode]}")
    print("publish it with: git add README.md && git commit && git push")


if __name__ == "__main__":
    main()
