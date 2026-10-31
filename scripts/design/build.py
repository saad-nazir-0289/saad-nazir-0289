"""Build the profile README artwork so it matches the portfolio site.

Every image comes in a light and a dark version (assets/<name>-light.svg / -dark.svg) and the README
switches between them with <picture>. Text is drawn as outlines from the site's own fonts (Manrope and
DM Sans), so it looks the same everywhere without loading web fonts.

    python scripts/design/build.py --site ../Saad-Portfolio

--site is a checkout of the portfolio (saad-nazir-0289/Saad-Portfolio); project, blog and image data
are read from it so the README stays in step with the site.
"""
import argparse
import base64
import html
import io
import json
import re
from functools import lru_cache
from pathlib import Path

import uharfbuzz as hb
from fontTools.ttLib import TTFont
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = ROOT / "assets"
SITE = "https://saadnazir.msndev.workers.dev"

THEMES = {
    "light": dict(bg="#f9faf7", ink="#23231f", muted="#62645e", accent="#b94424", line="#dce0d6",
                  card="#ffffff", soft="#e7eddd", warm="#eddcd2", tile="#ffffff8c", tileLine="#23231f1f",
                  button="#23231f", buttonText="#ffffff", hero="#23231f", heroText="#ffffff", tag="#23231f33",
                  note="#4c534b", iconAcc="#b94424"),
    "dark": dict(bg="#121615", ink="#eceee6", muted="#a9afa5", accent="#e56d4c", line="#313936",
                 card="#1e1e1e", soft="#2e3524", warm="#3c2d23", tile="#ffffff12", tileLine="#ffffff26",
                 button="#eceee6", buttonText="#151918", hero="#b94424", heroText="#ffffff", tag="#ffffff44",
                 note="#d8dccf", iconAcc="#e56d4c"),
}


# ---------------------------------------------------------------- text as outlines

class Face:
    def __init__(self, file):
        font = TTFont(HERE / "fonts" / file)
        font.flavor = None
        buf = io.BytesIO()
        font.save(buf)
        self.face = hb.Face(hb.Blob(buf.getvalue()))
        self.upem = self.face.upem

    @lru_cache(maxsize=None)
    def font(self, weight):
        f = hb.Font(self.face)
        f.set_variations({"wght": weight})
        return f

    def shape(self, text, weight):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        f = self.font(weight)
        hb.shape(f, buf, {"kern": True, "liga": True})
        return f, buf.glyph_infos, buf.glyph_positions


FACES = {"manrope": Face("manrope-latin.woff2"), "dm": Face("dm-sans-latin.woff2")}


class Pen:
    def __init__(self, x, y, s):
        self.x, self.y, self.s, self.d = x, y, s, []

    def p(self, pt):
        return f"{self.x + pt[0] * self.s:.1f} {self.y - pt[1] * self.s:.1f}"

    def moveTo(self, a): self.d.append("M" + self.p(a))
    def lineTo(self, a): self.d.append("L" + self.p(a))
    def curveTo(self, a, b, c): self.d.append("C" + " ".join(map(self.p, (a, b, c))))

    def qCurveTo(self, *pts):
        # TrueType quadratic runs: split implied on-curve points.
        *offs, end = pts
        for i, a in enumerate(offs):
            if i < len(offs) - 1:
                b = offs[i + 1]
                mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                self.d.append("Q" + self.p(a) + " " + self.p(mid))
            else:
                self.d.append("Q" + self.p(a) + " " + self.p(end))

    def closePath(self): self.d.append("Z")
    def endPath(self): pass


def width(text, size, weight=400, face="dm", track=0):
    f = FACES[face]
    _, infos, pos = f.shape(text, weight)
    return sum(p.x_advance for p in pos) * size / f.upem + track * size * max(len(infos) - 1, 0)


