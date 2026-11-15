#!/usr/bin/env python3
"""Draws the two full profile skins from public GitHub data only.

  space  You are the sun. Public repos orbit as planets with their languages as moons.
         Below: the past year of contributions as a star chart, then your languages as planetary rings.
  frost  A frozen world after the end (drawn twice: frost.svg by day, frost-night.svg under the moon). You are the last living tree; public repos are ruined towers
         with their languages growing back as vines. Below: the past year as ice and moss tiles,
         then your languages as the rings of a tree stump.

Everything drawn is already public on GitHub:
  repos       /users/<USER>/repos, which only returns public repos; forks, archived and EXCLUDE are dropped
  languages   /repos/<owner>/<repo>/languages for those public repos
  activity    github.com/users/<USER>/contributions, the same calendar your public profile shows

Language colors come from GitHub Linguist (every language GitHub knows), adjusted per skin so each
color reads well on that background and no two languages on your profile look alike.

Usage
  python3 scripts/build_skins.py                   fetch your public data and write skins/*.svg
  python3 scripts/build_skins.py --demo            invented demo data, for previews
  python3 scripts/build_skins.py --demo 0          demo with N repos, to preview how the sun and tree grow
  python3 scripts/build_skins.py --refresh-colors  update the Linguist color list first

Optional: set GITHUB_TOKEN to raise the API rate limit. Needs: pip install fonttools
"""
import argparse
import base64
import calendar as cal
import hashlib
import json
import math
import os
import random
import re
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

# Settings ------------------------------------------------------------------------------------
USER = "Aws-702"
NAME = "Aws"
MAX_REPOS = 8              # planets / towers in the scene
MAX_REPOS_FOR_LANGS = 40   # public repos counted in the language rings
MAX_LANGS_PER_REPO = 3
MIN_LANG_SHARE = 0.03
EXCLUDE = {"aws-702"}      # lowercase repo names that must never appear; the profile repo is already here
AVATAR_FILE = ""           # leave empty to use your GitHub avatar, or set a path to a local image
GROWTH_FULL_AT = 10        # public repos needed for the fully grown tree and the biggest sun

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "skins"
FONT_DIR = HERE / "fonts"
COLORS_FILE = HERE / "linguist_colors.json"
LINGUIST_URL = "https://raw.githubusercontent.com/github-linguist/linguist/main/lib/linguist/languages.yml"

W = 1200
NAVY_DEEP, NAVY, INDIGO, BLUE = "#0A0A3C", "#101445", "#3A4A93", "#526ABE"
CREAM, CYAN = "#FFF5C3", "#0FF0FC"

FONT = {
    "title": TTFont(FONT_DIR / "chakra-petch-latin-700-normal.woff"),
    "head": TTFont(FONT_DIR / "chakra-petch-latin-600-normal.woff"),
    "mono": TTFont(FONT_DIR / "ibm-plex-mono-latin-400-normal.woff"),
    "mono5": TTFont(FONT_DIR / "ibm-plex-mono-latin-500-normal.woff"),
}


# Network -------------------------------------------------------------------------------------
def http(url, api=False):
    headers = {"User-Agent": "profile-skins"}
    if api:
        headers.update({"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        if os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        return r.read().decode("utf-8")


def gh(path):
    return json.loads(http("https://api.github.com" + path, api=True))


def http_bytes(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "profile-skins"}), timeout=30) as r:
        return r.read()


