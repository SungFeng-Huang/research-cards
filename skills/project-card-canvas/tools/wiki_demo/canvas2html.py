#!/usr/bin/env python3
"""JSON Canvas → standalone HTML (SVG) approximating Obsidian's canvas look,
for headless-Chrome screenshots. Usage: canvas2html.py in.json out.html"""
import html
import json
import re
import sys

PALETTE = {"1": "#e93147", "2": "#ec7500", "3": "#e0ac00",
           "4": "#08b94e", "5": "#00bfbc", "6": "#7852ee"}
GRAY = "#8a8a8a"
PAD = 60


def md(t):
    t = html.escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return t.replace("\n", "<br>")


def anchor(n, side):
    x, y, w, h = n["x"], n["y"], n["width"], n["height"]
    return {"left": (x, y + h / 2), "right": (x + w, y + h / 2),
            "top": (x + w / 2, y), "bottom": (x + w / 2, y + h)}[side]


def ctrl(pt, side, d):
    x, y = pt
    return {"left": (x - d, y), "right": (x + d, y),
            "top": (x, y - d), "bottom": (x, y + d)}[side]


def main(src, dst, scale=1.0):
    c = json.load(open(src))
    # scale-compensated typography: the EFFECTIVE on-image font size stays
    # readable (~18px) no matter how far the canvas is scaled down
    nf = max(15, round(18 / scale))          # node text
    ef = max(13, round(15 / scale))          # edge labels
    nodes = {n["id"]: n for n in c["nodes"]}
    xs = [n["x"] for n in c["nodes"]] + [n["x"] + n["width"] for n in c["nodes"]]
    ys = [n["y"] for n in c["nodes"]] + [n["y"] + n["height"] for n in c["nodes"]]
    x0, y0 = min(xs) - PAD, min(ys) - PAD
    W, H = max(xs) - x0 + PAD, max(ys) - y0 + PAD
    sw, sh = int(W * scale), int(H * scale)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{sw}" height="{sh}" '
             f'viewBox="{x0} {y0} {W} {H}" font-family="-apple-system,'
             f'PingFang TC,sans-serif">',
             '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" '
             'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
             f'<path d="M0,0L10,5L0,10z" fill="{GRAY}"/></marker></defs>',
             f'<rect x="{x0}" y="{y0}" width="{W}" height="{H}" fill="#f7f7f5"/>']
    for e in c.get("edges", []):
        a, b = nodes[e["fromNode"]], nodes[e["toNode"]]
        fs, ts = e.get("fromSide", "right"), e.get("toSide", "left")
        p1, p2 = anchor(a, fs), anchor(b, ts)
        dist = max(abs(p2[0] - p1[0]), abs(p2[1] - p1[1]))
        d = max(60, min(dist * 0.5, 260))
        c1, c2 = ctrl(p1, fs, d), ctrl(p2, ts, d)
        parts.append(f'<path d="M{p1[0]},{p1[1]} C{c1[0]},{c1[1]} {c2[0]},'
                     f'{c2[1]} {p2[0]},{p2[1]}" fill="none" stroke="{GRAY}" '
                     f'stroke-width="2.5" marker-end="url(#arr)"/>')
        if e.get("label"):
            mx = (p1[0] + 3 * c1[0] + 3 * c2[0] + p2[0]) / 8
            my = (p1[1] + 3 * c1[1] + 3 * c2[1] + p2[1]) / 8
            lw = len(e["label"]) * ef + 16
            ph = round(ef * 1.9)
            parts.append(f'<rect x="{mx - lw / 2}" y="{my - ph / 2}" width="{lw}" '
                         f'height="{ph}" rx="6" fill="#f7f7f5" stroke="{GRAY}" '
                         f'stroke-width="1"/>'
                         f'<text x="{mx}" y="{my + ef * 0.35}" text-anchor="middle" '
                         f'font-size="{ef}" fill="#444">{html.escape(e["label"])}</text>')
    for n in c["nodes"]:
        col = PALETTE.get(n.get("color", ""), "#b9b9b9")
        fill = col + "14" if n.get("color") else "#ffffff"
        parts.append(f'<rect x="{n["x"]}" y="{n["y"]}" width="{n["width"]}" '
                     f'height="{n["height"]}" rx="10" fill="{fill}" '
                     f'stroke="{col}" stroke-width="3"/>')
        body = md(n.get("text") or f'📄 {n.get("file", "")}')
        parts.append(
            f'<foreignObject x="{n["x"] + 12}" y="{n["y"] + 8}" '
            f'width="{n["width"] - 24}" height="{n["height"] - 16}">'
            f'<div xmlns="http://www.w3.org/1999/xhtml" style="font-size:{nf}px;'
            f'line-height:1.45;color:#222;overflow:hidden;height:100%">'
            f'{body}</div></foreignObject>')
    parts.append("</svg>")
    open(dst, "w").write(
        "<!doctype html><meta charset='utf-8'><body style='margin:0'>"
        + "".join(parts))
    print(dst, f"{sw}x{sh}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2],
         float(sys.argv[3]) if len(sys.argv) > 3 else 1.0)