def outline(text, x, y, size, weight=400, face="dm", track=0, anchor="start"):
    """SVG path data for text whose baseline starts at (x, y). track is extra spacing in em."""
    f = FACES[face]
    font, infos, pos = f.shape(text, weight)
    s = size / f.upem
    w = width(text, size, weight, face, track)
    if anchor == "middle":
        x -= w / 2
    elif anchor == "end":
        x -= w
    pen_x, d = x, []
    for info, p in zip(infos, pos):
        pen = Pen(pen_x + p.x_offset * s, y - p.y_offset * s, s)
        font.draw_glyph_with_pen(info.codepoint, pen)
        d += pen.d
        pen_x += p.x_advance * s + track * size
    return "".join(d)


def text(t, x, y, size, fill, weight=400, face="dm", track=0, anchor="start", extra=""):
    return f'<path fill="{fill}"{extra} d="{outline(t, x, y, size, weight, face, track, anchor)}"/>'


def wrap(words, max_w, size, weight=400, face="dm"):
    """Greedy wrap. words: list of (word, style) pairs; style is passed through untouched."""
    space = width(" ", size, weight, face)
    lines, line, w = [], [], 0
    for word, style in words:
        ww = width(word, size, style.get("weight", weight), face)
        if line and w + space + ww > max_w:
            lines.append(line)
            line, w = [], 0
        line.append((word, style, ww))
        w += (space if len(line) > 1 else 0) + ww
    if line:
        lines.append(line)
    return lines, space


def paragraph(runs, x, y, max_w, size, lh, fill, weight=400, face="dm", max_lines=None):
    """runs: list of (text, {fill, weight}) styled spans. Returns (svg, last baseline)."""
    words = [(w, st) for t, st in runs for w in t.split()]
    lines, space = wrap(words, max_w, size, weight, face)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while sum(ww for *_, ww in last) + space * (len(last) - 1) + width("…", size, weight, face) > max_w:
            last.pop()
        word, st, _ = last[-1]
        last[-1] = (word.rstrip(".,;:") + "…", st, 0)
    out = []
    for i, line in enumerate(lines):
        cx = x
        for word, st, ww in line:
            out.append(text(word, cx, y + i * lh, size, st.get("fill", fill), st.get("weight", weight), face))
            cx += width(word, size, st.get("weight", weight), face) + space
    return "".join(out), y + (len(lines) - 1) * lh


def arrow(x, y, size, color, width_=2):
    """lucide arrow-up-right, top-left at (x, y)."""
    k = size / 24
    return (f'<g transform="translate({x} {y}) scale({k})" fill="none" stroke="{color}" stroke-width="{width_ / k:.2f}" '
            f'stroke-linecap="round" stroke-linejoin="round"><path d="M7 7h10v10M7 17 17 7"/></g>')


def svg(w, h, body, title, defs=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(title)}"><title>{html.escape(title)}</title>'
            f'{defs}{body}</svg>')


def embed(path, w, h, fmt="JPEG", quality=84, focus=0.5):
    """Crop to w:h around the focus point, resize to 2x for sharp screens and inline as a data URI."""
    im = Image.open(path).convert("RGB")
    ratio = w / h
    if im.width / im.height > ratio:
        nw = round(im.height * ratio)
        left = round((im.width - nw) * focus)
        im = im.crop((left, 0, left + nw, im.height))
    else:
        nh = round(im.width / ratio)
        top = round((im.height - nh) * focus)
        im = im.crop((0, top, im.width, top + nh))
    im = im.resize((w * 2, h * 2), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, fmt, quality=quality, optimize=True)
    return f"data:image/{fmt.lower()};base64," + base64.b64encode(buf.getvalue()).decode()


def write(name, theme, content):
    (OUT / f"{name}-{theme}.svg").write_text(content, encoding="utf-8")


# ---------------------------------------------------------------- pieces