def fetch_avatar():
    """Your profile picture as a data URI, so it is embedded in the SVG (GitHub blocks outside images in SVGs)."""
    if AVATAR_FILE:
        data = Path(AVATAR_FILE).expanduser().read_bytes()
    else:
        url = gh(f"/users/{USER}")["avatar_url"]
        data = http_bytes(url + ("&" if "?" in url else "?") + "s=240")
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif data[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    elif data[:4] == b"GIF8":
        mime = "image/gif"
    elif data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise ValueError("avatar is not a PNG, JPEG, GIF or WebP image")
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


AVATAR = {"href": None}


def growth(n):
    """0 with no public repos, rising to 1 at GROWTH_FULL_AT."""
    if n <= 0:
        return 0.0
    return 0.15 + 0.85 * min(1.0, (n - 1) / max(GROWTH_FULL_AT - 1, 1)) ** 0.7


def avatar(x, y, size, cid, rx=None):
    """Profile picture clipped to a circle, or to a rounded square when rx is given."""
    shape = (f'<circle cx="{fmt(x + size / 2)}" cy="{fmt(y + size / 2)}" r="{fmt(size / 2)}"/>' if rx is None else
             f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(size)}" height="{fmt(size)}" rx="{rx}"/>')
    if AVATAR["href"]:
        body = f'<image href="{AVATAR["href"]}" x="{fmt(x)}" y="{fmt(y)}" width="{fmt(size)}" height="{fmt(size)}" preserveAspectRatio="xMidYMid slice"/>'
    else:  # placeholder pattern for demo runs
        h = hashlib.md5(USER.encode()).digest()
        cell = size * 0.7 / 5
        ox, oy = x + size * 0.15, y + size * 0.15
        blocks = [f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(size)}" height="{fmt(size)}" fill="{INDIGO}"/>']
        for row in range(5):
            for col in range(3):
                if h[row * 3 + col] & 1:
                    for cc in {col, 4 - col}:
                        blocks.append(f'<rect x="{fmt(ox + cc * cell)}" y="{fmt(oy + row * cell)}" width="{fmt(cell + 0.3)}" height="{fmt(cell + 0.3)}" fill="{CREAM}"/>')
        body = "".join(blocks)
    return f'<clipPath id="{cid}">{shape}</clipPath><g clip-path="url(#{cid})">{body}</g>'


def mix(c1, c2, t):
    a, b = oklab(c1), oklab(c2)
    L, A, B = (a[i] + (b[i] - a[i]) * t for i in range(3))
    return from_oklch(L, math.hypot(A, B), math.atan2(B, A))


# Language colors -----------------------------------------------------------------------------
def parse_linguist(yml):
    """Minimal reader for Linguist's languages.yml: name -> color, following `group` when uncolored."""
    colors, groups, name = {}, {}, None
    for line in yml.splitlines():
        if line and not line.startswith((" ", "#", "-")) and line.rstrip().endswith(":"):
            name = line.rstrip()[:-1].strip().strip('"').strip("'")
        elif name and line.startswith("  color:"):
            m = re.search(r'#[0-9A-Fa-f]{6}', line)
            if m:
                colors[name] = m.group(0).upper()
        elif name and line.startswith("  group:"):
            groups[name] = line.split(":", 1)[1].strip().strip('"').strip("'")
    for n, g in groups.items():
        if n not in colors and g in colors:
            colors[n] = colors[g]
    return colors


def load_colors(refresh=False):
    if refresh:
        colors = parse_linguist(http(LINGUIST_URL))
        COLORS_FILE.write_text(json.dumps({"_source": "github-linguist/linguist languages.yml (MIT)", "colors": colors},
                                          indent=0, sort_keys=True))
        print(f"updated {len(colors)} language colors")
    return json.loads(COLORS_FILE.read_text())["colors"]


def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gam(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def oklab(hx):
    r, g, b = (_lin(int(hx[i:i + 2], 16) / 255) for i in (1, 3, 5))
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def oklch(hx):
    L, a, b = oklab(hx)
    return L, math.hypot(a, b), math.atan2(b, a)


def from_oklch(L, C, h):
    """OKLCH to hex, pulling chroma in until the color fits in sRGB."""
    for _ in range(60):
        a, b = C * math.cos(h), C * math.sin(h)
        l_, m_, s_ = L + 0.3963377774 * a + 0.2158037573 * b, L - 0.1055613458 * a - 0.0638541728 * b, L - 0.0894841775 * a - 1.2914855480 * b
        l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
        rgb = (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
               -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
               -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)
        if all(-1e-4 <= v <= 1.0001 for v in rgb):
            break
        C *= 0.93
    return "#%02X%02X%02X" % tuple(round(_gam(min(max(v, 0), 1)) * 255) for v in rgb)


def tone(hx, dL=0.0, cmul=1.0):
    L, C, h = oklch(hx)
    return from_oklch(min(max(L + dL, 0), 1), C * cmul, h)


def base_color(lang, colors):
    if lang in colors:
        return colors[lang]
    h = int(hashlib.md5(lang.encode()).hexdigest()[:6], 16) / 0xFFFFFF * 2 * math.pi
    return from_oklch(0.68, 0.13, h)


BANDS = {"space": (0.72, 0.9), "frost": (0.46, 0.66), "frost-night": (0.62, 0.84)}
MIN_DIST = 0.085


def palette(langs, skin, colors):
    """Color engine: Linguist color, moved into the skin's lightness band, then nudged apart from
    every more used language until all colors on the profile are clearly different."""
    lo, hi = BANDS[skin]
    trials = [(0, 0, 0), (24, 0, 0), (-24, 0, 0), (48, 0, 0), (-48, 0, 0), (0, 0.07, 0.07), (0, -0.07, 0.07),
              (75, 0, 0.08), (-75, 0, 0.08), (110, 0.04, 0.1), (-110, -0.04, 0.1), (160, 0, 0.12), (200, 0, 0.12)]
    out = {}
    for lang in langs:
        L, C, h = oklch(base_color(lang, colors))
        L = min(max(L, lo), hi)
        best, best_d = None, -1
        for dh, dL, cmin in trials:
            cand = from_oklch(min(max(L + dL, lo), hi), max(C, cmin), h + math.radians(dh))
            p = oklab(cand)
            d = min((math.dist(p, oklab(o)) for o in out.values()), default=9)
            if d >= MIN_DIST:
                best = cand
                break
            if d > best_d:
                best, best_d = cand, d
        out[lang] = best
    out["Other"] = {"space": "#8C93A8", "frost": "#8A96A6"}.get(skin, "#A3AEC6")
    return out


# Data ----------------------------------------------------------------------------------------
def fetch_repos():
    repos = gh(f"/users/{USER}/repos?type=owner&per_page=100&sort=pushed")
    keep = [r for r in repos
            if not r.get("private") and r.get("visibility", "public") == "public"
            and not r.get("fork") and not r.get("archived") and r["name"].lower() not in EXCLUDE]
    keep.sort(key=lambda r: (r.get("stargazers_count", 0), r.get("pushed_at") or ""), reverse=True)
    return [{"name": r["name"], "langs": gh(f"/repos/{r['full_name']}/languages"), "stars": r.get("stargazers_count", 0)}
            for r in keep[:MAX_REPOS_FOR_LANGS]]


def fetch_calendar():
    html = http(f"https://github.com/users/{USER}/contributions")
    cells = {}
    for m in re.finditer(r"<td\b[^>]*>", html):
        tag = m.group(0)
        d, i, lv = (re.search(p, tag) for p in (r'data-date="(\d{4}-\d{2}-\d{2})"', r'\bid="([^"]+)"', r'data-level="(\d)"'))
        if d and i and lv:
            cells[i.group(1)] = [date.fromisoformat(d.group(1)), int(lv.group(1)), None]
    for m in re.finditer(r'<tool-tip\b[^>]*\bfor="([^"]+)"[^>]*>(.*?)</tool-tip>', html, re.S):
        n = re.match(r"\s*([\d,]+|No) contribution", m.group(2))
        if m.group(1) in cells and n:
            cells[m.group(1)][2] = 0 if n.group(1) == "No" else int(n.group(1).replace(",", ""))
    days = sorted((d, c if c is not None else lv, lv) for d, lv, c in cells.values())
    if not days:
        raise ValueError("no calendar cells found")
    return days


DEMO_REPOS = [
    {"name": "nebula-notes", "langs": {"C++": 210000, "QML": 9000, "CMake": 6000}, "stars": 5},
    {"name": "glass-ui", "langs": {"TypeScript": 90000, "CSS": 14000, "HTML": 3000}, "stars": 0},
    {"name": "pond-sim", "langs": {"JavaScript": 61000, "HTML": 12000, "CSS": 8000}, "stars": 1},
    {"name": "lantern-cli", "langs": {"Python": 48000, "Shell": 3000}, "stars": 3},
    {"name": "atlas-maps", "langs": {"Rust": 34000}, "stars": 0},
    {"name": "relay-bot", "langs": {"Python": 22000, "Dockerfile": 900}, "stars": 2},
    {"name": "game-jam", "langs": {"GDScript": 15000, "GLSL": 2500}, "stars": 0},
    {"name": "scratchpad", "langs": {"Zig": 6000, "Haskell": 4000, "Elixir": 2500, "Lua": 1800}, "stars": 0},
]


def demo_calendar():
    rng = random.Random(3)
    end = date.today()
    days, streak_start = [], end - timedelta(days=rng.randint(120, 200))
    for k in range(364 + (end.weekday() + 1) % 7 + 1):
        d = end - timedelta(days=k)
        p = 0.62 if d.weekday() < 5 else 0.35
        forced = streak_start <= d < streak_start + timedelta(days=27) or k < 9
        c = 0 if (rng.random() > p and not forced) else max(1, int(rng.expovariate(1 / 5)))
        lv = 0 if c == 0 else 1 if c <= 3 else 2 if c <= 7 else 3 if c <= 12 else 4
        days.append((d, c, lv))
    return sorted(days)


def prepare(repos):
    for r in repos:
        total = sum(r["langs"].values())
        r["total"] = total
        ranked = sorted(r["langs"].items(), key=lambda kv: -kv[1])
        r["top"] = [(k, v / total) for k, v in ranked if total and v / total >= MIN_LANG_SHARE][:MAX_LANGS_PER_REPO]
    scene = repos[:MAX_REPOS]
    sizes = [math.log10(max(r["total"], 1000)) for r in scene]
    lo, hi = (min(sizes), max(sizes)) if sizes else (0, 1)
    for r, s in zip(scene, sizes):
        r["norm"] = 0.5 if hi - lo < 1e-6 else (s - lo) / (hi - lo)
    totals = {}
    for r in repos:
        for k, v in r["langs"].items():
            totals[k] = totals.get(k, 0) + v
    lang_totals = sorted(totals.items(), key=lambda kv: -kv[1])
    return scene, lang_totals


def calendar_stats(days):
    active = [c > 0 for _, c, _ in days]
    longest, end_i, run = 0, -1, 0
    for i, a in enumerate(active):
        run = run + 1 if a else 0
        if run > longest:
            longest, end_i = run, i
    i = len(days) - 1
    if i >= 0 and not active[i]:
        i -= 1
    current = 0
    while i >= 0 and active[i]:
        current, i = current + 1, i - 1
    best = max(days, key=lambda d: d[1])
    return {"total": sum(c for _, c, _ in days), "current": current, "longest": longest,
            "streak": (end_i - longest + 1, end_i) if longest else None, "best": best}


# Drawing helpers -----------------------------------------------------------------------------
def fmt(v):
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


def text(key, s, size, x, y, anchor="start", tracking=0.0):
    """Outline a string as an SVG path so it renders the same everywhere. Returns (d, width)."""
    font = FONT[key]
    gs, cmap, hmtx = font.getGlyphSet(), font.getBestCmap(), font["hmtx"]
    scale = size / font["head"].unitsPerEm
    names = [cmap.get(ord(ch)) or cmap.get(ord("?")) for ch in s]
    adv = [hmtx[g][0] * scale + tracking for g in names]
    width = sum(adv) - (tracking if names else 0)
    x -= width / 2 if anchor == "middle" else width if anchor == "end" else 0
    pen = SVGPathPen(gs, ntos=fmt)
    cx = x
    for g, a in zip(names, adv):
        gs[g].draw(TransformPen(pen, (scale, 0, 0, -scale, cx, y)))
        cx += a
    return pen.getCommands(), width


def tpath(key, s, size, x, y, fill, opacity=1.0, anchor="start", tracking=0.0):
    d, _ = text(key, s, size, x, y, anchor, tracking)
    op = f' opacity="{opacity}"' if opacity < 1 else ""
    return f'<path d="{d}" fill="{fill}"{op}/>'


def fit(key, s, size, max_w):
    if text(key, s, size, 0, 0)[1] <= max_w:
        return s
    while len(s) > 3 and text(key, s + "..", size, 0, 0)[1] > max_w:
        s = s[:-1]
    return s + ".."


def poly(pts, close=False):
    return "M" + " L".join(f"{fmt(p[0])} {fmt(p[1])}" for p in pts) + (" Z" if close else "")


def ellipse_pts(rx, ry, n=180):
    return [(rx * math.cos(2 * math.pi * i / n), ry * math.sin(2 * math.pi * i / n), math.sin(2 * math.pi * i / n) > 0)
            for i in range(n + 1)]


def hidden_window(pts, r_block, extra):
    lengths = [0.0]
    for (x0, y0, _), (x1, y1, _) in zip(pts, pts[1:]):
        lengths.append(lengths[-1] + math.hypot(x1 - x0, y1 - y0))
    idx = [i for i, (x, y, front) in enumerate(pts) if not front and math.hypot(x, y) < r_block + extra]
    if not idx:
        return None
    a, b = lengths[idx[0]] / lengths[-1], lengths[idx[-1]] / lengths[-1]
    return [0, max(a - 0.015, 0.001), a, b, min(b + 0.015, 0.999), 1]


def starfield(rng, h, n, avoid=lambda x, y: False):
    out = []
    for _ in range(n):
        x, y = rng.uniform(0, W), rng.uniform(0, h)
        if avoid(x, y):
            continue
        r = rng.choice([0.6, 0.8, 1.0, 1.2]) if rng.random() > 0.07 else rng.uniform(1.5, 2.1)
        col = CREAM if rng.random() < 0.25 else "#FFFFFF"
        if rng.random() < 0.45:
            d = rng.uniform(2.5, 6)
            out.append(f'<circle class="tw" cx="{fmt(x)}" cy="{fmt(y)}" r="{r}" fill="{col}" '
                       f'style="animation-duration:{d:.1f}s;animation-delay:{-rng.uniform(0, d):.1f}s"/>')
        else:
            out.append(f'<circle cx="{fmt(x)}" cy="{fmt(y)}" r="{r}" fill="{col}" opacity="{rng.uniform(0.35, 0.95):.2f}"/>')
    return "\n".join(out)


def calendar_layout(days, top):
    start = days[0][0] - timedelta(days=(days[0][0].weekday() + 1) % 7)
    cols = (days[-1][0] - start).days // 7 + 1
    pitch = min(20.0, (W - 140) / cols)
    x0 = (W - cols * pitch) / 2 + pitch / 2
    pos = [(x0 + ((d - start).days // 7) * pitch, top + ((d.weekday() + 1) % 7) * pitch) for d, _, _ in days]
    months, last_col = [], -9
    for (d, _, _), (x, _) in zip(days, pos):
        col = round((x - x0) / pitch)
        if d.day == 1 and col - last_col > 2:
            months.append((x - pitch / 2, cal.month_abbr[d.month]))
            last_col = col
    return pos, pitch, months


def streak_path(pos, a, b):
    """Snake through the streak's cells column by column, so the line only joins neighbouring cells."""
    cols = {}
    for i in range(a, b + 1):
        cols.setdefault(round(pos[i][0], 1), []).append(pos[i])
    out = []
    for k, x in enumerate(sorted(cols)):
        cells = sorted(cols[x], key=lambda p: p[1])
        out += cells if k % 2 == 0 else cells[::-1]
    return out


def stats_row(stats, y, value_fill, label_fill):
    best_d, best_c, _ = stats["best"]
    items = [
        (f"{stats['total']:,}", "PAST YEAR"),
        (f"{stats['current']} day{'s' if stats['current'] != 1 else ''}", "CURRENT STREAK"),
        (f"{stats['longest']} day{'s' if stats['longest'] != 1 else ''}", "LONGEST STREAK"),
        (f"{best_c} on {cal.month_abbr[best_d.month]} {best_d.day}" if best_c else "none yet", "BUSIEST DAY"),
    ]
    out = []
    for k, (val, lab) in enumerate(items):
        cx = W * (2 * k + 1) / 8
        out.append(tpath("head", val, 28, cx, y, value_fill, anchor="middle"))
        out.append(tpath("mono5", lab, 11.5, cx, y + 24, label_fill, 0.6, anchor="middle", tracking=2.5))
    return "\n".join(out)


def lang_list(lang_totals, P, x0, y0, fill, track):
    total = sum(v for _, v in lang_totals) or 1
    rows = [(k, v / total) for k, v in lang_totals[:11]]
    rest = sum(v for _, v in lang_totals[11:]) / total
    if rest > 0:
        rows.append(("Other", rest))
    top_share = max((s for _, s in rows), default=1)
    out = []
    per_col = max(1, math.ceil(len(rows) / 2))
    for idx, (lang, share) in enumerate(rows):
        x = x0 + (idx // per_col) * 290
        y = y0 + (idx % per_col) * 32
        pct = f"{share * 100:.1f}%" if share >= 0.001 else "<0.1%"
        out.append(f'<circle cx="{x + 5}" cy="{fmt(y - 4.5)}" r="5" fill="{P[lang]}"/>')
        out.append(tpath("mono", fit("mono", lang, 14, 160), 14, x + 17, y, fill, 0.9))
        out.append(tpath("mono", pct, 13, x + 250, y, fill, 0.6, anchor="end"))
        out.append(f'<rect x="{x + 17}" y="{y + 7}" width="233" height="3" rx="1.5" fill="{track}"/>')
        out.append(f'<rect x="{x + 17}" y="{y + 7}" width="{fmt(max(2, 233 * share / top_share))}" height="3" rx="1.5" fill="{P[lang]}"/>')
    return "\n".join(out), [k for k, _ in rows]


TWINKLE_CSS = """
.tw{animation-name:tw;animation-timing-function:ease-in-out;animation-iteration-count:infinite}
@keyframes tw{0%,100%{opacity:.15}50%{opacity:1}}
"""
REDUCED = "@media (prefers-reduced-motion: reduce){*{animation:none!important}}"


# Space ---------------------------------------------------------------------------------------
def space(scene, lang_totals, days, stats, colors, n_public):
    CX, CY = 600, 300
    g = growth(n_public)
    SUN = 22 if n_public == 0 else 28 + 34 * g
    sc = {k: mix(blue, warm, g) for k, (blue, warm) in {
        'core': ('#E8F4FF', '#FFFFF4'), 'mid': ('#9CCBFF', CREAM), 'edge': ('#3F7BFF', '#FFB24A'),
        'glow': ('#6FA8FF', '#FFC86B'), 'c1': ('#7FB2FF', '#FFD27A'), 'c2': ('#D2E8FF', CREAM)}.items()}
    has_cal = bool(days)
    cal_top = 652
    lang_y = 1060 if has_cal else 760
    H = lang_y + 150 if lang_totals else (cal_top + 7 * 20 + 130 if has_cal else 640)
    rng = random.Random(11)
    langs_order = [k for k, _ in lang_totals]
    for r in scene:
        for k, _ in r["top"]:
            if k not in langs_order:
                langs_order.append(k)
    P = palette(langs_order, "space", colors)

    defs, body = [], []
    n = len(scene)
    for i, r in enumerate(scene):
        t = i / max(n - 1, 1) if n > 1 else 0.35
        rx, ry = 180 + t * 340, 128 + t * 100
        orbit = f"M{fmt(CX + rx)} {CY} A{fmt(rx)} {fmt(ry)} 0 1 1 {fmt(CX - rx)} {CY} A{fmt(rx)} {fmt(ry)} 0 1 1 {fmt(CX + rx)} {CY}"
        period = 30 * (rx / 180) ** 1.5
        begin = -((i * 0.618 + 0.2) % 1) * period
        motion = f'dur="{period:.1f}s" begin="{begin:.1f}s" repeatCount="indefinite" path="{orbit}"'
        pr = 11 + 12 * r["norm"]
        base = P[r["top"][0][0]] if r["top"] else "#8A93B8"
        defs.append(f'<radialGradient id="pg{i}" cx="0.4" cy="0.4" r="0.7"><stop offset="0" stop-color="{tone(base, 0.1)}"/>'
                    f'<stop offset="0.6" stop-color="{tone(base, -0.06)}"/><stop offset="1" stop-color="{tone(base, -0.28)}"/></radialGradient>')
        body.append(f'<ellipse cx="{CX}" cy="{CY}" rx="{fmt(rx)}" ry="{fmt(ry)}" fill="none" stroke="{CYAN}" '
                    f'stroke-width="1" stroke-dasharray="2 6" opacity="0.32"/>')
        moons, lines, reach_y = [], [], pr
        for j, (lang, share) in enumerate(r["top"]):
            mo, mr = pr + 8 + j * 7, 2.6 + 3.2 * share
            pts = ellipse_pts(mo, mo * 0.42)
            kt = hidden_window(pts, pr, mr * 0.6)
            md = 3.4 + j * 1.8 + rng.uniform(0, 0.6)
            mb = -rng.uniform(0, md)
            anim = (f'<animate attributeName="opacity" values="1;1;0;0;1;1" keyTimes="{";".join(f"{k:.3f}" for k in kt)}" '
                    f'dur="{md:.2f}s" begin="{mb:.2f}s" repeatCount="indefinite"/>') if kt else ""
            moons.append(f'<circle r="{mr:.1f}" fill="{P[lang]}"><animateMotion path="{poly(pts, True)}" '
                         f'dur="{md:.2f}s" begin="{mb:.2f}s" repeatCount="indefinite" calcMode="paced"/>{anim}</circle>')
            lines.append(f'<ellipse rx="{mo}" ry="{fmt(mo * 0.42)}" fill="none" stroke="{CREAM}" stroke-width="0.7" opacity="0.18"/>')
            reach_y = max(pr, mo * 0.42 + mr)
        lab = text("mono", fit("mono", r["name"], 13, 150), 13, 0, reach_y + 16, anchor="middle")[0]
        body.append(f"""<g><animateMotion {motion}/>{"".join(lines)}
  <circle r="{fmt(pr + 5)}" fill="{base}" opacity="0.22" filter="url(#soft)"/>
  <circle r="{fmt(pr)}" fill="url(#pg{i})"/><path d="{lab}" fill="{CREAM}" opacity="0.88"/></g>
<g><animateMotion {motion} rotate="auto"/><circle r="{fmt(pr + 0.3)}" fill="url(#term)"/></g>
<g><animateMotion {motion}/>{"".join(moons)}</g>""")

    def corona(seed, spikes, r_in, r_out):
        g = random.Random(seed)
        return poly([(CX + (r_out * g.uniform(0.85, 1.15) if k % 2 == 0 else r_in) * math.cos(math.pi * k / spikes),
                      CY + (r_out * g.uniform(0.85, 1.15) if k % 2 == 0 else r_in) * math.sin(math.pi * k / spikes))
                     for k in range(spikes * 2)], True)

    # activity: the past year as a star chart, longest streak drawn as a constellation
    act = []
    if has_cal:
        pos, pitch, months = calendar_layout(days, cal_top)
        for mx, m in months:
            act.append(tpath("mono", m, 12, mx, cal_top - 18, CREAM, 0.55))
        if stats["streak"]:
            a, b = stats["streak"]
            sp = streak_path(pos, a, b)
            act.append(f'<path d="{poly(sp)}" fill="none" stroke="{CYAN}" stroke-width="1.1" opacity="0.5" stroke-linejoin="round"/>')
            act.append("".join(f'<circle cx="{fmt(x)}" cy="{fmt(y)}" r="6.5" fill="none" stroke="{CYAN}" stroke-width="0.8" opacity="0.35"/>' for x, y in sp))
        glow, stars = [], []
        star_cols = [CREAM, CREAM, "#D9F7E8", "#9DF5F0", CYAN]
        for (d, c, lv), (x, y) in zip(days, pos):
            if lv == 0:
                stars.append(f'<circle cx="{fmt(x)}" cy="{fmt(y)}" r="1.3" fill="#FFFFFF" opacity="0.16"/>')
                continue
            r = (2.0, 2.8, 3.6, 4.6)[lv - 1]
            cls = ' class="tw" style="animation-duration:4s;animation-delay:-%.1fs"' % rng.uniform(0, 4) if lv == 4 else ""
            stars.append(f'<circle cx="{fmt(x)}" cy="{fmt(y)}" r="{r}" fill="{star_cols[lv]}" opacity="{(0.55, 0.75, 0.9, 1)[lv - 1]}"{cls}/>')
            if lv >= 3:
                glow.append(f'<circle cx="{fmt(x)}" cy="{fmt(y)}" r="{r + 3}" fill="{star_cols[lv]}" opacity="0.5"/>')
        act.append(f'<g filter="url(#soft)">{"".join(glow)}</g>')
        act.extend(stars)
        act.append(stats_row(stats, cal_top + 7 * pitch + 66, CREAM, CREAM))

    # languages: planetary rings, thickness by share
    lst, shown = lang_list(lang_totals, P, 640, lang_y - 72, CREAM, "#FFFFFF22")
    total = sum(v for _, v in lang_totals) or 1
    shares = {k: v / total for k, v in lang_totals[:11]}
    if "Other" in shown:
        shares["Other"] = 1 - sum(shares.values())
    px, py, prr = 320, lang_y, 40
    back, front, rad = [], [], 62.0
    usable = 118 - len(shown) * 2.2
    for lang in shown:
        t = 2.2 + shares.get(lang, 0) * max(usable - 2.2 * len(shown), 20)
        mid = rad + t / 2
        back.append(f'<path d="M{fmt(-mid)} 0 A{fmt(mid)} {fmt(mid)} 0 0 1 {fmt(mid)} 0" fill="none" stroke="{P[lang]}" stroke-width="{fmt(t)}" opacity="0.6"/>')
        front.append(f'<path d="M{fmt(mid)} 0 A{fmt(mid)} {fmt(mid)} 0 0 1 {fmt(-mid)} 0" fill="none" stroke="{P[lang]}" stroke-width="{fmt(t)}" opacity="0.92"/>')
        rad += t + 2.2
    ring_tf = f'translate({px} {py}) rotate(-14) scale(1 0.3)'
    rings_svg = f'''  <g transform="{ring_tf}">{"".join(back)}</g>
  <circle cx="{px}" cy="{py}" r="{prr + 6}" fill="{BLUE}" opacity="0.25" filter="url(#soft)"/>
  <circle cx="{px}" cy="{py}" r="{prr}" fill="url(#ringplanet)"/>
  <path d="M{px - prr * 0.93} {fmt(py + prr * 0.36)} A{prr} {prr} 0 0 1 {fmt(px + prr * 0.2)} {fmt(py - prr * 0.98)}" fill="none" stroke="{CREAM}" stroke-width="1.6" stroke-linecap="round" opacity="0.5"/>
  <g transform="{ring_tf}">{"".join(front)}</g>
  {lst}''' if lang_totals else ""

    stars_avoid = lambda x, y: math.hypot(x - CX, y - CY) < SUN + 30 or (has_cal and 50 < x < 1150 and 600 < y < cal_top + 230) or (600 < x < 1200 and lang_y - 100 < y < lang_y + 130)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{NAME} on GitHub: public repositories orbiting as planets, the past year of contributions, and languages as planetary rings.">
<title>{NAME}</title>
<style>{TWINKLE_CSS}
.pulse{{animation:pulse 5s ease-in-out infinite alternate}}
@keyframes pulse{{0%{{opacity:.55}}100%{{opacity:.95}}}}
.shoot{{animation:shoot 12s ease-in infinite;animation-delay:4s;opacity:0}}
@keyframes shoot{{0%{{transform:translate(0,0);opacity:0}}2%{{opacity:1}}9%{{transform:translate(-320px,160px);opacity:0}}100%{{transform:translate(-320px,160px);opacity:0}}}}
{REDUCED}</style>
<defs>
  <clipPath id="frame"><rect width="{W}" height="{H}" rx="18"/></clipPath>
  <linearGradient id="sky" x1="0" y1="0" x2="0.4" y2="1"><stop offset="0" stop-color="#05051F"/><stop offset="0.5" stop-color="{NAVY_DEEP}"/><stop offset="1" stop-color="{NAVY}"/></linearGradient>
  <radialGradient id="neb1" cx="0.18" cy="0.18" r="0.5"><stop offset="0" stop-color="{BLUE}" stop-opacity="0.3"/><stop offset="1" stop-color="{BLUE}" stop-opacity="0"/></radialGradient>
  <radialGradient id="neb2" cx="0.85" cy="0.7" r="0.55"><stop offset="0" stop-color="{INDIGO}" stop-opacity="0.4"/><stop offset="1" stop-color="{INDIGO}" stop-opacity="0"/></radialGradient>
  <radialGradient id="glow" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="{sc['mid']}" stop-opacity="0.55"/><stop offset="0.35" stop-color="{sc['glow']}" stop-opacity="0.18"/><stop offset="1" stop-color="{sc['glow']}" stop-opacity="0"/></radialGradient>
  <radialGradient id="limb" cx="0.5" cy="0.5" r="0.5"><stop offset="0.62" stop-color="{sc['edge']}" stop-opacity="0"/><stop offset="0.86" stop-color="{sc['edge']}" stop-opacity="0.35"/><stop offset="1" stop-color="{sc['edge']}" stop-opacity="0.85"/></radialGradient>
  <radialGradient id="ringplanet" cx="0.38" cy="0.35" r="0.75"><stop offset="0" stop-color="{BLUE}"/><stop offset="0.6" stop-color="{INDIGO}"/><stop offset="1" stop-color="#14184F"/></radialGradient>
  <linearGradient id="term" x1="0.5" y1="1" x2="0.5" y2="0"><stop offset="0" stop-color="#03031A" stop-opacity="0"/><stop offset="0.45" stop-color="#03031A" stop-opacity="0"/><stop offset="0.7" stop-color="#03031A" stop-opacity="0.55"/><stop offset="1" stop-color="#03031A" stop-opacity="0.8"/></linearGradient>
  <linearGradient id="tail" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{CREAM}"/><stop offset="1" stop-color="{CREAM}" stop-opacity="0"/></linearGradient>
  <filter id="soft" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="4"/></filter>
  <filter id="corona" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="6"/></filter>
  {"".join(defs)}
</defs>
<g clip-path="url(#frame)">
  <rect width="{W}" height="{H}" fill="url(#sky)"/>
  <rect width="{W}" height="{H}" fill="url(#neb1)"/>
  <rect width="{W}" height="{H}" fill="url(#neb2)"/>
  {starfield(rng, H, int(H * 0.32), stars_avoid)}
  <g class="shoot"><line x1="1010" y1="90" x2="1120" y2="35" stroke="url(#tail)" stroke-width="2" stroke-linecap="round"/></g>
  <circle class="pulse" cx="{CX}" cy="{CY}" r="{SUN * 3}" fill="url(#glow)"/>
  <path d="{corona(1, 22, SUN * 0.95, SUN * 1.45)}" fill="{sc['c1']}" opacity="0.45" filter="url(#corona)">
    <animateTransform attributeName="transform" type="rotate" from="0 {CX} {CY}" to="360 {CX} {CY}" dur="140s" repeatCount="indefinite"/></path>
  <path d="{corona(2, 17, SUN * 0.95, SUN * 1.3)}" fill="{sc['c2']}" opacity="0.5" filter="url(#corona)">
    <animateTransform attributeName="transform" type="rotate" from="360 {CX} {CY}" to="0 {CX} {CY}" dur="95s" repeatCount="indefinite"/></path>
  <circle cx="{CX}" cy="{CY}" r="{fmt(SUN + 1.5)}" fill="{sc['core']}"/>
  {avatar(CX - SUN, CY - SUN, SUN * 2, "sunpfp")}
  <circle cx="{CX}" cy="{CY}" r="{fmt(SUN)}" fill="url(#limb)"/>
  <circle cx="{CX}" cy="{CY}" r="{fmt(SUN)}" fill="none" stroke="{sc['mid']}" stroke-width="{fmt(max(1.5, SUN * 0.05))}"/>
  {"".join(body)}
  {"".join(act)}
  {rings_svg}
</g>
</svg>"""
    (OUT / "space.svg").write_text(svg)


# Frost ---------------------------------------------------------------------------------------
GROUND = 560
BARK, BARK_LIGHT = "#3B2A2D", "#7A5A5C"
BLOSSOM = {"shadow": "#C2557F", "mid": "#E886A8", "light": "#F7B5CB", "pale": "#FFE3EC", "eye": "#A8335F"}


def jag_top(rng, x0, x1, top, broken):
    pts, x = [(x0, top + rng.uniform(0, 10))], x0
    while x < x1:
        x = min(x + rng.uniform(10, 22), x1)
        pts.append((x, top + (rng.uniform(0, 34) if broken and rng.random() < 0.55 else rng.uniform(0, 6))))
    return pts


def top_at(pts, x):
    for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
        if xa <= x <= xb:
            return ya + (yb - ya) * ((x - xa) / max(xb - xa, 1e-6))
    return pts[-1][1]


def skyline(rng, base, hmin, hmax, color, snow, windows=False):
    out, x = [], -20
    while x < W + 20:
        w, h = rng.uniform(40, 95), rng.uniform(hmin, hmax)
        pts = jag_top(rng, x, x + w, base - h, rng.random() < 0.6)
        out.append(f'<path d="{poly([(x, base)] + pts + [(x + w, base)], True)}" fill="{color}"/>')
        out.append(f'<path d="{poly(pts)}" fill="none" stroke="{snow}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>')
        if windows:
            out.append(f'<path d="{poly([(x, base - 12)] + [(px, py + 14) for px, py in pts] + [(x + w, base - 12)], True)}" fill="url(#winpat)"/>')
        x += w + rng.uniform(-8, 14)
    return "\n".join(out)


def pine(x, base, h, body, snow, rng):
    out = [f'<rect x="{fmt(x - h * 0.035)}" y="{fmt(base - h * 0.14)}" width="{fmt(h * 0.07)}" height="{fmt(h * 0.15)}" fill="#3B3430"/>']
    for k in range(4):
        ty = base - h + k * h * 0.2
        by = ty + h * 0.34
        tw = h * 0.55 * (0.45 + 0.55 * (k + 1) / 4) / 2
        out.append(f'<path d="M{fmt(x)} {fmt(ty)} L{fmt(x + tw)} {fmt(by)} Q{fmt(x)} {fmt(by - h * 0.05)} {fmt(x - tw)} {fmt(by)} Z" fill="{body}"/>')
        sw = tw * rng.uniform(0.55, 0.8)
        out.append(f'<path d="M{fmt(x)} {fmt(ty)} L{fmt(x + sw * 0.9)} {fmt(ty + (by - ty) * 0.62)} Q{fmt(x)} {fmt(ty + (by - ty) * 0.42)} {fmt(x - sw)} {fmt(ty + (by - ty) * 0.66)} Z" fill="{snow}"/>')
    return "".join(out)


def bare_tree(rng, x, base, length, depth, color, width):
    segs = []

    def grow(x0, y0, ang, ln, d, wd):
        x1, y1 = x0 + ln * math.cos(ang), y0 + ln * math.sin(ang)
        segs.append((x0, y0, x1, y1, wd))
        if d:
            for _ in range(2 if rng.random() < 0.8 else 3):
                grow(x1, y1, ang + math.radians(rng.uniform(-34, 34)), ln * rng.uniform(0.64, 0.8), d - 1, wd * 0.68)

    grow(x, base, -math.pi / 2 + rng.uniform(-0.08, 0.08), length, depth, width)
    return "".join(f'<line x1="{fmt(a)}" y1="{fmt(b)}" x2="{fmt(c)}" y2="{fmt(d)}" stroke="{color}" stroke-width="{max(w, 0.6):.1f}" stroke-linecap="round"/>'
                   for a, b, c, d, w in segs)


def clump_d(x, y, r, rng, n=32):
    """Outline of a fluffy blossom clump: a circle with a scalloped edge."""
    lobes, ph = rng.randint(7, 10), rng.uniform(0, 6.3)
    pts = [(x + r * (1 + 0.07 * math.sin(lobes * t + ph)) * math.cos(t), y + r * (1 + 0.07 * math.sin(lobes * t + ph)) * math.sin(t))
           for t in (2 * math.pi * q / n for q in range(n))]
    if r < 16:
        return "M" + " L".join(f"{px:.1f} {py:.1f}" for px, py in pts) + " Z"
    return "M" + " L".join(f"{round(px)} {round(py)}" for px, py in pts) + " Z"


def puff_pattern(pid, w, h, seed, rmin, rmax, n):
    """A seamless tile of small overlapping blossom puffs, each with a shadowed lower edge and a lit top."""
    prng = random.Random(seed)
    puffs = [(prng.uniform(0, w), prng.uniform(0, h), prng.uniform(rmin, rmax)) for _ in range(n)]
    items = []
    for x, y, r in sorted(puffs, key=lambda p: -p[1]):
        for ox in (-w, 0, w):
            for oy in (-h, 0, h):
                cx, cy = x + ox, y + oy
                if -r - 2 < cx < w + r + 2 and -r - 2 < cy < h + r + 2:
                    items.append(clump(cx + 1.1, cy + 1.6, r, "#D96C93", prng, 14, 0.42))
                    items.append(clump(cx, cy, r * 0.95, "#F5ABC5", prng, 14, 0.6))
                    items.append(f'<circle cx="{cx - r * 0.3:.1f}" cy="{cy - r * 0.35:.1f}" r="{r * 0.32:.1f}" fill="#FFE8F0" opacity="0.5"/>')
    return f'<pattern id="{pid}" width="{w}" height="{h}" patternUnits="userSpaceOnUse">{"".join(items)}</pattern>'


def clump(x, y, r, fill, rng, n=32, opacity=None):
    op = f' opacity="{opacity}"' if opacity is not None else ""
    return f'<path d="{clump_d(x, y, r, rng, n)}" fill="{fill}"{op}/>'


def snow_cap(x, y, r, rng):
    """Snow lying on the top of a round foliage clump, thickest at the crown, with a soft underside."""
    a0, a1, n = math.pi + 0.5, 2 * math.pi - 0.5, 16
    top = [(x + (r + 1.2) * math.cos(a0 + (a1 - a0) * q / n), y + (r + 1.2) * math.sin(a0 + (a1 - a0) * q / n)) for q in range(n + 1)]
    under = []
    for q in range(n + 1):
        t = a1 - (a1 - a0) * q / n
        th = r * (0.08 + 0.26 * math.sin(math.pi * q / n)) + (r * 0.07 if q % 4 == 2 else 0) + rng.uniform(-0.5, 0.5)
        under.append((x + (r - th) * math.cos(t), y + (r - th) * math.sin(t)))
    return (f'<path d="{poly(top + under, True)}" fill="#F6FAFD"/>'
            f'<path d="{poly(under)}" fill="none" stroke="#C3D3E0" stroke-width="1" opacity="0.9"/>')


def flower(x, y, r, petal="#FFF0F5", eye="#B23C6E"):
    """A small five petal cherry flower."""
    out = []
    for a in range(-90, 270, 72):
        px, py = x + r * 0.6 * math.cos(math.radians(a)), y + r * 0.6 * math.sin(math.radians(a))
        out.append(f'<ellipse cx="{fmt(px)}" cy="{fmt(py)}" rx="{fmt(r * 0.6)}" ry="{fmt(r * 0.42)}" fill="{petal}" transform="rotate({a} {fmt(px)} {fmt(py)})"/>')
    out.append(f'<circle cx="{fmt(x)}" cy="{fmt(y)}" r="{fmt(r * 0.3)}" fill="{eye}"/>')
    return "".join(out)


def petals(rng, area, count, H):
    """Cherry petals drifting down from the crown to the snow."""
    x0, y0, x1, y1 = area
    out = []
    for k in range(count):
        x, y = rng.uniform(x0, x1), rng.uniform(y0, y1)
        d = rng.uniform(7, 13)
        col = BLOSSOM["light"] if k % 3 else BLOSSOM["mid"]
        out.append(f'<ellipse class="pt{k % 2}" cx="{fmt(x)}" cy="{fmt(y)}" rx="2.8" ry="1.6" fill="{col}" '
                   f'style="--fall:{fmt(GROUND - y + rng.uniform(0, 14))}px;animation-duration:{d:.1f}s;animation-delay:{-rng.uniform(0, d):.1f}s"/>')
    return "\n".join(out)


def sapling(x, base):
    """No public repos yet: a young sapling poking out of the snow."""
    leaves = [(x - 11, base - 41, -40, BLOSSOM["mid"]), (x + 7, base - 37, 52, BLOSSOM["shadow"]), (x - 5, base - 48, -62, BLOSSOM["light"])]
    out = [f'<ellipse cx="{x}" cy="{base + 1}" rx="26" ry="6" fill="#F6FAFD"/>',
           f'<path d="M{x} {base} C{x - 2} {base - 20} {x + 3} {base - 34} {x + 1} {base - 52}" fill="none" stroke="{BARK}" stroke-width="3" stroke-linecap="round"/>',
           f'<path d="M{x + 0.5} {base - 30} Q{x - 6} {base - 34} {x - 10} {base - 40} M{x + 1} {base - 40} Q{x + 7} {base - 43} {x + 10} {base - 48}" fill="none" stroke="{BARK}" stroke-width="1.6" stroke-linecap="round"/>']
    for lx, ly, ang, col in leaves:
        out.append(f'<ellipse cx="{lx}" cy="{ly}" rx="6" ry="3" fill="{col}" transform="rotate({ang} {lx} {ly})"/>')
    tuft = random.Random(1)
    out.append(clump(x + 1, base - 55, 9.5, BLOSSOM["shadow"], tuft) + clump(x + 1, base - 57, 9, BLOSSOM["mid"], tuft)
               + snow_cap(x + 1, base - 57, 9, tuft))
    return "\n".join(out)


def life_tree(rng, n, g):
    """You, as the last living tree. It grows with your number of public repos."""
    if n == 0:
        return f'<g transform="translate(600 {GROUND + 2}) scale(1.5) translate(-600 -{GROUND + 2})">{sapling(600, GROUND + 2)}</g>', 0
    depth = 3 + round(4 * g)
    trunk_len, trunk_w, leaf_scale = 46 + 76 * g, 7 + 25 * g, 0.5 + 0.5 * g
    segs, tips = [], []

    def grow(x0, y0, ang, ln, d, wd):
        x1, y1 = x0 + ln * math.cos(ang), y0 + ln * math.sin(ang)
        segs.append((x0, y0, x1, y1, wd, d))
        if d in (1, 2):
            tips.append((x1, y1, d))
        if d == 0:
            return
        spread = 26 if d > 5 else 34
        kids = 3 if d in (6, 5) and rng.random() < 0.5 else 2
        for k in range(kids):
            off = ((-1 if k == 0 else 1) * rng.uniform(12, spread)) if kids == 2 else (-spread, 0, spread)[k] + rng.uniform(-6, 6)
            na = ang + math.radians(off)
            na += (-math.pi / 2 - na) * 0.12
            grow(x1, y1, na, ln * rng.uniform(0.76, 0.86), d - 1, wd * 0.64)

    grow(600, GROUND + 4, -math.pi / 2, trunk_len, depth, trunk_w)

    fork_y = segs[0][3]
    rx = 60 + 150 * g

    # front crown, as in the original design: blossom clumps on the tops of the branches
    front = []
    if g < 0.35:
        # young tree (1 or 2 repos): a domed front crown, full down to its sides, with the branches fitted inside
        R = 36 + 80 * g
        dcy = fork_y - R * 0.55
        rc_f = R * 0.42
        pts_all = [(a, b) for a, b, _, _, _, _ in segs] + [(c, d) for _, _, c, d, _, _ in segs]
        maxdx = max((abs(x - 600) for x, _ in pts_all), default=1) or 1
        min_y = min((y for _, y in pts_all), default=fork_y)
        kx = min(1.0, R * 0.7 / maxdx)
        ky = min(1.0, (fork_y - (dcy - R * 0.55)) / max(fork_y - min_y, 1))
        fit = lambda x, y: (600 + (x - 600) * kx, y if y >= fork_y else fork_y - (fork_y - y) * ky)
        segs = [(*fit(a, b), *fit(c, d), w, dep) for a, b, c, d, w, dep in segs]
        n_arc = 9
        for q in range(n_arc):
            t = math.pi + math.pi * q / (n_arc - 1)
            front.append((600 + (R - rc_f * 0.8) * math.cos(t) * 1.15, dcy + (R - rc_f * 0.8) * math.sin(t) + 4, rc_f * rng.uniform(0.95, 1.08)))
        for dx in (-0.45, 0, 0.45):
            front.append((600 + dx * R, dcy - R * 0.1 + abs(dx) * R * 0.3, rc_f * 1.1))
    else:
        for x, y, d in tips:
            r = rng.uniform(22, 36) * (1.1 if d == 2 else 0.85) * leaf_scale
            front.append((x + rng.uniform(-6, 6), y, r))
    line = None
    if front and g >= 0.35:
        # keep the crown balanced: trim whichever side leans further out than the other
        left_ext = 600 - min(x - r for x, _, r in front)
        right_ext = max(x + r for x, _, r in front) - 600
        half = min(left_ext, right_ext) * 1.04
        trimmed = []
        for x, y, r in front:
            over = max((600 - half) - (x - r), (x + r) - (600 + half))
            r = r - max(over, 0)
            if r >= 8:
                trimmed.append((x, y, r))
        front = trimmed
        # bring the front down to a gently curved line about half way to the fork, so it reads as a full crown;
        # the darker back still wraps round underneath it
        ftop0 = min(y - r for _, y, r in front)
        avg_r = sum(c[2] for c in front) / len(front)
        span = fork_y - ftop0

        def floor_at(x):
            u = (x - 600) / half
            return ftop0 + span * (0.6 - 0.1 * u * u)

        bottom_mid = floor_at(600)
        hw_max = half - avg_r * 0.85

        def dome_top(x):  # rounded shoulders: the filled area drops away towards the sides
            u = (x - 600) / max(hw_max, 1)
            return ftop0 + avg_r * 0.9 + 0.5 * (bottom_mid - ftop0) * u * u

        # the front's lower edge is one clean line: straight sides, rounded corners, a gentle sag across the bottom
        W = half - avg_r * 0.1
        y_line = bottom_mid + avg_r * 0.15
        line = (W, y_line, W * 0.03, min(avg_r * 1.6, W * 0.3))
        hw = W - avg_r * 0.5
        yy = ftop0 + avg_r
        while yy <= y_line + avg_r * 0.4:
            n_row = max(1, int(2 * hw / (avg_r * 1.15)) + 1)
            for q in range(n_row):
                x = 600 - hw + 2 * hw * q / max(n_row - 1, 1) if n_row > 1 else 600
                x += rng.uniform(-3, 3)
                if dome_top(x) <= yy:
                    front.append((x, yy + rng.uniform(-3, 3), avg_r * rng.uniform(0.95, 1.08)))
            yy += avg_r * 1.0
    ftop = min((y - r for _, y, r in front), default=fork_y - 60)
    fbot = max((y + r for _, y, r in front), default=fork_y)
    fleft = min((x - r for x, _, r in front), default=560)
    fright = max((x + r for x, _, r in front), default=640)

    def under_front(x, y):
        return any(math.hypot(x - fx, y - fy) < fr for fx, fy, fr in front)

    def front_floor(x):
        ys = [fy + math.sqrt(max(0.0, fr * fr - (x - fx) ** 2)) for fx, fy, fr in front if abs(x - fx) < fr]
        return max(ys) if ys else -1e9

    def line_y(x):
        return 1e9

    if line:
        _, yl_, sag_, rcn_ = line
        low = [c for c in front if c[1] + c[2] > yl_ - 2]
        Lx = min((x - r for x, _, r in low), default=560) + 3
        Rx = max((x + r for x, _, r in low), default=640) - 3
        line = (Lx, Rx, yl_, sag_, rcn_)

        def line_y(x):
            if Lx <= x <= Rx:
                u = (x - (Lx + Rx) / 2) / max((Rx - Lx) / 2, 1)
                return yl_ + sag_ * (1 - u * u)
            return yl_ - rcn_

    # back of the crown: a slightly smaller rounded mass behind the branches, wrapped round the top of the trunk,
    # never showing above or outside the front tops
    # the back spans the full width: its sides reach out under the ends of the front crown
    bcx = (fleft + fright) / 2
    rc = 14 + 12 * g
    brx = (fright - fleft) / 2 - rc * 0.5
    ends = sorted(front, key=lambda c: c[0])
    side_y = (ends[0][1] + ends[-1][1]) / 2 if ends else fork_y - 40
    btop = min(ftop + 0.32 * (fork_y - ftop), side_y - 10)
    bbot = fork_y + 6 * leaf_scale
    bcy = min(side_y, bbot - 20)
    up, down = bcy - btop, bbot - bcy

    def oval_y(t, scale=1.0):  # egg shaped: shallower above the widest line, deeper below it
        return bcy + (down if math.sin(t) > 0 else up) * scale * math.sin(t)

    cand = []
    n_rim = max(12, int(2 * math.pi * math.sqrt((brx * brx + ((up + down) / 2) ** 2) / 2) / (rc * 1.15)))
    for q in range(n_rim):
        t = 2 * math.pi * q / n_rim + rng.uniform(-0.04, 0.04)
        cand.append((bcx + (brx - rc * 0.85) * math.cos(t), oval_y(t) - rc * 0.85 * math.sin(t), rc * rng.uniform(0.95, 1.1)))
    step, yy = rc * 1.25, btop + rc
    while yy < bbot:
        xx = bcx - brx
        while xx < bcx + brx:
            jx, jy = xx + rng.uniform(-4, 4), yy + rng.uniform(-4, 4)
            half = (down if jy > bcy else up) * 0.8
            if half > 0 and ((jx - bcx) / (brx * 0.82)) ** 2 + ((jy - bcy) / half) ** 2 <= 1:
                cand.append((jx, jy, rc * rng.uniform(1.0, 1.15)))
            xx += step
        yy += step
    back = []
    for x, y, r in cand:
        while r >= 7 and not ((under_front(x, y - r) and y - r < line_y(x)) or
                              y - r > min(front_floor(x) if front_floor(x) > -1e8 else 1e9, line_y(x)) - 4):
            r -= 2
        if r >= 7:
            back.append((x, y, r))

    out = [f'<linearGradient id="crownback" gradientUnits="userSpaceOnUse" x1="0" y1="{fmt(btop)}" x2="0" y2="{fmt(bbot)}">'
           f'<stop offset="0" stop-color="#D97A9E"/><stop offset="1" stop-color="#A3436C"/></linearGradient>']
    out.append("".join(clump(x, y + 6 * leaf_scale, r, "#8E3A60", rng, 18) for x, y, r in back))
    out.append("".join(clump(x, y, r, "url(#crownback)", rng, 20) for x, y, r in back))

    # a few pink vines come down out of the crown and wind round the trunk to its foot
    n_vines = 1 if g < 0.3 else 2 if g < 0.7 else 3
    vine_back, vine_front = [], []
    half_w = trunk_w / 2 + 1.5
    for k in range(n_vines):
        side = -1 if k % 2 == 0 else 1
        x0 = 600 + side * (fright - fleft) / 2 * rng.uniform(0.25, 0.42)
        y0 = max(fork_y - 0.45 * (fork_y - ftop), front_floor(x0) - 14)
        if line:
            y0 = min(y0, line[2] - 8)
        ph = k * 2 * math.pi / n_vines + rng.uniform(-0.3, 0.3)
        turns = 1.2 + 1.3 * g
        path = []
        for q in range(13):  # drape from the crown to the fork
            t = q / 12
            path.append((x0 + (600 + half_w * math.sin(ph) - x0) * (t ** 1.4), y0 + (fork_y - y0) * t, 1.0))
        steps = max(24, int((GROUND - fork_y) / 3))
        for q in range(1, steps + 1):  # spiral round the trunk
            t = q / steps
            a = ph + t * turns * 2 * math.pi
            path.append((600 + half_w * math.sin(a), fork_y + (GROUND - 2 - fork_y) * t, math.cos(a)))
        runs, cur, vis = [], [], None
        for x, y, z in path:
            v = z >= 0
            if vis is None or v == vis:
                cur.append((x, y))
            else:
                runs.append((vis, cur))
                cur = [cur[-1], (x, y)]
            vis = v
        runs.append((vis, cur))
        total_y = GROUND - y0
        for vis, run in runs:
            if len(run) < 2:
                continue
            frac = (run[-1][1] - run[0][1]) / max(total_y, 1)
            delay = 0.5 + 0.2 * k + 3.4 * (run[0][1] - y0) / max(total_y, 1)
            el = (f'<path class="vine" d="{poly(run)}" pathLength="1" fill="none" stroke="{"#E27BA2" if vis else "#9E3462"}" stroke-width="{fmt(2 + 1.2 * g)}" '
                  f'stroke-linecap="round" style="animation-delay:{delay:.2f}s;animation-duration:{max(0.3, 3.4 * frac):.2f}s"/>')
            (vine_front if vis else vine_back).append(el)
            if vis:
                for j, (fx, fy) in enumerate(run[1::4]):
                    fd = 0.5 + 0.2 * k + 3.4 * (fy - y0) / max(total_y, 1)
                    vine_front.append(f'<g class="leaf" style="animation-delay:{fd:.2f}s">{flower(fx + (3 if j % 2 else -3), fy, 3.4 + 1.4 * g)}</g>')
    out.extend(vine_back)

    root_w = max(2.5, trunk_w * 0.3)
    for side in (-1, 1):
        for k in range(2):
            ex = 600 + side * rng.uniform(38, 70) * (k + 1) * 0.8 * (0.4 + 0.6 * g)
            out.append(f'<path d="M600 {fmt(GROUND - 26 * g)} Q{fmt(600 + side * 14 * g)} {GROUND - 2} {fmt(ex)} {GROUND + 8 + k * 3}" fill="none" stroke="{BARK}" stroke-width="{fmt(root_w * (1 - k * 0.35))}" stroke-linecap="round"/>')
    for a, b, c, d, w, dep in segs:
        if dep == 0:
            continue
        out.append(f'<line x1="{fmt(a)}" y1="{fmt(b)}" x2="{fmt(c)}" y2="{fmt(d)}" stroke="{BARK}" stroke-width="{max(w, 0.8):.1f}" stroke-linecap="round"/>')
        if w > 11:  # cherry bark: faint horizontal lenticel stripes
            ln = math.hypot(c - a, d - b)
            ux, uy = (c - a) / ln, (d - b) / ln
            t = rng.uniform(6, 12)
            while t < ln - 4:
                mx, my = a + ux * t, b + uy * t
                hw = w * rng.uniform(0.12, 0.26)
                off = rng.uniform(-w * 0.15, w * 0.15)
                out.append(f'<line x1="{fmt(mx - uy * (hw - off))}" y1="{fmt(my + ux * (hw - off))}" x2="{fmt(mx + uy * (hw + off))}" y2="{fmt(my - ux * (hw + off))}" stroke="{BARK_LIGHT}" stroke-width="1.1" stroke-linecap="round" opacity="0.35"/>')
                t += rng.uniform(8, 16)
        if w > 4:
            out.append(f'<line x1="{fmt(a - w * 0.18)}" y1="{fmt(b)}" x2="{fmt(c - w * 0.18)}" y2="{fmt(d)}" stroke="#E9F1F7" stroke-width="{w * 0.12:.1f}" stroke-linecap="round" opacity="0.5"/>')

    out.extend(vine_front)

    # front crown on top of everything: light at the top, lit from the sun side, darker underside
    shapes = [clump_d(x, y, r, rng) for x, y, r in front]
    out.append(f'<linearGradient id="crown" gradientUnits="userSpaceOnUse" x1="0" y1="{fmt(ftop)}" x2="0" y2="{fmt(fbot)}">'
               f'<stop offset="0" stop-color="{BLOSSOM["light"]}"/><stop offset="0.55" stop-color="#F09DBA"/>'
               f'<stop offset="1" stop-color="{BLOSSOM["mid"]}"/></linearGradient>'
               f'<radialGradient id="crownlight" gradientUnits="userSpaceOnUse" cx="{fmt(fright - (fright - fleft) * 0.2)}" cy="{fmt(ftop)}" r="{fmt((fright - fleft) * 0.75)}">'
               f'<stop offset="0" stop-color="#FFFFFF" stop-opacity="0.35"/><stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/></radialGradient>'
               f'<clipPath id="crownclip">{"".join(f"<path d=\"{sd}\"/>" for sd in shapes)}</clipPath>')
    cut, cut_s = "", ""
    if line:
        L, R, yl, sag, rcn = line
        scal = max(5.0, 9 * leaf_scale)

        def quad(p0, p1, p2, n):
            return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                     (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]) for t in (q / n for q in range(1, n + 1))]

        def cut_d(dy):
            """Even lower edge with rounded corners and small scalloped lobes; above the corners the sides are untouched."""
            B = yl + dy
            base = [(L, B - rcn)] + quad((L, B - rcn), (L, B), (L + rcn, B), 10)
            base += quad((L + rcn, B), ((L + R) / 2, B + 2 * sag), (R - rcn, B), max(10, int((R - L) / 3)))
            base += quad((R - rcn, B), (R, B), (R, B - rcn), 10)
            pts, s_len = [], 0.0
            for i, (x, y) in enumerate(base):
                if i:
                    s_len += math.hypot(x - base[i - 1][0], y - base[i - 1][1])
                a, b = base[max(i - 1, 0)], base[min(i + 1, len(base) - 1)]
                tx, ty = b[0] - a[0], b[1] - a[1]
                ln = math.hypot(tx, ty) or 1
                nx, ny = ty / ln, -tx / ln
                bump = scal * (0.6 * abs(math.sin(math.pi * s_len / (scal * 1.7))) - 0.25)
                pts.append((x + nx * bump, y + ny * bump))
            return (f"M-10 -10 L-10 {fmt(B - rcn)} " + " ".join(f"L{fmt(x)} {fmt(y)}" for x, y in pts)
                    + f" L1210 {fmt(B - rcn)} L1210 -10 Z")

        out.append(f'<clipPath id="frontcut"><path d="{cut_d(0)}"/></clipPath><clipPath id="frontcut_s"><path d="{cut_d(6 * leaf_scale)}"/></clipPath>')
        cut, cut_s = ' clip-path="url(#frontcut)"', ' clip-path="url(#frontcut_s)"'
    out.append(f'<g{cut_s}>' + "".join(clump(x, y + 6 * leaf_scale, r * 1.02, BLOSSOM["shadow"], rng, 20) for x, y, r in front) + "</g>")
    out.append(f'<g{cut}>')
    out.append("".join(f'<path d="{sd}" fill="url(#crown)"/>' for sd in shapes))

    # texture: each puff of blossom overlaps the one below it with a soft shadowed edge,
    # catches a little light on its upper side, and the surface carries a fine petal grain
    tex = []
    for x, y, r in sorted(front, key=lambda c: -c[1]):
        tex.append(clump(x + 2 * leaf_scale, y + 3 * leaf_scale, r, "#DD7499", rng, 22, 0.5))
        tex.append(clump(x, y, r * 0.97, "url(#crown)", rng, 22))
    out.append(puff_pattern("puffs1", 46, 40, 11, 6.5, 10, 9) + puff_pattern("puffs2", 62, 54, 23, 8, 13, 9))
    out.append(f'<radialGradient id="crowndepth" gradientUnits="userSpaceOnUse" cx="600" cy="{fmt(ftop + (fbot - ftop) * 0.3)}" '
               f'r="{fmt(max(fright - fleft, fbot - ftop) * 0.62)}"><stop offset="0.55" stop-color="#D8739A" stop-opacity="0"/>'
               f'<stop offset="1" stop-color="#C95F8A" stop-opacity="0.45"/></radialGradient>')
    tex.append(f'<rect x="{fmt(fleft)}" y="{fmt(ftop)}" width="{fmt(fright - fleft)}" height="{fmt(fbot - ftop + 12)}" fill="url(#puffs2)" opacity="0.45"/>')
    tex.append(f'<rect x="{fmt(fleft)}" y="{fmt(ftop)}" width="{fmt(fright - fleft)}" height="{fmt(fbot - ftop + 12)}" fill="url(#puffs1)" opacity="0.55"/>')
    for x, y, r in front:
        tex.append(clump(x - r * 0.28, y - r * 0.3, r * 0.42, "#FFE6EF", rng, 14, 0.18))
    area = (fright - fleft) * (fbot - ftop)
    for _ in range(int(area / 700)):
        px, py = rng.uniform(fleft, fright), rng.uniform(ftop, fbot)
        col, op = ("#FFE3EE", 0.75) if rng.random() < 0.55 else ("#CF5F8A", 0.45)
        tex.append(f'<ellipse cx="{fmt(px)}" cy="{fmt(py)}" rx="{rng.uniform(1.4, 2.6):.1f}" ry="{rng.uniform(0.9, 1.5):.1f}" fill="{col}" opacity="{op}" '
                   f'transform="rotate({rng.randint(0, 179)} {fmt(px)} {fmt(py)})"/>')
    out.append(f'<filter id="petalgrain" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" seed="7"/>'
               f'<feColorMatrix type="matrix" values="0 0 0 0 0.62  0 0 0 0 0.16  0 0 0 0 0.36  0 0 0 -1.4 0.75"/></filter>')
    out.append(f'<g clip-path="url(#crownclip)">{"".join(tex)}'
               f'<rect x="{fmt(fleft)}" y="{fmt(ftop)}" width="{fmt(fright - fleft)}" height="{fmt(fbot - ftop + 12)}" filter="url(#petalgrain)" opacity="0.22"/>'
               f'<rect x="{fmt(fleft)}" y="{fmt(ftop)}" width="{fmt(fright - fleft)}" height="{fmt(fbot - ftop + 12)}" fill="url(#crowndepth)"/>'
               f'<rect x="{fmt(fleft)}" y="{fmt(ftop)}" width="{fmt(fright - fleft)}" height="{fmt(fbot - ftop + 12)}" fill="url(#crownlight)"/></g>')
    out.append("</g>")

    # snow lying along the whole top of the crown: it fills the dips between puffs,
    # is thickest where the crown is flat and slides off where it curves away
    xs = [fleft + 2 * i for i in range(int((fright - fleft) / 2) + 1)]

    def top_at_x(x):
        ys = [cy0 - math.sqrt(r * r - (x - cx0) ** 2) for cx0, cy0, r in front if abs(x - cx0) < r]
        return min(ys) if ys else None

    tops = [top_at_x(x) for x in xs]
    pts = [(x, t) for x, t in zip(xs, tops) if t is not None]
    if len(pts) > 6:
        bridged = [min(t for _, t in pts[max(0, i - 4):i + 5]) for i in range(len(pts))]
        bridged = [sum(bridged[max(0, i - 5):i + 6]) / len(bridged[max(0, i - 5):i + 6]) for i in range(len(bridged))]
        T = 5 + 9 * g
        ph = rng.uniform(0, 6.3)
        ths, ok = [], []
        for i, (x, t) in enumerate(pts):
            j0, j1 = max(0, i - 3), min(len(pts) - 1, i + 3)
            slope = (bridged[j1] - bridged[j0]) / max(pts[j1][0] - pts[j0][0], 1)
            raw = (pts[j1][1] - pts[j0][1]) / max(pts[j1][0] - pts[j0][0], 1)
            th = T * (1 - abs(slope) * 0.75) + 1.4 * math.sin(x / 7 + ph)
            ths.append(th)
            ok.append(th > 1.5 and abs(raw) < 0.85 and abs(slope) < 0.85)
        runs = []
        if any(ok):
            L, R = ok.index(True), len(ok) - 1 - ok[::-1].index(True)
            run = []
            for i in range(L, R + 1):
                x, t = pts[i]
                edge = max(0.0, min(1.0, (i - L) / 8, (R - i) / 8))
                top_edge = bridged[i] * edge + t * (1 - edge)
                run.append((x, top_edge - 1.2, max(t, top_edge) + max(ths[i], 2.5) * edge + 0.6))
            runs.append(run)
        for run in runs:
            if len(run) < 4:
                continue
            upper = [(x, a) for x, a, _ in run]
            lower = [(x, b) for x, _, b in run]
            # round the ends of each patch of snow
            lower[0] = (lower[0][0], upper[0][1] + 0.5)
            lower[-1] = (lower[-1][0], upper[-1][1] + 0.5)
            out.append(f'<path d="{poly(upper + [(x, y + 2.5) for x, y in lower[::-1]], True)}" fill="#C9D8E5" opacity="0.8"/>')
            out.append(f'<path d="{poly(upper + lower[::-1], True)}" fill="#F7FAFD"/>')
            for x, y in lower[3:-3:8]:
                if rng.random() < 0.35:
                    out.append(f'<ellipse cx="{fmt(x)}" cy="{fmt(y + 1)}" rx="{rng.uniform(2, 3.5):.1f}" ry="{rng.uniform(2.5, 4.5):.1f}" fill="#F7FAFD"/>')
            out.append(f'<path d="{poly(upper)}" fill="none" stroke="#FFFFFC" stroke-width="1.4" opacity="0.9"/>')

    out.append(petals(rng, (fleft + 20, ftop + 20, fright - 20, GROUND - 140 * g), int(8 + 26 * g), 0))
    return "\n".join(out), trunk_w


def signboard(cx, cy, size, post=False):
    """Wooden sign with your profile picture, nailed to the trunk or standing on its own post."""
    b = size + 16
    x0, y0 = cx - b / 2, cy - b / 2
    out = []
    if post:
        out.append(f'<rect x="{fmt(cx - 4)}" y="{fmt(cy)}" width="8" height="{fmt(GROUND + 4 - cy)}" fill="#5A3E30"/>'
                   f'<rect x="{fmt(cx + 1)}" y="{fmt(cy)}" width="3" height="{fmt(GROUND + 4 - cy)}" fill="#3F2B21" opacity="0.6"/>'
                   f'<ellipse cx="{fmt(cx)}" cy="{GROUND + 3}" rx="16" ry="4.5" fill="#F6FAFD"/>')
    out.append(f'<g transform="rotate(-3 {fmt(cx)} {fmt(cy)})">')
    out.append(f'<rect x="{fmt(x0)}" y="{fmt(y0)}" width="{fmt(b)}" height="{fmt(b)}" rx="5" fill="#6B4B3A"/>')
    for gy in (0.22, 0.5, 0.78):
        out.append(f'<path d="M{fmt(x0 + 4)} {fmt(y0 + b * gy)} H{fmt(x0 + b - 4)}" stroke="#5A3E30" stroke-width="1.1"/>')
    out.append(f'<rect x="{fmt(cx - size / 2 - 2)}" y="{fmt(cy - size / 2 - 2)}" width="{fmt(size + 4)}" height="{fmt(size + 4)}" rx="6" fill="#3F2B21"/>')
    out.append(avatar(cx - size / 2, cy - size / 2, size, "signpfp", rx=5))
    for nx, ny in ((x0 + 5, y0 + 5), (x0 + b - 5, y0 + 5), (x0 + 5, y0 + b - 5), (x0 + b - 5, y0 + b - 5)):
        out.append(f'<circle cx="{fmt(nx)}" cy="{fmt(ny)}" r="1.8" fill="#C9CED6"/>')
    out.append(f'<path d="M{fmt(x0 - 2)} {fmt(y0 + 3)} Q{fmt(x0 - 1)} {fmt(y0 - 5)} {fmt(x0 + 10)} {fmt(y0 - 5)} H{fmt(x0 + b - 10)} '
               f'Q{fmt(x0 + b + 1)} {fmt(y0 - 5)} {fmt(x0 + b + 2)} {fmt(y0 + 3)} Q{fmt(x0 + b * 0.75)} {fmt(y0 + 6)} {fmt(x0 + b * 0.62)} {fmt(y0 + 3)} '
               f'Q{fmt(x0 + b * 0.55)} {fmt(y0 + 9)} {fmt(x0 + b * 0.48)} {fmt(y0 + 3)} Q{fmt(x0 + b * 0.25)} {fmt(y0 + 6)} {fmt(x0 - 2)} {fmt(y0 + 3)} Z" fill="#F6FAFD"/>')
    out.append("</g>")
    return "\n".join(out)


def tower(rng, r, cx, i, P, label_w=140):
    w, h = 76 + 34 * r["norm"], 165 + 205 * r["norm"]
    x0, x1, top = cx - w / 2, cx + w / 2, GROUND - h
    pts = jag_top(rng, x0, x1, top, True)
    shape = poly([(x0, GROUND)] + pts + [(x1, GROUND)], True)
    out = [f'<path d="{shape}" fill="url(#concrete)"/>',
           f'<rect x="{fmt(x1 - 12)}" y="{fmt(top)}" width="12" height="{fmt(h)}" fill="#0E1520" opacity="0.22" clip-path="url(#tc{i})"/>']
    clip = f'<clipPath id="tc{i}"><path d="{shape}"/></clipPath>'
    cols = max(2, int((w - 18) // 17))
    gap = (w - 18 - cols * 10) / max(cols - 1, 1)
    lit, k = set(rng.sample(range(200), min(r.get("stars", 0), 6))), 0
    for wy in range(int(top + 26), GROUND - 22, 24):
        for c in range(cols):
            wx = x0 + 9 + c * (10 + gap)
            if wy < top_at(pts, wx + 5) + 10:
                continue
            k += 1
            if k in lit:
                out.append(f'<rect x="{fmt(wx - 3)}" y="{wy - 3}" width="16" height="20" fill="#FFD48A" opacity="0.35" filter="url(#warm)"/><rect x="{fmt(wx)}" y="{wy}" width="10" height="14" fill="#FFD48A"/>')
            else:
                out.append(f'<rect x="{fmt(wx)}" y="{wy}" width="10" height="14" fill="#263140"/>')
            out.append(f'<rect x="{fmt(wx - 2)}" y="{wy + 14}" width="14" height="2.6" rx="1.2" fill="#F6FAFD"/>')
            if rng.random() < 0.3:
                ix, il = wx + rng.uniform(1, 9), rng.uniform(3, 8)
                out.append(f'<path d="M{fmt(ix - 1.3)} {wy + 16.4} L{fmt(ix + 1.3)} {wy + 16.4} L{fmt(ix)} {fmt(wy + 16.4 + il)} Z" fill="#DDF3FA"/>')
    for _ in range(2):
        sx, sy = rng.uniform(x0 + 8, x1 - 8), rng.uniform(top + 40, GROUND - 40)
        out.append(f'<path d="M{fmt(sx)} {fmt(sy)} l{fmt(rng.uniform(-8, 8))} 12 l{fmt(rng.uniform(-6, 6))} 10 l{fmt(rng.uniform(-8, 8))} 14" fill="none" stroke="#1C2533" stroke-width="1.2" opacity="0.6"/>')
    out.append(f'<path d="{poly(pts)}" fill="none" stroke="#F6FAFD" stroke-width="6" stroke-linejoin="round" stroke-linecap="round"/>')
    nv = len(r["top"])
    for j, (lang, share) in enumerate(r["top"]):
        vx = x0 + (j + 1) * w / (nv + 1) + rng.uniform(-6, 6)
        vh = min(h * (0.3 + 0.62 * share ** 0.7), GROUND - top_at(pts, vx) - 8)
        col, leaf = P[lang], tone(P[lang], 0.08)
        amp, per, ph = rng.uniform(2.5, 4), rng.uniform(48, 70), rng.uniform(0, 6)
        vp = [(vx + amp * math.sin(ph + yy / per * 2 * math.pi), GROUND + 2 - yy) for yy in range(0, int(vh), 5)]
        if len(vp) < 2:
            continue
        out.append(f'<path class="vine" d="{poly(vp)}" pathLength="1" fill="none" stroke="{col}" stroke-width="2.6" stroke-linecap="round" style="animation-delay:{0.3 * i + 0.2 * j:.1f}s"/>')
        for q, (lx, ly) in enumerate(vp[3::3]):
            side = 1 if q % 2 else -1
            delay = 0.3 * i + 0.2 * j + 3.2 * (GROUND - ly) / max(vh, 1)
            out.append(f'<g transform="translate({fmt(lx)} {fmt(ly)}) rotate({side * 40})"><ellipse class="leaf" cx="{side * 6}" cy="0" rx="6" ry="2.8" fill="{leaf}" style="animation-delay:{delay:.2f}s"/></g>')
    front = (f'<ellipse cx="{fmt(cx)}" cy="{GROUND + 1}" rx="{fmt(w * 0.62)}" ry="8" fill="#F6FAFD"/>'
             + tpath("mono5", fit("mono5", r["name"], 13, label_w), 13, cx, 596, NAVY, 0.85, anchor="middle"))
    return clip, "\n".join(out), (x0, x1), front


def stump(cx, cy, shown, shares, P, rng):
    """Tree stump cross section: one ring per language, thickness by share, biggest at the core."""
    rx, ry, side = 172, 56, 54
    k = ry / rx
    out = [f'<ellipse cx="{cx + 34}" cy="{cy + side + 16}" rx="{rx + 6}" ry="{ry * 0.5}" fill="#C3D1DE" opacity="0.35"/>',
           f'<path d="M{cx - rx} {cy} V{cy + side} A{rx} {ry} 0 0 0 {cx + rx} {cy + side} V{cy} Z" fill="url(#bark)"/>']
    for gx in range(int(cx - rx + 10), int(cx + rx - 6), 13):
        dx = (gx - cx) / rx
        y_top = cy + ry * math.sqrt(max(0, 1 - dx * dx))
        out.append(f'<path d="M{gx} {fmt(y_top + 2)} q{rng.uniform(-3, 3):.1f} {side * 0.5:.1f} {rng.uniform(-2, 2):.1f} {side - 4:.1f}" stroke="#241B16" stroke-width="1.4" opacity="0.5" fill="none"/>')
    out.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="#3B2E26"/>')
    inner = rx - 10
    weights = [max(shares.get(l, 0), 0.012) for l in shown]
    tot = sum(weights) or 1
    radii, acc = [], 0.0
    for wgt in weights:
        acc += wgt / tot * inner
        radii.append(acc)
    for lang, rr in reversed(list(zip(shown, radii))):
        out.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{fmt(rr)}" ry="{fmt(rr * k)}" fill="{P[lang]}" stroke="{tone(P[lang], -0.12)}" stroke-width="1"/>')
    for a in (0.4, 1.9, 3.5, 4.6):
        r0, r1 = rng.uniform(4, 20), rng.uniform(inner * 0.55, inner * 0.95)
        out.append(f'<path d="M{fmt(cx + r0 * math.cos(a))} {fmt(cy + r0 * k * math.sin(a))} L{fmt(cx + r1 * math.cos(a + 0.05))} {fmt(cy + r1 * k * math.sin(a + 0.05))}" stroke="#1E1612" stroke-width="1.3" opacity="0.45"/>')
    # snow crescent along the back rim
    outer, inner_edge = [], []
    for q in range(41):
        t = math.pi * 1.06 + (math.pi * 0.72) * q / 40
        bulge = math.sin(math.pi * q / 40)
        outer.append((cx + (rx + 2) * math.cos(t), cy + (ry + 2) * math.sin(t) - 7 * bulge))
        dr = 4 + 14 * bulge + rng.uniform(-1.5, 1.5)
        inner_edge.append((cx + (rx - dr) * math.cos(t), cy + (ry - dr * k) * math.sin(t)))
    out.append(f'<path d="{poly(outer + inner_edge[::-1], True)}" fill="#F6FAFD"/>')
    # snow banked against the foot of the stump, all the way round the front
    base_y = cy + side
    top_edge = [(cx - rx - 40, base_y + 10), (cx - rx - 14, base_y - 2)]
    for q in range(49):
        t = math.pi - math.pi * q / 48
        lift = 9 + 5 * math.sin(3 * t + 0.6) ** 2 + rng.uniform(-1, 1)
        top_edge.append((cx + (rx + 3) * math.cos(t), base_y + (ry + 3) * math.sin(t) - lift))
    top_edge += [(cx + rx + 14, base_y - 2), (cx + rx + 40, base_y + 10)]
    lower = [(cx + (rx + 40) * math.cos(math.pi * q / 32), base_y + 10 + (ry + 6) * math.sin(math.pi * q / 32)) for q in range(33)]
    out.append(f'<path d="{poly(top_edge + lower, True)}" fill="url(#bank)"/>')
    out.append(f'<path d="{poly(top_edge[2:-2])}" fill="none" stroke="#D5E0EA" stroke-width="1.2"/>')
    for _ in range(18):
        a, rr = rng.uniform(0, 2 * math.pi), rng.uniform(10, inner)
        out.append(f'<circle cx="{fmt(cx + rr * math.cos(a))}" cy="{fmt(cy + rr * k * math.sin(a))}" r="{rng.uniform(0.6, 1.4):.1f}" fill="#F6FAFD" opacity="0.8"/>')
    return "\n".join(out)


NIGHT = {
    # sky, far and near ruins, fog
    "#AEBFD0": "#0A0F2C", "#CBD7E3": "#141C42", "#E7EDF3": "#26315C",
    "#B4C3D2": "#222D52", "#94A8BB": "#18203F", "#FEFEFF": "#3C4A78",
    # moonlit snow
    "#F6FAFD": "#B8C6E0", "#F7FAFD": "#C2CFE6", "#EEF3F7": "#8E9DBE",
    "#F7FAFC": "#56658C", "#EEF3F6": "#3A4870", "#E2E9F0": "#283459",  # the open snowfield, darker so cream text reads on it
    "#D3DEE8": "#7D8CB0", "#DCE5EE": "#4A5880", "#C3D3E0": "#7F8FB0", "#C9D8E5": "#6E7DA3", "#FFFFFC": "#D6E0F2",
    "#FAFCFE": "#B3C1DC", "#F3F7FA": "#A2B1CF", "#E9EFF4": "#8E9DBE", "#C3D1DE": "#5A6890", "#DDF3FA": "#9FB4D6",
    "#9FB2C6": "#7F8FB0", "#E9F1F7": "#AAB8D4",
    # pines, dead trees, towers
    "#7F95A8": "#2A3658", "#7D90A4": "#2E3A5E", "#6A7D92": "#2E3A55", "#4A5A6D": "#1C2538", "#263140": "#0E1424",
    # calendar ice tiles and their snow
    "#DCE6EF": "#26314F", "#FFFFFD": "#6F7FA6",
    # text and bars switch from navy to cream
    NAVY: CREAM,
}


def night_sky(svg, H):
    """Stars over the night version, kept off the moon and the upper ruins."""
    stars = starfield(random.Random(41), 400, 120, lambda x, y: math.hypot(x - 985, y - 128) < 70)
    return svg.replace('<circle cx="985" cy="128" r="120"', stars + '\n  <circle cx="985" cy="128" r="120"', 1)


def frost(scene, lang_totals, days, stats, colors, n_public, night=False):
    has_cal = bool(days)
    cal_top = 662
    lang_y = 1050 if has_cal else 760
    H = lang_y + 170 if lang_totals else (cal_top + 7 * 20 + 140 if has_cal else 660)
    rng = random.Random(5)
    langs_order = [k for k, _ in lang_totals]
    for r in scene:
        for k, _ in r["top"]:
            if k not in langs_order:
                langs_order.append(k)
    P = palette(langs_order, "frost-night" if night else "frost", colors)
    n = len(scene)
    g = growth(n_public)
    tree_svg, trunk_w = life_tree(random.Random(9), n_public, g)
    if g >= 0.7:
        sign_svg = signboard(600, 494, 60)
    else:
        sign_svg = signboard(600 + 46 + 30 * g, GROUND - 58, 44, post=True)

    order = sorted(scene, key=lambda r: -r["norm"])
    nl, nr = (n + 1) // 2, n // 2
    left = [88 + k * (450 - 88) / max(nl - 1, 1) for k in range(nl)] if nl > 1 else [300]
    right = [1112 - k * (1112 - 750) / max(nr - 1, 1) for k in range(nr)] if nr > 1 else [900]
    slots = []
    for k in range(max(nl, nr)):
        slots += ([left[k]] if k < nl else []) + ([right[k]] if k < nr else [])
    gap = (450 - 88) / max(max(nl, nr) - 1, 1) if max(nl, nr) > 1 else 300
    clips, towers, spans, fronts = [], [], [], []
    for i, (r, cx) in enumerate(zip(order, slots)):
        c, t, span, f = tower(random.Random(100 + i), r, cx, i, P, label_w=min(150, gap - 14))
        clips.append(c), towers.append(t), spans.append(span), fronts.append(f)

    def free(x, pad=14):
        return all(not (a - pad < x < b + pad) for a, b in spans) and abs(x - 600) > 135

    pines_bg = [pine(rng.uniform(10, 1190), 548, rng.uniform(40, 70), "#7F95A8", "#EEF3F7", rng) for _ in range(14)]
    pines_fg, tries = [], 0
    while len(pines_fg) < 7 and tries < 200:
        tries += 1
        x = rng.uniform(15, 1185)
        if free(x):
            pines_fg.append(pine(x, GROUND + rng.uniform(4, 12), rng.uniform(60, 115), "#2D4A44", "#F6FAFD", rng))

    # activity: ice tiles, moss where you worked, longest streak as a vine
    act = []
    tile_cols = ["#DCE6EF", "#A9C8B1", "#79A68A", "#4E8268", "#2F5C4A"]
    if has_cal:
        pos, pitch, months = calendar_layout(days, cal_top)
        s = pitch - 4
        for mx, m in months:
            act.append(tpath("mono", m, 12, mx, cal_top - 18, NAVY, 0.55))
        for (d, c, lv), (x, y) in zip(days, pos):
            act.append(f'<rect x="{fmt(x - s / 2)}" y="{fmt(y - s / 2)}" width="{fmt(s)}" height="{fmt(s)}" rx="3" fill="{tile_cols[lv]}"/>')
            if lv <= 1:
                act.append(f'<rect x="{fmt(x - s / 2)}" y="{fmt(y - s / 2)}" width="{fmt(s)}" height="3" rx="1.5" fill="#FFFFFD" opacity="0.9"/>')
        if stats["streak"]:
            a, b = stats["streak"]
            vp = streak_path(pos, a, b)
            act.append(f'<path class="vine" d="{poly(vp)}" pathLength="1" fill="none" stroke="#173029" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round" style="animation-delay:1s;animation-duration:5s"/>')
            for q, (x, y) in enumerate(vp):
                side = 1 if q % 2 else -1
                act.append(f'<g transform="translate({fmt(x)} {fmt(y)}) rotate({side * 40 - 90})"><ellipse class="leaf" cx="{side * 5}" cy="0" rx="5.5" ry="2.6" fill="#B8E0C2" stroke="#173029" stroke-width="0.6" style="animation-delay:{1 + 5 * q / max(len(vp), 1):.2f}s"/></g>')
        act.append(stats_row(stats, cal_top + 7 * pitch + 66, NAVY, NAVY))

    lst, shown = lang_list(lang_totals, P, 640, lang_y - 72, NAVY, "#10144518")
    total = sum(v for _, v in lang_totals) or 1
    shares = {k: v / total for k, v in lang_totals[:11]}
    if "Other" in shown:
        shares["Other"] = 1 - sum(shares.values())

    lang_line = (f'<path d="M0 {lang_y - 110} Q260 {lang_y - 126} 560 {lang_y - 108} T1200 {lang_y - 116}" fill="none" stroke="#DCE5EE" stroke-width="2"/>'
                 if lang_totals else "")
    lang_svg = (stump(320, lang_y - 14, shown, shares, P, random.Random(17))
                + pine(70, lang_y + 120, 90, "#2D4A44", "#F6FAFD", random.Random(31))
                + pine(566, lang_y + 128, 76, "#2D4A44", "#F6FAFD", random.Random(32)) + lst) if lang_totals else ""
    flakes = []
    for k in range(int(H * 0.13)):
        d = rng.uniform(14, 30)
        flakes.append(f'<circle class="f{k % 2}" cx="{fmt(rng.uniform(0, W))}" cy="-10" r="{rng.uniform(1, 2.6):.1f}" fill="#FFFFFF" '
                      f'opacity="{rng.uniform(0.6, 1):.2f}" style="animation-duration:{d:.1f}s;animation-delay:{-rng.uniform(0, d):.1f}s"/>')
    flake_shadow = "".join(f.replace('fill="#FFFFFF"', 'fill="#9FB2C6"') for f in flakes[: len(flakes) // 3])

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{NAME} on GitHub: public repositories as ruined towers around a living tree, the past year of contributions, and languages as tree rings.">
<title>{NAME}</title>
<style>
.f0,.f1{{animation-name:fall0;animation-timing-function:linear;animation-iteration-count:infinite}}
.f1{{animation-name:fall1}}
@keyframes fall0{{0%{{transform:translate(0,0)}}50%{{transform:translate(22px,{H // 2}px)}}100%{{transform:translate(0,{H + 30}px)}}}}
@keyframes fall1{{0%{{transform:translate(0,0)}}50%{{transform:translate(-20px,{H // 2}px)}}100%{{transform:translate(4px,{H + 30}px)}}}}
.fog{{animation:fog 38s ease-in-out infinite alternate}}
.fog2{{animation:fog 52s ease-in-out infinite alternate-reverse}}
@keyframes fog{{0%{{transform:translateX(-60px)}}100%{{transform:translateX(60px)}}}}
.pt0,.pt1{{transform-box:fill-box;transform-origin:center;animation-name:pt0;animation-timing-function:linear;animation-iteration-count:infinite}}
.pt1{{animation-name:pt1}}
@keyframes pt0{{0%{{transform:translate(0,0) rotate(0deg);opacity:0}}8%{{opacity:1}}50%{{transform:translate(26px,calc(var(--fall) * .5)) rotate(200deg)}}92%{{opacity:1}}100%{{transform:translate(8px,var(--fall)) rotate(400deg);opacity:0}}}}
@keyframes pt1{{0%{{transform:translate(0,0) rotate(0deg);opacity:0}}8%{{opacity:1}}50%{{transform:translate(-24px,calc(var(--fall) * .5)) rotate(-180deg)}}92%{{opacity:1}}100%{{transform:translate(-6px,var(--fall)) rotate(-380deg);opacity:0}}}}
.vine{{stroke-dasharray:1;animation:grow 3.4s ease-out both}}
@keyframes grow{{from{{stroke-dashoffset:1}}to{{stroke-dashoffset:0}}}}
.leaf{{animation:leaf .6s ease-out both}}
@keyframes leaf{{from{{opacity:0}}to{{opacity:1}}}}
.sway{{animation:sway 6s ease-in-out infinite alternate}}
@keyframes sway{{0%{{transform:rotate(-3deg)}}100%{{transform:rotate(3deg)}}}}
{REDUCED}</style>
<defs>
  <clipPath id="frame"><rect width="{W}" height="{H}" rx="18"/></clipPath>
  {"".join(clips)}
  <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#AEBFD0"/><stop offset="0.45" stop-color="#CBD7E3"/><stop offset="0.8" stop-color="#E7EDF3"/></linearGradient>
  <linearGradient id="concrete" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#6A7D92"/><stop offset="1" stop-color="#4A5A6D"/></linearGradient>
  <linearGradient id="snow" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#F7FAFC"/><stop offset="0.5" stop-color="#EEF3F6"/><stop offset="1" stop-color="#E2E9F0"/></linearGradient>
  <linearGradient id="bark" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#3A2C24"/><stop offset="0.45" stop-color="#5A4436"/><stop offset="1" stop-color="#2E231C"/></linearGradient>
  <linearGradient id="bank" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FAFCFE"/><stop offset="0.5" stop-color="#F3F7FA"/><stop offset="1" stop-color="#E9EFF4" stop-opacity="0"/></linearGradient>
  <filter id="blur30" x="-50%" y="-200%" width="200%" height="500%"><feGaussianBlur stdDeviation="28"/></filter>
  <filter id="warm" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="4"/></filter>
  <pattern id="winpat" width="14" height="18" patternUnits="userSpaceOnUse"><rect x="4" y="5" width="7" height="9" fill="#1A2533" opacity="0.13"/></pattern>
</defs>
<g clip-path="url(#frame)">
  <rect width="{W}" height="620" fill="url(#sky)"/>
  <circle cx="985" cy="128" r="120" fill="#FFFFFF" opacity="0.35" filter="url(#blur30)"/>
  <circle cx="985" cy="128" r="40" fill="#FBFDFF" opacity="0.8"/>
  {skyline(random.Random(1), 520, 70, 210, "#B4C3D2", "#EEF3F7")}
  <g class="fog"><ellipse cx="350" cy="455" rx="420" ry="40" fill="#FEFEFF" opacity="0.55" filter="url(#blur30)"/></g>
  {skyline(random.Random(2), 545, 60, 230, "#94A8BB", "#EEF3F7", windows=True)}
  {"".join(pines_bg)}
  {bare_tree(random.Random(3), 140, 548, 46, 6, "#7D90A4", 5)}{bare_tree(random.Random(4), 1050, 548, 40, 6, "#7D90A4", 4.5)}
  <g class="fog2"><ellipse cx="850" cy="500" rx="460" ry="44" fill="#FEFEFF" opacity="0.6" filter="url(#blur30)"/></g>
  {tree_svg}
  {sign_svg}
  {"".join(towers)}
  <path d="M0 {GROUND - 4} Q150 {GROUND - 14} 300 {GROUND - 2} T600 {GROUND - 6} T900 {GROUND - 1} T1200 {GROUND - 8} V{H} H0 Z" fill="url(#snow)"/>
  <path d="M0 {GROUND - 4} Q150 {GROUND - 14} 300 {GROUND - 2} T600 {GROUND - 6} T900 {GROUND - 1} T1200 {GROUND - 8}" fill="none" stroke="#D3DEE8" stroke-width="3"/>
  <path d="M0 {cal_top - 46} Q300 {cal_top - 62} 600 {cal_top - 48} T1200 {cal_top - 52}" fill="none" stroke="#DCE5EE" stroke-width="2"/>
  {lang_line}
  {"".join(fronts)}
  {"".join(pines_fg)}
  {"".join(act)}
  {lang_svg}
  {flake_shadow}
  {"".join(flakes)}
</g>
</svg>"""
    if night:
        for day_col, night_col in NIGHT.items():
            svg = svg.replace(day_col, night_col)
        svg = night_sky(svg, H)
        svg = svg.replace("<style>", "<style>" + TWINKLE_CSS, 1)
        (OUT / "frost-night.svg").write_text(svg)
    else:
        (OUT / "frost.svg").write_text(svg)


# Main ----------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", nargs="?", type=int, const=len(DEMO_REPOS), metavar="N",
                    help="draw invented demo data instead of fetching yours (optionally with N repos, to preview growth)")
    ap.add_argument("--refresh-colors", action="store_true", help="download the latest Linguist language colors first")
    args = ap.parse_args()
    colors = load_colors(args.refresh_colors)
    if args.demo is not None:
        repos, days = [dict(r) for r in DEMO_REPOS[:args.demo]], demo_calendar()
    else:
        repos = fetch_repos()
        try:
            AVATAR["href"] = fetch_avatar()
        except Exception as e:
            print(f"warning: could not load your profile picture ({e}); using a placeholder", file=sys.stderr)
        try:
            days = fetch_calendar()
        except Exception as e:  # the calendar page is HTML, so a layout change on GitHub's side can break it
            print(f"warning: could not read the contribution calendar ({e}); drawing without activity", file=sys.stderr)
            days = []
    scene, lang_totals = prepare(repos)
    stats = calendar_stats(days) if days else None
    OUT.mkdir(parents=True, exist_ok=True)
    space(scene, lang_totals, days, stats, colors, len(repos))
    frost(scene, lang_totals, days, stats, colors, len(repos))
    frost(scene, lang_totals, days, stats, colors, len(repos), night=True)
    print(f"{len(repos)} public repos ({len(scene)} drawn), {len(lang_totals)} languages, "
          f"{stats['total'] if stats else 'no'} contributions in the past year")
    for name in ("space.svg", "frost.svg", "frost-night.svg"):
        print(f"  {OUT / name}  {(OUT / name).stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
