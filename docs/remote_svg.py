"""Generate the HAP command remote as inline SVG, in two visual directions.

The Configure dialog renders step descriptions through <ha-markdown allow-svg>,
so inline SVG is the one route to real shapes and colour inside the
integration's own UI. No width or height is set on the root element: the viewBox
lets it scale to the dialog, the README, and anywhere else it is dropped.

Every glyph is drawn as a path. The first draft used emoji (⏪ ⏩ 🔇) which was a
mistake: emoji render as full-colour OS artwork, so the diagram looked different
on every machine and clashed with the flat styling. Paths render identically
everywhere and inherit the palette.
"""

from __future__ import annotations

# ─── Palettes ──────────────────────────────────────────────────────────────────

BRAND = {
    "key": "brand",
    "body_top": "#232a3d",
    "body_bottom": "#0e1220",
    "body_edge": "#3d4561",
    "btn": "#2b3247",
    "btn_edge": "#4c5578",
    "glyph": "#dfe5ff",
    "glyph_on": "#08121a",
    "accent_a": "#22d3ee",
    "accent_b": "#e879f9",
    "ring": "#171d2e",
    "label": "#d3d9ee",
    "dim": "#8d95b0",
    "lead": "#5a648a",
    "page": "#0b0d14",
}

NEUTRAL = {
    "key": "neutral",
    "body_top": "#8a8f99",
    "body_bottom": "#5f6672",
    "body_edge": "#a8adb7",
    "btn": "#f5f6f8",
    "btn_edge": "#cdd2da",
    "glyph": "#1f2733",
    "glyph_on": "#062430",
    "accent_a": "#38bdf8",
    "accent_b": "#38bdf8",
    "ring": "#717783",
    # currentColor makes the captions follow the surrounding theme's text colour,
    # so this variant is legible on light and dark themes alike.
    "label": "currentColor",
    "dim": "currentColor",
    "lead": "currentColor",
    "page": "transparent",
}

W, H = 740, 800
CX = 150          # remote centre line
LX = 306          # caption column


# ─── Glyphs, all drawn centred on (0, 0) ───────────────────────────────────────


def _g(p, x, y, body, *, on=False):
    colour = p["glyph_on"] if on else p["glyph"]
    return f'<g transform="translate({x} {y})" fill="{colour}" stroke="{colour}">{body}</g>'


def tri(d, s):
    """Triangle pointing in direction d, half-size s."""
    if d == "r":
        return f'<path d="M{-s*0.45} {-s} L{s*0.75} 0 L{-s*0.45} {s} Z" stroke="none"/>'
    if d == "l":
        return f'<path d="M{s*0.45} {-s} L{-s*0.75} 0 L{s*0.45} {s} Z" stroke="none"/>'
    if d == "u":
        return f'<path d="M{-s} {s*0.45} L0 {-s*0.75} L{s} {s*0.45} Z" stroke="none"/>'
    return f'<path d="M{-s} {-s*0.45} L0 {s*0.75} L{s} {-s*0.45} Z" stroke="none"/>'


def power(s=8):
    return (
        f'<path d="M{-s*0.8} {-s*0.35} A{s} {s} 0 1 0 {s*0.8} {-s*0.35}" fill="none" '
        f'stroke-width="2" stroke-linecap="round"/>'
        f'<line x1="0" y1="{-s*1.25}" x2="0" y2="{-s*0.1}" stroke-width="2" '
        f'stroke-linecap="round"/>'
    )


def info(s=9):
    return (
        f'<circle r="{s}" fill="none" stroke-width="1.8"/>'
        f'<circle cx="0" cy="{-s*0.45}" r="1.5" stroke="none"/>'
        f'<line x1="0" y1="{-s*0.05}" x2="0" y2="{s*0.55}" stroke-width="2" '
        f'stroke-linecap="round"/>'
    )


def back(s=9):
    return (
        f'<path d="M{s*0.9} {s*0.5} A{s*0.85} {s*0.85} 0 0 0 {-s*0.35} {-s*0.35}" '
        f'fill="none" stroke-width="2" stroke-linecap="round"/>'
        f'<path d="M{-s*0.95} {-s*0.75} L{-s*0.1} {-s*0.3} L{-s*0.75} {s*0.35} Z" '
        f'stroke="none"/>'
    )


