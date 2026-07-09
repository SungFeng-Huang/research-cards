#!/usr/bin/env python3
"""Integrity check for the Heptabase -> Obsidian sync output.

Scans managed folders and reports:
  bad_ext_attachments  - attachment files whose extension Obsidian won't render
  missing_embeds       - ![[file]] embeds whose target file doesn't exist
  broken_wikilinks     - [[note]] links whose target .md doesn't exist
  broken_blockrefs     - [[#^id]] refs with no matching ^id in the same file
  leftover_placeholders- unreplaced %%HEPTA / HEPTA- markers
  duplicate_ids        - two files claiming the same heptabase_id
  state_orphans        - state.json entries whose file is missing
  untracked_files      - .md files in managed folders not in state.json
  journal_issues       - vault-root daily notes (journal bridge): malformed
                         managed markers, missing embeds / broken wikilinks
                         inside the managed block, leftover placeholders
"""
import json, os, re, subprocess, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                "..", "_shared"))
import hbconfig

_cfg = hbconfig.load_config()
VAULT = _cfg["obsidian"]["vault"]
# Mirror sync.py's rules exactly: a collection is active only with a real
# tag_id (blank/"<placeholder>" entries are metadata-only, sync skips them);
# folder = configured mapping, else the capitalized collection key. Scan the
# union of active-collection folders and explicitly mapped folders — the map
# also covers legacy folders whose collection left the config.
_FOLDER_MAP = _cfg["obsidian"].get("folders") or {}
_COLLECTIONS = {
    k: c for k, c in (((_cfg.get("heptabase") or {}).get("collections")
                       or {}).items())
    if isinstance(c.get("tag_id"), str) and c["tag_id"]
    and not c["tag_id"].startswith("<")}
folder_of = {k: _FOLDER_MAP.get(k, k.capitalize())
             for k in set(_COLLECTIONS) | set(_FOLDER_MAP)}
FOLDERS = sorted(set(folder_of.values())) or ["Papers"]
STATE_PATH = os.path.join(VAULT, ".hepta-sync", "state.json")
IMG_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp',
           '.pdf', '.mp4', '.mp3', '.m4a', '.wav'}

out = {k: [] for k in ["bad_ext_attachments", "missing_embeds",
                       "broken_wikilinks", "broken_blockrefs",
                       "leftover_placeholders", "duplicate_ids",
                       "state_orphans", "untracked_files"]}

# collect all note names and attachment files
notes, attachments, ids = set(), set(), {}
for folder in FOLDERS:
    fdir = os.path.join(VAULT, folder)
    if not os.path.isdir(fdir):
        continue
    for fn in os.listdir(fdir):
        if fn.endswith(".md"):
            notes.add(fn[:-3])
    att = os.path.join(fdir, "attachments")
    if os.path.isdir(att):
        for fn in os.listdir(att):
            attachments.add(fn)
            if os.path.splitext(fn)[1].lower() not in IMG_EXT:
                kind = subprocess.run(["file", "-b", os.path.join(att, fn)],
                                      capture_output=True, text=True).stdout
                out["bad_ext_attachments"].append(
                    {"file": f"{folder}/attachments/{fn}", "actual": kind.strip()[:40]})

embed_re = re.compile(r"!\[\[([^\]|#]+?)(?:\|[^\]]*)?\]\]")
wl_re = re.compile(r"(?<!\!)\[\[([^\]|#^]+?)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
blockref_re = re.compile(r"\[\[#\^([0-9a-f]{8})(?:\|[^\]]*)?\]\]")

for folder in FOLDERS:
    fdir = os.path.join(VAULT, folder)
    if not os.path.isdir(fdir):
        continue
    for fn in sorted(os.listdir(fdir)):
        if not fn.endswith(".md"):
            continue
        rel = f"{folder}/{fn}"
        text = open(os.path.join(fdir, fn)).read()
        m = re.search(r'heptabase_id: "([0-9a-f-]{36})"', text)
        if m:
            ids.setdefault(m.group(1), []).append(rel)
        for e in embed_re.findall(text):
            e = e.strip()
            if e not in attachments and e + ".md" not in notes and e not in notes:
                out["missing_embeds"].append({"in": rel, "target": e})
        for w in wl_re.findall(text):
            w = w.strip()
            if w and w not in notes:
                out["broken_wikilinks"].append({"in": rel, "target": w})
        anchors = set(re.findall(r"\^([0-9a-f]{8})\s*$", text, re.M))
        for b in blockref_re.findall(text):
            if b not in anchors:
                out["broken_blockrefs"].append({"in": rel, "ref": b})
        for p in re.findall(r"%%HEPTA[^%]*%%|HEPTA-[A-Z_]+:", text):
            out["leftover_placeholders"].append({"in": rel, "marker": p[:60]})

out["duplicate_ids"] = [{"id": k, "files": v} for k, v in ids.items() if len(v) > 1]

# --- journal bridge: vault-root daily notes (managed block only — user
# content outside the markers is theirs, not sync output to be verified)
out["journal_issues"] = []
J_START, J_END = "<!-- hepta-journal:start -->", "<!-- hepta-journal:end -->"
root_att = set()
if os.path.isdir(os.path.join(VAULT, "attachments")):
    root_att = set(os.listdir(os.path.join(VAULT, "attachments")))
for fn in sorted(os.listdir(VAULT)):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", fn):
        continue
    text = open(os.path.join(VAULT, fn)).read()
    n_s, n_e = text.count(J_START), text.count(J_END)
    if (n_s, n_e) == (0, 0):
        continue  # daily note the bridge never claimed
    if (n_s, n_e) != (1, 1) or text.index(J_START) > text.index(J_END):
        out["journal_issues"].append({"in": fn, "issue": "malformed markers"})
        continue
    blk = text.split(J_START, 1)[1].split(J_END, 1)[0]
    for e in embed_re.findall(blk):
        e = e.strip()
        if e not in root_att and e not in attachments and e not in notes:
            out["journal_issues"].append({"in": fn, "issue": f"missing embed {e}"})
    for w in wl_re.findall(blk):
        w = w.strip()
        if w and w not in notes:
            out["journal_issues"].append({"in": fn, "issue": f"broken wikilink {w}"})
    for p in re.findall(r"%%HEPTA[^%]*%%|HEPTA-[A-Z_]+:", blk):
        out["journal_issues"].append({"in": fn, "issue": f"placeholder {p[:40]}"})

if os.path.exists(STATE_PATH):
    state = json.load(open(STATE_PATH))
    tracked = set()
    for cid, st in state["cards"].items():
        coll = st['collection']
        # unknown collection (left the config entirely) → same capitalize
        # fallback sync.py would have used when it wrote the file
        rel = f"{folder_of.get(coll, coll.capitalize())}/{st['file']}.md"
        tracked.add(rel)
        if not os.path.exists(os.path.join(VAULT, rel)):
            out["state_orphans"].append({"id": cid, "file": rel})
    for folder in FOLDERS:
        fdir = os.path.join(VAULT, folder)
        if not os.path.isdir(fdir):
            continue
        for fn in sorted(os.listdir(fdir)):
            if fn.endswith(".md") and f"{folder}/{fn}" not in tracked:
                out["untracked_files"].append(f"{folder}/{fn}")

print(json.dumps({k: v for k, v in out.items() if v}, ensure_ascii=False, indent=1))
issues = sum(len(v) for v in out.values())
print(f"\n{'CLEAN' if not issues else f'{issues} issue(s) found'}", file=sys.stderr)