def header(c, theme, portrait):
    W, H = 900, 452
    b = [f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="16" fill="{c["bg"]}" stroke="{c["line"]}"/>']
    bx = 40
    b.append(text("saad nazir", bx, 58, 25, c["ink"], 800, "manrope", -1.5 / 25))
    b.append(text(".", bx + width("saad nazir", 25, 800, "manrope", -1.5 / 25) - 1.5 + 1, 58, 25, c["accent"], 800, "manrope"))
    b.append(f'<circle cx="{W - 40 - width("Lahore, Pakistan", 13, 500) - 14}" cy="53.5" r="3.5" fill="#52712f"/>')
    b.append(text("Lahore, Pakistan", W - 40, 58, 13, c["muted"], 500, anchor="end"))
    b.append(f'<path d="M0 88.5H{W}" stroke="{c["line"]}"/>')
    hs, tr = 56, -.06
    b.append(text("Real problems.", bx - 2, 166, hs, c["ink"], 600, "manrope", tr))
    b.append(text("Thoughtful code.", bx - 2, 228, hs, c["ink"], 600, "manrope", tr))
    for i, word in enumerate(["Useful software.", "Smarter systems.", "Better workflows."]):
        b.append(f'<g class="w w{i + 1}">{text(word, bx - 2, 290, hs, c["accent"], 600, "manrope", tr)}</g>')
    runs = [("I’m Saad, a", {}), ("Software Engineer focused on Applied AI.", {"fill": c["ink"], "weight": 600}),
            ("I turn complex problems into working prototypes in days, then build them into software people can rely on.", {})]
    para, _ = paragraph(runs, bx, 344, 470, 16.5, 27, c["muted"])
    b.append(para)
    # Profile card
    px, py, pw, ph = 600, 118, 260, 300
    b.append(f'<g clip-path="url(#pc)"><image x="{px}" y="{py}" width="{pw}" height="{ph}" preserveAspectRatio="xMidYMid slice" xlink:href="{portrait}"/>'
             f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" fill="url(#shade)"/></g>'
             f'<rect x="{px + .5}" y="{py + .5}" width="{pw - 1}" height="{ph - 1}" rx="18" fill="none" stroke="#5b1d14" stroke-opacity=".55"/>')
    b.append(text("Saad Nazir", px + pw / 2, py + 44, 27, "#ffffff", 500, "manrope", -.03, "middle"))
    b.append(text("Software Engineer | Applied AI", px + pw / 2, py + 66, 11.5, "#ffffff", 600, anchor="middle"))
    bar_y = py + ph - 64
    b.append(f'<rect x="{px + 12}" y="{bar_y}" width="{pw - 24}" height="52" rx="12" fill="#3a1410" fill-opacity=".86" stroke="#ffffff" stroke-opacity=".14"/>')
    b.append(text("@saad-nazir0289", px + 28, bar_y + 23, 12, "#ffffff", 600))
    b.append(text("Available remotely", px + 28, bar_y + 40, 11, "#f0b8a6", 400))
    b.append(f'<circle cx="{px + pw - 34}" cy="{bar_y + 26}" r="14" fill="#7a2a1d"/>' + arrow(px + pw - 42, bar_y + 18, 16, "#ffffff"))
    defs = (f'<defs><clipPath id="pc"><rect x="{px}" y="{py}" width="{pw}" height="{ph}" rx="18"/></clipPath>'
            '<linearGradient id="shade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1a0d0a" stop-opacity=".55"/>'
            '<stop offset=".3" stop-color="#1a0d0a" stop-opacity="0"/><stop offset=".7" stop-color="#2a0f0a" stop-opacity="0"/>'
            '<stop offset="1" stop-color="#2a0f0a" stop-opacity=".6"/></linearGradient>'
            '<style>.w{opacity:0;animation:rot 7.8s cubic-bezier(.2,.7,.2,1) infinite}.w1{opacity:1;animation-delay:-.4s}'
            '.w2{animation-delay:2.2s}.w3{animation-delay:4.8s}'
            '@keyframes rot{0%{opacity:0;transform:translateY(16px)}5%,30%{opacity:1;transform:none}35%,100%{opacity:0;transform:translateY(-12px)}}'
            '@media (prefers-reduced-motion:reduce){.w{animation:none}}</style></defs>')
    write("header", theme, svg(W, H, "".join(b), "saad nazir. Real problems. Thoughtful code. Useful software. Software Engineer focused on Applied AI.", defs))


def button(name, label, theme, c, kind="primary", icon="arrow"):
    size, pad, gap = 14.5, 22, 18
    tw = width(label, size, 500)
    w = round(pad + tw + gap + 16 + pad)
    h = 50
    if kind == "hero":
        fill, fg, stroke = c["hero"], c["heroText"], c["hero"]
    elif kind == "primary":
        fill, fg, stroke = c["button"], c["buttonText"], c["button"]
    else:
        fill, fg, stroke = "none", c["ink"], c["ink"]
    b = f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" fill="{fill}" stroke="{stroke}"/>'
    b += text(label, pad, 30, size, fg, 500)
    ix = pad + tw + gap
    if icon == "down":
        b += (f'<g transform="translate({ix} 17)" fill="none" stroke="{fg}" stroke-width="1.8" stroke-linecap="round" '
              f'stroke-linejoin="round"><path d="M8 0v16M2 10l6 6 6-6"/></g>')
    else:
        b += arrow(ix - 1, 16, 18, fg, 1.8)
    write("btn-" + name, theme, svg(w, h, b, label))
    return w


def stats(c, theme, completed):
    W, H = 900, 108
    items = [(str(completed), "Projects completed"), ("10+", "Competition wins"),
             ("PKR 1M", "Research funded · Co-author"), ("80+", "Students mentored")]
    b = [f'<path d="M0 .5H{W}M0 {H - .5}H{W}" stroke="{c["line"]}"/>']
    cw = W / 4
    for i, (n, label) in enumerate(items):
        cx = cw * i + cw / 2
        if i:
            b.append(f'<path d="M{cw * i:.1f} 26V{H - 26}" stroke="{c["line"]}"/>')
        b.append(text(n, cx, 56, 30, c["ink"], 500, "manrope", -1 / 30, "middle"))
        b.append(text(label, cx, 80, 12.5, c["muted"], 400, anchor="middle"))
    write("stats", theme, svg(W, H, "".join(b), ", ".join(f"{n} {l}" for n, l in items)))


def heading(name, eyebrow, plain, accent, c, theme):
    W, H = 900, 108
    b = text(eyebrow, 0, 30, 12.5, c["muted"], 700, track=1.7 / 12.5)
    b += text(plain, -1, 86, 44, c["ink"], 600, "manrope", -.05)
    sep = "" if accent.startswith(".") else " "
    b += text(accent, -1 + width(plain + sep, 44, 600, "manrope", -.05) + (2.2 if sep else 0), 86, 44, c["accent"], 600, "manrope", -.05)
    write("h-" + name, theme, svg(W, H, b, plain + sep + accent))


def icon_markup(raw, ink, acc, playing=True):
    """Project icon from the site, with its draw-in animation replaying in a loop."""
    inner = re.sub(r"^<svg[^>]*>|</svg>$", "", raw)
    inner = re.sub(r'style="--d:([\d.]+)s([^"]*)"', lambda m: f'style="animation-delay:{m.group(1)}s{m.group(2)}"', inner)
    css = (f'.i .ink,.i .acc{{fill:none;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round}}.i .ink{{stroke:{ink}}}'
           f'.i .acc{{stroke:{acc};stroke-width:2.5}}.i .fill{{fill:{acc}}}'
           '.i .draw{stroke-dasharray:1;animation:pd 9s ease-out infinite}'
           '.i .pop{transform-box:fill-box;transform-origin:center;animation:pp 9s cubic-bezier(.3,1.6,.5,1) infinite}'
           '.i .drop{animation:pdr 9s cubic-bezier(.3,1.4,.5,1) infinite}'
           '@keyframes pd{0%{stroke-dashoffset:1}6%,100%{stroke-dashoffset:0}}'
           '@keyframes pp{0%{opacity:0;transform:scale(.3)}5%,100%{opacity:1;transform:none}}'
           '@keyframes pdr{0%{opacity:0;transform:translateY(-12px)}6%,100%{opacity:1;transform:none}}'
           '@media (prefers-reduced-motion:reduce){.i *{animation:none!important}}')
    return css, inner


def project_card(p, idx, image, raw_icon, note, c, theme):
    W = 900
    tone = c["soft"] if p["slug"] == "mill-ledger" else c["warm"]
    pad, iw, ih = 30, 400, 225
    rx = pad + iw + 32
    rw = W - rx - pad
    b = []
    b.append(f'<image x="{pad}" y="{pad}" width="{iw}" height="{ih}" preserveAspectRatio="xMidYMid slice" xlink:href="{image}"/>')
    css, inner = icon_markup(raw_icon, c["ink"], c["iconAcc"])
    ty = pad + ih + 24
    b.append(f'<rect x="{pad + .5}" y="{ty + .5}" width="55" height="55" rx="14" fill="{c["tile"]}" stroke="{c["tileLine"]}"/>'
             f'<svg class="i" x="{pad + 8}" y="{ty + 8}" width="40" height="40" viewBox="0 0 40 40" overflow="visible">{inner}</svg>')
    b.append(text(note, pad + 72, ty + 33, 14, c["note"], 400))
    b.append(text(f"0{idx} / {p['category']}", rx, 52, 12, c["ink"], 700, track=1.5 / 12))
    b.append(f'<circle cx="{W - pad - 21}" cy="47" r="21" fill="none" stroke="{c["ink"]}" stroke-opacity=".25"/>' + arrow(W - pad - 30, 38, 18, c["ink"], 1.8))
    b.append(text(p["client"], rx, 104, 13.5, c["muted"], 400))
    b.append(text(p["title"], rx - 1, 146, 36, c["ink"], 500, "manrope", -.04))
    para, last = paragraph([(p["summary"], {})], rx, 184, rw, 15.5, 25, c["muted"])
    b.append(para)
    y = last + 26
    b.append(f'<path d="M{rx} {y + .5}H{W - pad}" stroke="{c["ink"]}" stroke-opacity=".15"/>')
    tx, ty2 = rx, y + 18
    for tag in p["stack"]:
        tw = width(tag, 12, 400) + 16
        if tx + tw > W - pad:
            tx, ty2 = rx, ty2 + 34
        b.append(f'<rect x="{tx + .5}" y="{ty2 + .5}" width="{tw - 1:.1f}" height="26" rx="3" fill="none" stroke="{c["tag"]}"/>')
        b.append(text(tag, tx + 8, ty2 + 17.5, 12, c["ink"], 400))
        tx += tw + 6
    H = max(ty + 55 + pad, ty2 + 26 + pad)
    body = f'<rect width="{W}" height="{H}" fill="{tone}"/>' + "".join(b)
    write("card-" + p["slug"], theme, svg(W, H, body, f"{p['title']}: {p['summary']}", f"<defs><style>{css}</style></defs>"))


def now_text(slug, kicker, title, body, c, theme):
    W = 440
    b = [text(kicker, 0, 22, 11.5, c["accent"], 700, track=1.2 / 11.5)]
    b.append(text(title, -1, 58, 25, c["ink"], 600, "manrope", -.03))
    para, last = paragraph([(body, {})], 0, 90, W - 10, 14.5, 23, c["muted"])
    b.append(para)
    y = last + 36
    b.append(text("Case study", 0, y, 14, c["ink"], 600))
    b.append(arrow(width("Case study", 14, 600) + 6, y - 13, 15, c["ink"], 1.8))
    write("now-" + slug, theme, svg(W, y + 10, "".join(b), f"{title}: {body}"))


def blog_card(post, i, cover, c, theme):
    W, H, aw = 900, 176, 264
    b = [f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" fill="{c["card"]}" stroke="{c["line"]}"/>']
    if cover:
        b.append(f'<image x="1" y="1" width="{aw}" height="{H - 2}" preserveAspectRatio="xMidYMid slice" xlink:href="{cover}"/>')
    else:
        b.append(f'<rect x="1" y="1" width="{aw}" height="{H - 2}" fill="{c["soft"]}"/>')
        b.append(text(f"{i:02d}", 26, H - 30, 74, c["ink"], 600, "manrope", -.04))
        for k, lw in enumerate((110, 86, 58)):
            b.append(f'<rect x="{aw - 26 - 110}" y="{H - 82 + k * 14}" width="{lw}" height="5" rx="2.5" fill="{c["ink"]}" fill-opacity=".14"/>')
    x = aw + 32
    b.append(text(post["category"], x, 40, 11.5, c["accent"], 700, track=1.6 / 11.5))
    date = f"{post['dateLabel']} · {post['readingTime']} min"
    b.append(text(date, x + width(post["category"], 11.5, 700, track=1.6 / 11.5) + 22, 40, 12.5, c["muted"], 400))
    tl, ty = paragraph([(post["title"], {})], x, 74, W - x - 70, 21, 27, c["ink"], 600, "manrope")
    b.append(tl)
    sp, sy = paragraph([(post["summary"], {})], x, ty + 30, W - x - 40, 14, 22, c["muted"], max_lines=2)
    b.append(sp)
    b.append(arrow(W - 52, 22, 20, c["ink"], 1.8))
    write(f"blog-{i}", theme, svg(W, H, "".join(b), f"{post['title']}. {post['summary']}"))


def toolbox(tools, c, theme):
    cols, cw, ch, gap = 6, 140, 64, 12
    W = cols * cw + (cols - 1) * gap
    rows = (len(tools) + cols - 1) // cols
    H = rows * ch + (rows - 1) * gap + 1
    b = []
    for i, (name, raw, color) in enumerate(tools):
        x, y = (i % cols) * (cw + gap), (i // cols) * (ch + gap)
        b.append(f'<rect x="{x + .5}" y="{y + .5}" width="{cw - 1}" height="{ch - 1}" fill="{c["card"]}" stroke="{c["line"]}"/>')
        vb = re.search(r'viewBox="([^"]+)"', raw).group(1)
        inner = re.sub(r"^<svg[^>]*>|</svg>$", "", raw)
        stroke_icon = 'stroke="currentColor"' in raw[:400]
        attrs = (f'fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
                 if stroke_icon else f'fill="{color}"')
        b.append(f'<svg x="{x + 14}" y="{y + 18}" width="27" height="27" viewBox="{vb}" {attrs}>{inner}</svg>')
        b.append(text(name, x + 53, y + 37, 14, c["ink"], 400))
    write("toolbox", theme, svg(W, H, "".join(b), "Toolbox: " + ", ".join(t[0] for t in tools)))


def about(c, theme):
    W = 900
    b = [text("I switched from pre-med to computer science.", 0, 34, 27, c["ink"], 600, "manrope", -.035)]
    runs = [("As a medical student, I couldn’t ignore my passion for computers. My parents hoped I’d become a doctor, "
             "so I took a stand to prove I belonged here. That decision changed my", {}), ("journey.", {"fill": c["accent"], "weight": 600}),
            ("Today I study computer science at UCP, build software, compete in hackathons, and do research.", {})]
    p1, last = paragraph(runs, 0, 82, W - 30, 16.5, 28, c["muted"])
    b.append(p1)
    p2, last = paragraph([("Next, I want to join a team building AI products and own features from idea to production.", {})],
                         0, last + 44, W - 30, 16.5, 28, c["muted"])
    b.append(p2)
    y = last + 34
    for n, t, d in [("01", "Full-stack products", "Web apps, APIs, and desktop software."),
                    ("02", "AI & automation", "Email workflows, search tools, and agents."),
                    ("03", "Product decisions", "Choosing features and testing them against the user’s requirements.")]:
        b.append(f'<path d="M0 {y + .5}H{W}" stroke="{c["line"]}"/>')
        b.append(text(n, 0, y + 30, 12, c["accent"], 500))
        b.append(text(t, 46, y + 33, 19, c["ink"], 600, "manrope", -.03))
        b.append(text(d, 46, y + 58, 15.5, c["muted"], 400))
        y += 82
    alt = ("I switched from pre-med to computer science. As a medical student, I couldn’t ignore my passion for computers. "
           "Today I study computer science at UCP, build software, compete in hackathons, and do research.")
    write("about", theme, svg(W, y + 2, "".join(b), alt))


def contact(c, theme, email):
    W, H = 900, 108
    b = [text("Contact me about a role or project.", 0, 26, 16.5, c["muted"], 400)]
    b.append(text(email, 0, 78, 34, c["ink"], 500, "manrope", -.04))
    ew = width(email, 34, 500, "manrope", -.04)
    b.append(arrow(ew + 10, 50, 30, c["ink"], 2.2))
    b.append(f'<path d="M0 98.5H{ew + 44:.0f}" stroke="{c["ink"]}"/>')
    write("contact", theme, svg(W, H, "".join(b), f"Email {email}"))


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True, type=Path, help="checkout of saad-nazir-0289/Saad-Portfolio")
    site = ap.parse_args().site.resolve()
    gen = site / "src" / "generated"
    projects = json.loads((gen / "projects.json").read_text())
    posts = json.loads((gen / "blogs.json").read_text())
    icons = json.loads((HERE / "icons.json").read_text())
    pub = site / "public"
    OUT.mkdir(exist_ok=True)

    portrait = embed(pub / "saad-portrait.png", 260, 300, focus=.3)
    covers = {"mill-ledger": embed(pub / "case-studies/mill-ledger/home-thumbnail.png", 400, 225),
              "ucp-noticeboard": embed(pub / "case-studies/ucp-noticeboard/home-thumbnail.png", 400, 225)}
    notes = {"mill-ledger": "Runs a rice mill’s daily accounts", "ucp-noticeboard": "Live in the UCP student portal"}
    by_slug = {p["slug"]: p for p in projects}
    completed = sum(1 for p in projects if not p.get("inProgress") and not p.get("draft"))
    # The site's own colours for each tool, in the order of its toolbox.
    colors = ["#9d7610", "#087ea4", "#43853d", "#3776ab", "#008578", "#4169e1", "#32843b", "#1674bb",
              "#13846d", "#7544bb", "#c63c61", "#d44429"]
    tools = [(n, raw, col) for (n, raw), col in zip(icons["tools"], colors)]
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    for post in posts:
        y, m, d = post["date"].split("-")
        post["dateLabel"] = f"{months[int(m) - 1]} {int(d)}, {y}"

    for theme, c in THEMES.items():
        header(c, theme, portrait)
        button("explore", "Explore my work", theme, c, "hero")
        button("resume", "Résumé", theme, c, "secondary")
        button("projects", f"All projects ({len(projects)})", theme, c, "secondary")
        button("journey", "My journey", theme, c, "primary")
        button("certifications", "Certifications", theme, c, "secondary")
        button("blog", f"Read all {len(posts)} posts", theme, c, "secondary")
        button("linkedin", "LinkedIn", theme, c, "primary")
        button("website", "Visit the site", theme, c, "secondary")
        stats(c, theme, completed)
        for args in [("work", "01 / SELECTED WORK", "Selected projects", "."),
                     ("about", "02 / A LITTLE ABOUT ME", "About", "me."),
                     ("now", "03 / IN PROGRESS", "Currently", "building."),
                     ("blog", "04 / WRITING", "Latest from the", "blog."),
                     ("toolbox", "05 / MY TOOLBOX", "Tools I", "build with."),
                     ("contact", "06 / LET’S CONNECT", "Get in", "touch.")]:
            heading(*args, c, theme)
        for i, slug in enumerate(["mill-ledger", "ucp-noticeboard"], 1):
            project_card(by_slug[slug], i, covers[slug], icons["projectIcons"][slug], notes[slug], c, theme)
        now_text("gate-vision", "COMPUTER VISION · TECH LEAD", "UCP Gate Vision",
                 "Spots every car at three campus gates, reads its number plate, logs the entry, and flags banned vehicles. Takhleeq × UCP.", c, theme)
        now_text("agrivision", "DEEP LEARNING · FINAL-YEAR PROJECT", "AgriVision",
                 "Sharp satellite photos are often lost to clouds. AgriVision fills the gaps from blurry daily images to map crop health.", c, theme)
        for i, post in enumerate(posts, 1):
            cover = None
            if post.get("cover"):
                cover = embed(pub / post["cover"]["src"].lstrip("/"), 264, 174, focus=0)
            blog_card(post, i, cover, c, theme)
        toolbox(tools, c, theme)
        about(c, theme)
        contact(c, theme, "saadnazir099@gmail.com")
    print("Wrote", len(list(OUT.glob("*-light.svg"))), "light and", len(list(OUT.glob("*-dark.svg"))), "dark images to", OUT)


if __name__ == "__main__":
    main()