def home(s=9):
    return (
        f'<path d="M{-s} {-s*0.05} L0 {-s*0.95} L{s} {-s*0.05}" fill="none" '
        f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
        f'<path d="M{-s*0.65} {-s*0.2} V{s*0.85} H{s*0.65} V{-s*0.2}" fill="none" '
        f'stroke-width="2" stroke-linejoin="round"/>'
    )


def close(s=7):
    return (
        f'<line x1="{-s}" y1="{-s}" x2="{s}" y2="{s}" stroke-width="2.2" '
        f'stroke-linecap="round"/>'
        f'<line x1="{s}" y1="{-s}" x2="{-s}" y2="{s}" stroke-width="2.2" '
        f'stroke-linecap="round"/>'
    )


def gear(s=8):
    """Cog. The teeth must overlap the rim — set apart from it they read as a
    sun, which is what the first attempt looked like."""
    teeth = "".join(
        f'<rect x="-1.7" y="{-s - 2.2}" width="3.4" height="4.2" rx="1.2" '
        f'stroke="none" transform="rotate({a})"/>'
        for a in range(0, 360, 45)
    )
    return (
        f'{teeth}<circle r="{s * 0.82}" fill="none" stroke-width="2.4"/>'
        f'<circle r="{s * 0.2}" stroke="none"/>'
    )


def skip(direction, s=7, bar=True):
    """Rewind/fast-forward (two triangles) or prev/next (triangle + bar)."""
    if direction == "r":
        body = f'<g transform="translate({-s*0.55} 0)">{tri("r", s)}</g>'
        body += f'<g transform="translate({s*0.75} 0)">{tri("r", s)}</g>'
        if bar:
            body += f'<rect x="{s*1.5}" y="{-s}" width="2.2" height="{s*2}" rx="1" stroke="none"/>'
    else:
        body = f'<g transform="translate({s*0.55} 0)">{tri("l", s)}</g>'
        body += f'<g transform="translate({-s*0.75} 0)">{tri("l", s)}</g>'
        if bar:
            body += f'<rect x="{-s*1.5-2.2}" y="{-s}" width="2.2" height="{s*2}" rx="1" stroke="none"/>'
    return body


def play_pause(s=9):
    return (
        f'<g transform="translate({-s*0.6} 0)">{tri("r", s*0.85)}</g>'
        f'<rect x="{s*0.45}" y="{-s*0.85}" width="2.6" height="{s*1.7}" rx="1.2" stroke="none"/>'
        f'<rect x="{s*1.05}" y="{-s*0.85}" width="2.6" height="{s*1.7}" rx="1.2" stroke="none"/>'
    )


def mute(s=8):
    return (
        f'<path d="M{-s*0.95} {-s*0.3} H{-s*0.4} L{s*0.15} {-s*0.9} V{s*0.9} '
        f'L{-s*0.4} {s*0.3} H{-s*0.95} Z" stroke-width="1.6" stroke-linejoin="round"/>'
        f'<line x1="{s*0.55}" y1="{-s*0.55}" x2="{s*1.25}" y2="{s*0.55}" '
        f'stroke-width="2" stroke-linecap="round"/>'
        f'<line x1="{s*1.25}" y1="{-s*0.55}" x2="{s*0.55}" y2="{s*0.55}" '
        f'stroke-width="2" stroke-linecap="round"/>'
    )


# ─── Building blocks ───────────────────────────────────────────────────────────


def _defs(p):
    return f"""
  <defs>
    <linearGradient id="body-{p['key']}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{p['body_top']}"/>
      <stop offset="1" stop-color="{p['body_bottom']}"/>
    </linearGradient>
    <linearGradient id="acc-{p['key']}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{p['accent_a']}"/>
      <stop offset="1" stop-color="{p['accent_b']}"/>
    </linearGradient>
    <radialGradient id="gloss-{p['key']}" cx="0.5" cy="0.1" r="0.9">
      <stop offset="0" stop-color="#ffffff" stop-opacity="0.13"/>
      <stop offset="1" stop-color="#ffffff" stop-opacity="0"/>
    </radialGradient>
  </defs>"""


def btn(p, x, y, r, glyph_fn, *, accent=False, vendor=False):
    """One button. vendor=True draws a dashed rim.

    home (16) and settings (14) are not in the HAP RemoteKey spec — they are
    vendor extensions that happen to work on Sony. Drawing them identically to
    the real keys invites a bug report from every LG owner, so they are marked.
    """
    fill = f"url(#acc-{p['key']})" if accent else p["btn"]
    dash = ' stroke-dasharray="4 3.5"' if vendor else ""
    return (
        f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{p["btn_edge"]}" '
        f'stroke-width="{2 if vendor else 1.2}"{dash}/>' + _g(p, x, y, glyph_fn, on=accent)
    )


