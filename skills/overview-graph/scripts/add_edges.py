#!/usr/bin/env python3
"""Materialise lateral graph edges as in-card mentions, idempotently.

Each edge becomes a card-mention bullet under a trailing H2 section
「相關主題（橫向連結）」 on the SOURCE card. Direction semantics live in the
label text: `↔ …` (write the mirror edge on the other card too) or `→ …`
(deep-dive pointer, source side only). Heptabase whiteboards render these
mentions as lines when 「顯示 mention link」 is on.

Usage: python3 add_edges.py <edges.json> [--dry-run]
Spec:
{
  "edges": [
    {"from": "<card-id>", "to": "<card-id>", "label": "↔ 同 7 篇論文的全雙工工程面"},
    ...
  ]
}
Re-running only adds missing bullets (a source card's section is scanned for the
target id). Bidirectional edges = two entries (one per direction).
"""
import json, subprocess, tempfile, os, sys

# backend routing: obsidian mode reads/writes vault cards via the doc-level
# backend (card ids = "Folder/Name"); heptabase/both keep the legacy CLI path.
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.realpath(__file__)),
                                  "..", "..", "_shared"))
try:
    import backend as _backend
    OBS = _backend.obsidian_or_none()
except Exception:
    OBS = None

SEC = "相關主題（橫向連結）"

def short(cid):
    return cid if OBS else cid[:8]

def run(a): return subprocess.run(a, capture_output=True, text=True)
def tx(n):
    if n.get("type") == "text": return n.get("text", "")
    return "".join(tx(c) for c in n.get("content", []) if isinstance(c, dict))
def H(l, t): return {"type":"heading","attrs":{"id":None,"level":l},"content":[{"type":"text","text":t}]}
def bullet(cid, desc):
    return {"type":"bullet_list_item","attrs":{"id":None,"folded":False,"format":None},
            "content":[{"type":"paragraph","attrs":{"id":None},
                        "content":[{"type":"card","attrs":{"cardId":cid}},
                                   {"type":"text","text":"　"+desc}]}]}

def main():
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    dry = "--dry-run" in sys.argv
    failures = 0
    by_src = {}
    for e in spec["edges"]:
        by_src.setdefault(e["from"], []).append((e["to"], e["label"]))

    for src, edges in by_src.items():
        if OBS:
            md5, doc = OBS.read_doc(src)
        else:
            r = run(["heptabase", "note", "read", src])
            d = json.loads(r.stdout)
            md5 = d["contentMd5"]; doc = json.loads(d["content"])
        C = doc["content"]
        idx = next((i for i, n in enumerate(C)
                    if n.get("type") == "heading" and tx(n).strip() == SEC), None)
        existing = set()
        if idx is not None:
            for n in C[idx+1:]:
                if n.get("type") == "heading": break
                s = json.dumps(n)
                for t, _ in edges:
                    if t in s: existing.add(t)
        new = [bullet(t, lbl) for t, lbl in edges if t not in existing]
        if not new:
            print(f"{short(src)}: complete ({len(edges)} edges present)"); continue
        if dry:
            print(f"{short(src)}: would add {len(new)} (has section: {idx is not None})"); continue
        if idx is None:
            C.append(H(2, SEC)); idx = len(C) - 1
        end = idx + 1
        while end < len(C) and C[end].get("type") != "heading": end += 1
        C[end:end] = new
        if OBS:
            try:
                OBS.save_doc(src, md5, doc)
                print(f"{short(src)}: +{len(new)}")
            except Exception as e:
                failures += 1
                print(f"{short(src)}: SAVE FAILED: {str(e)[:120]}")
            continue
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False); tmp = f.name
        try:
            r = run(["heptabase", "note", "save", src, "--content-md5", md5, "--content-file", tmp])
        finally:
            os.unlink(tmp)
        if r.returncode != 0:
            failures += 1
            print(f"{src[:8]}: SAVE FAILED (rc={r.returncode}): {r.stderr.strip()[:120]}")
        else:
            print(f"{src[:8]}: +{len(new)}")
    if failures:
        print(f"{failures} card(s) NOT updated — fix (md5 conflict? re-run) before trusting the graph.")
    return 1 if failures else 0

if __name__ == "__main__":
    try:
        import hbconfig as _hbc
        if not _hbc.feature_enabled("study"):
            sys.exit("study 方向已在 config features.study 停用")
    except ImportError:
        pass
    sys.exit(main())