def lead(p, points):
    """Leader line through explicit waypoints — no guessing, no crossings."""
    d = f"M{points[0][0]} {points[0][1]}" + "".join(
        f" L{x} {y}" for x, y in points[1:]
    )
    return (
        f'<path d="{d}" fill="none" stroke="{p["lead"]}" stroke-width="1.2" '
        f'stroke-opacity="0.5" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{points[0][0]}" cy="{points[0][1]}" r="2.6" fill="{p["lead"]}" '
        f'fill-opacity="0.7" stroke="none"/>'
    )


def caption(p, y, title, commands):
    return (
        f'<text x="{LX}" y="{y}" fill="{p["label"]}" font-size="14.5" '
        f'font-weight="600">{title}</text>'
        f'<text x="{LX}" y="{y + 20}" fill="{p["dim"]}" font-size="12.6" '
        f'font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" '
        f'opacity="0.82">{commands}</text>'
    )


# ─── The drawing ───────────────────────────────────────────────────────────────


def build(p):
    o = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" '
        'aria-label="HAP remote command reference" '
        'font-family="-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">',
        _defs(p),
    ]
    if p["page"] != "transparent":
        o.append(f'<rect width="{W}" height="{H}" fill="{p["page"]}"/>')

    # Body
    o.append(
        f'<rect x="{CX - 112}" y="22" width="224" height="744" rx="56" '
        f'fill="url(#body-{p["key"]})" stroke="{p["body_edge"]}" stroke-width="1.6"/>'
    )
    o.append(
        f'<rect x="{CX - 112}" y="22" width="224" height="744" rx="56" '
        f'fill="url(#gloss-{p["key"]})" stroke="none"/>'
    )

    # ── Power (top right) and Info (top left) ─────────────────────────────────
    o.append(btn(p, CX + 46, 84, 26, power()))
    o.append(lead(p, [(CX + 76, 84), (CX + 104, 84), (LX - 24, 62), (LX - 8, 62)]))
    o.append(caption(p, 58, "Power", "remote.turn_on  ·  remote.turn_off"))

    o.append(btn(p, CX - 46, 84, 26, info(), accent=True))
    # Routed under the power button so the two never cross.
    o.append(lead(p, [(CX - 46, 112), (CX - 46, 126), (LX - 24, 126), (LX - 8, 126)]))
    o.append(caption(p, 122, "Info — steps through your inputs",
                     "info  ·  15      the ⓘ on the iOS widget"))

    # ── D-pad ─────────────────────────────────────────────────────────────────
    dy = 262
    o.append(
        f'<circle cx="{CX}" cy="{dy}" r="98" fill="{p["ring"]}" '
        f'stroke="{p["btn_edge"]}" stroke-width="1.2" stroke-opacity="0.55"/>'
    )
    o.append(btn(p, CX, dy - 64, 27, tri("u", 7)))
    o.append(btn(p, CX, dy + 64, 27, tri("d", 7)))
    o.append(btn(p, CX - 64, dy, 27, tri("l", 7)))
    o.append(btn(p, CX + 64, dy, 27, tri("r", 7)))
    o.append(
        f'<circle cx="{CX}" cy="{dy}" r="39" fill="url(#acc-{p["key"]})" '
        f'stroke="{p["btn_edge"]}" stroke-width="1.2"/>'
        f'<text x="{CX}" y="{dy}" fill="{p["glyph_on"]}" font-size="16" '
        f'font-weight="700" text-anchor="middle" dominant-baseline="central">OK</text>'
    )
    o.append(lead(p, [(CX + 91, dy - 36), (CX + 116, dy - 36), (LX - 24, 200), (LX - 8, 200)]))
    o.append(caption(p, 196, "D-pad", "up 4   down 5   left 6   right 7"))
    o.append(lead(p, [(CX + 91, dy + 36), (CX + 116, dy + 36), (LX - 24, 268), (LX - 8, 268)]))
    o.append(caption(p, 264, "Select", "select  ·  ok  ·  enter   →   8"))

    # ── Navigation ────────────────────────────────────────────────────────────
    ny = 424
    o.append(btn(p, CX - 64, ny, 27, back()))
    o.append(btn(p, CX, ny, 27, home(), vendor=True))
    o.append(btn(p, CX + 64, ny, 27, close()))
    o.append(lead(p, [(CX + 94, ny), (CX + 116, ny), (LX - 24, 336), (LX - 8, 336)]))
    o.append(caption(p, 332, "Navigation", "back 9   home 16   exit 10"))

    sy = 486
    o.append(btn(p, CX, sy, 25, gear(), vendor=True))
    o.append(lead(p, [(CX + 28, sy), (CX + 116, sy), (LX - 24, 404), (LX - 8, 404)]))
    o.append(caption(p, 400, "TV settings", "settings  ·  14      vendor extension"))

    # ── Transport ─────────────────────────────────────────────────────────────
    ty = 566
    o.append(btn(p, CX - 64, ty, 27, skip("l", bar=False)))
    o.append(btn(p, CX, ty, 31, play_pause()))
    o.append(btn(p, CX + 64, ty, 27, skip("r", bar=False)))
    o.append(lead(p, [(CX + 94, ty), (CX + 116, ty), (LX - 24, 472), (LX - 8, 472)]))
    o.append(caption(p, 468, "Transport", "rewind 0   play_pause 11   fast_forward 1"))

    # ── Track, with mute in the middle so the row stays balanced ─────────────
    ky = 634
    o.append(btn(p, CX - 64, ky, 25, skip("l")))
    o.append(btn(p, CX, ky, 27, mute()))
    o.append(btn(p, CX + 64, ky, 25, skip("r")))
    o.append(lead(p, [(CX + 91, ky), (CX + 116, ky), (LX - 24, 540), (LX - 8, 540)]))
    o.append(caption(p, 536, "Track", "previous_track 3   next_track 2"))
    # Mute sits in the middle of the row, so its leader drops clear of the
    # neighbouring button before turning right.
    o.append(lead(p, [(CX, ky + 29), (CX, 666), (CX + 116, 666), (LX - 24, 608), (LX - 8, 608)]))
    o.append(caption(p, 604, "Mute", "mute  ·  mute_on  ·  mute_off"))

    # ── Volume rocker ─────────────────────────────────────────────────────────
    vy = 700
    o.append(
        f'<rect x="{CX - 36}" y="{vy - 36}" width="72" height="72" rx="33" '
        f'fill="{p["btn"]}" stroke="{p["btn_edge"]}" stroke-width="1.2"/>'
        f'<line x1="{CX - 36}" y1="{vy}" x2="{CX + 36}" y2="{vy}" '
        f'stroke="{p["btn_edge"]}" stroke-width="1.2" stroke-opacity="0.7"/>'
        f'<text x="{CX}" y="{vy - 17}" fill="{p["glyph"]}" font-size="17" '
        f'font-weight="700" text-anchor="middle" dominant-baseline="central">+</text>'
        f'<text x="{CX}" y="{vy + 17}" fill="{p["glyph"]}" font-size="19" '
        f'font-weight="700" text-anchor="middle" dominant-baseline="central">&#8722;</text>'
    )
    o.append(lead(p, [(CX + 37, vy), (CX + 116, vy), (LX - 24, 676), (LX - 8, 676)]))
    o.append(caption(p, 672, "Volume", "volume_up  ·  volume_down"))

    # ── Footnotes ─────────────────────────────────────────────────────────────
    o.append(
        f'<g transform="translate({LX + 6} 726)">'
        f'<circle r="7" fill="none" stroke="{p["btn_edge"]}" stroke-width="2" '
        f'stroke-dasharray="4 3.5"/></g>'
        f'<text x="{LX + 22}" y="730" fill="{p["dim"]}" font-size="12.4" opacity="0.75">'
        "dashed = vendor extension, not in the HAP spec.</text>"
        f'<text x="{LX + 22}" y="748" fill="{p["dim"]}" font-size="12.4" opacity="0.75">'
        "TVs that do not know them simply ignore them.</text>"
    )
    o.append(
        f'<text x="{LX}" y="778" fill="{p["dim"]}" font-size="12.4" opacity="0.75">'
        "Names and raw values are interchangeable. input:&lt;name&gt; picks an input.</text>"
    )

    o.append("</svg>")
    return "".join(o)


if __name__ == "__main__":
    import pathlib

    out = pathlib.Path("docs")
    for palette in (BRAND, NEUTRAL):
        path = out / f"remote_{palette['key']}.svg"
        path.write_text(build(palette))
        print("wrote", path)
