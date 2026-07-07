#!/usr/bin/env python3
"""Export Heptabase card collections as hung-yi-lee external corpora.

Direction A of the hung-yi-lee ↔ Heptabase integration, two collections:

  study/overview  -> raw/external/heptabase-overview/  (source_type heptabase_overview_card)
  study/paper     -> raw/external/heptabase-papers/    (source_type heptabase_paper_card)

Each member becomes one markdown doc with the frontmatter contract
`graph build --external` expects (title / source_type / collection /
origin_id / links). Card mentions are resolved to plain card TITLES in the
body (paper names feed concept extraction); mentions whose target is ALSO an
exported member additionally land in the `links:` field (comma-separated
origin_ids) — the graph builder turns those into EXTRACTED links_to edges.
Papers additionally carry `model_names:` (curated short names from the
topology MATCH/ALIASES tables — overview section headings ARE the user's
canonical names, so this covers papers whose titles omit the model name);
the graph builder turns those into `describes` edges to concept nodes. A
MATCH-table change is detected via a stamp digest and forces a full
re-export.

The member lists are enumerated LIVE on every run — nothing about card
counts is hardcoded (per-collection floor guards only protect the prune step
from a partial scan). Backend follows ~/.config/research-cards/config.json
(`heptabase`/`both` -> heptabase CLI as source of truth; `obsidian` -> reads
the vault's collection folders directly); override with --backend.

  python3 export_hungyi_corpus.py [--out <raw/external root>]
  python3 export_hungyi_corpus.py --if-stale --build
      # freshness one-liner (safe before every `graph query`): cheap member
      # scans; NOTHING changed -> skip; only content edits -> INCREMENTAL
      # rewrite of just the changed/new/missing members; membership or a
      # title changed -> full re-export (titles/links resolve cross-doc, so
      # membership is global state). Then `graph build --external` runs only
      # when graph.local.json is missing or older than the corpus OR the
      # tracked lecture graph (covers sync-metadata/transcripts + plain
      # `graph build`).
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")

_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(_DIR, "..", "..", "_shared"))
from pmmd import Converter, safe_filename  # noqa: E402

try:
    import hbconfig
except ImportError:
    hbconfig = None

STUDY_OVERVIEW_TAG = STUDY_PAPER_TAG = None
_scan = []
try:  # all ids from config (heptabase.collections + scan_tags)
    if hbconfig:
        STUDY_OVERVIEW_TAG = hbconfig.hb_id("collections", "overviews", "tag_id")
        STUDY_PAPER_TAG = hbconfig.hb_id("collections", "papers", "tag_id")
        _scan = (hbconfig.load_config().get("heptabase") or {}).get("scan_tags") \
            or [t for t in (STUDY_PAPER_TAG,) if t]
except Exception:
    pass
_mode = None
try:
    _mode = hbconfig.load_config().get("backend") if hbconfig else None
except Exception:
    pass
if _mode != "obsidian" and not STUDY_OVERVIEW_TAG:
    sys.exit("config 缺少 heptabase.collections.overviews.tag_id（heptabase 模式必填）")
TITLE_TAGS = [STUDY_OVERVIEW_TAG] + [t for t in _scan if t != STUDY_OVERVIEW_TAG]
# key = hbconfig collections key (obsidian folder lookup); floor = minimum
# member count before the prune step may run (partial-scan guard).
COLLECTIONS = [
    {"key": "overviews", "dirname": "heptabase-overview", "collection": "overview",
     "source_type": "heptabase_overview_card", "default_tag": STUDY_OVERVIEW_TAG,
     "floor": 10, "aggregator": True},
    {"key": "papers", "dirname": "heptabase-papers", "collection": "papers",
     "source_type": "heptabase_paper_card", "default_tag": STUDY_PAPER_TAG,
     "floor": 50},
]
DEFAULT_OUT = os.path.expanduser("~/.claude/skills/hung-yi-lee/raw/external")
# Resolve only card-like mentions to titles; embeds/files/whiteboards carry no
# concept signal for the corpus and are dropped (counted + reported).
CARD_PLACEHOLDER  = re.compile(r"%%HEPTA-(?:CARD|SECTION|PDF_CARD):([0-9a-f-]{36})%%")
OTHER_PLACEHOLDER = re.compile(r"%%HEPTA-[A-Z_]+:[0-9a-zA-Z-]+%%")
# Obsidian wikilinks: [[Name]], [[Name|alias]], [[Name#anchor|alias]], [[#^block|label]]
WIKILINK = re.compile(r"\[\[([^\]|#]*)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]")


def cli(*args, fatal=True):
    try:
        r = subprocess.run(["heptabase", *args], capture_output=True, text=True,
                           timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        sys.exit(f"ERROR: heptabase {' '.join(args[:2])}: {e}")
    if r.returncode != 0:
        msg = (f"heptabase {' '.join(args[:2])} failed: "
               f"{(r.stderr or r.stdout).strip()[:160]}")
        if fatal:
            sys.exit(f"ERROR: {msg}")
        raise RuntimeError(msg)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: heptabase {' '.join(args[:2])} returned non-JSON: {e}")


def tag_cards(tag_id, include_properties=False):
    args = ["tag", "cards", tag_id]
    if include_properties:
        args.append("--include-properties")
    return cli(*args).get("cards", [])


# ── model_names: curated short names per arxiv id (describes-edge signal 1) ─────
def model_names_map():
    """arxiv_id -> [cleaned short names], from every topic snapshot's
    graph-derived `match` table (overview section-heading short names +
    ALIASES — the user-curated canonical names). Titles often omit the model
    name ("Language Models are Few-Shot Learners" = GPT-3), so this personal
    signal outranks any title parsing on the consumer side. Best-effort: no
    snapshots -> empty map (the graph builder falls back to self-mention)."""
    mapping = {}
    try:
        import topology as T
    except (Exception, SystemExit):
        # topology sys.exit()s on config gaps (e.g. obsidian mode without
        # graph.hubs) — best-effort means the EXPORT must survive that.
        return mapping
    for key in getattr(T, "TOPICS", {}):
        try:
            snap = json.load(open(T.snapshot_path(key), encoding="utf-8"))
        except Exception:
            continue
        for name, aid in snap.get("match") or []:
            short = re.split(r"[：（(]", name)[0].strip()
            if len(short) < 2:
                continue
            names = mapping.setdefault(aid, [])
            if short not in names:
                names.append(short)
    return mapping


def _match_digest(mapping):
    return hashlib.md5(json.dumps(
        {k: sorted(v) for k, v in mapping.items()},
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ── Backend member/body access ──────────────────────────────────────────────────
def resolve_backend(override):
    """heptabase | obsidian. Config `both` keeps heptabase as source of truth
    (same convention as every other skill); no config -> heptabase."""
    if override:
        return override
    if hbconfig is None:
        return "heptabase"
    try:
        backend = hbconfig.load_config().get("backend", "heptabase")
    except Exception:
        return "heptabase"
    return "obsidian" if backend == "obsidian" else "heptabase"


def collection_tag(spec):
    """heptabase tag id for a collection — config override, else constant."""
    if hbconfig is not None:
        try:
            col = hbconfig.collections(hbconfig.load_config()).get(spec["key"]) or {}
            if col.get("tag_id"):
                return col["tag_id"]
        except Exception:
            pass
    return spec["default_tag"]


def _arxiv_prop_id():
    try:
        return hbconfig.hb_id("props", "arxiv") if hbconfig else None
    except Exception:
        return None


def hb_members(spec):
    """[{id, origin_id, title, ts, arxiv}] for one collection (heptabase CLI).
    NOTE: the full tag, unfiltered — the corpus wants every study/paper card,
    not just the alphaXiv subset the obsidian sync mirrors. `arxiv` (papers
    only) keys the model_names lookup; one --include-properties scan, no
    per-card calls."""
    want_arxiv = spec["key"] == "papers" and _arxiv_prop_id()
    out = []
    for c in tag_cards(collection_tag(spec), include_properties=bool(want_arxiv)):
        aid = None
        if want_arxiv:
            for p in c.get("properties", []):
                if p.get("id") == want_arxiv and p.get("value"):
                    aid = p["value"]
                    break
        out.append({"id": c["id"], "origin_id": c["id"],
                    "title": c.get("title") or c["id"],
                    "ts": c.get("lastEditedTime") or "", "arxiv": aid})
    return out


def obs_backend():
    import backend as _backend
    cfg = hbconfig.load_config()
    return _backend.ObsidianBackend(cfg)


def obs_members(ob, spec):
    out, seen = [], {}
    for c in ob.list_cards(spec["key"]):
        props = c.get("props") or {}
        oid = props.get("heptabase_id") or c["id"]
        if oid in seen:
            # origin_id keys the stamp/manifest — a duplicate would silently
            # merge two vault files and prune one of their outputs.
            sys.exit(f"ERROR: duplicate heptabase_id {oid} in vault "
                     f"({seen[oid]} vs {c['id']}) — fix the vault first")
        seen[oid] = c["id"]
        out.append({"id": c["id"], "origin_id": oid,
                    "title": c.get("title") or c["id"],
                    "ts": str(props.get("modified") or c.get("modified") or ""),
                    "arxiv": props.get("arxiv_id")})
    return out


# ── Freshness stamp (v2: per-member ts+title, files manifest) ───────────────────
def _stamp_path(cdir):
    return os.path.join(cdir, ".export-stamp.json")


def _member_state(members):
    return {m["origin_id"]: {"ts": m["ts"], "title": m["title"]} for m in members}


def _load_stamp(cdir):
    try:
        s = json.load(open(_stamp_path(cdir), encoding="utf-8"))
        if isinstance(s, dict) and s.get("version") == 2:
            return s
    except Exception:
        pass
    return None  # missing or v1 -> treat as needing a full export


def _skill_root(out_dir):
    """Walk up from the external root to the hung-yi-lee skill root (the dir
    holding scripts/hungyi_kb.py); fall back to the default install path."""
    d = out_dir
    for _ in range(6):
        if os.path.exists(os.path.join(d, "scripts", "hungyi_kb.py")):
            return d
        d = os.path.dirname(d)
    return os.path.expanduser("~/.claude/skills/hung-yi-lee")


def _newest_corpus_mtime(out_dir):
    """Newest .md across the whole raw/external tree."""
    times = []
    for dirpath, _, files in os.walk(out_dir):
        times += [os.path.getmtime(os.path.join(dirpath, f))
                  for f in files if f.endswith(".md")]
    return max(times) if times else None


def build_local_graph(out_dir):
    """(Re)run `graph build --external`, but only when the local graph is
    missing or older than either input side: the external corpus, OR the
    tracked lecture graph (i.e. after sync-metadata/sync-transcripts +
    plain `graph build`) — so the freshness one-liner stays the single
    entry point for BOTH data paths. Prefers the skill's conda env."""
    root = _skill_root(out_dir)
    kb = os.path.join(root, "scripts", "hungyi_kb.py")
    if not os.path.exists(kb):
        sys.exit(f"ERROR: --build could not locate hungyi_kb.py under {root}")
    local = os.path.join(root, "wiki", "graph", "graph.local.json")
    refs = []
    newest = _newest_corpus_mtime(out_dir)
    if newest:
        refs.append(newest)
    tracked = os.path.join(root, "wiki", "graph", "graph.json")
    if os.path.exists(tracked):
        refs.append(os.path.getmtime(tracked))
    if refs and os.path.exists(local) and os.path.getmtime(local) >= max(refs):
        print("local graph already newer than corpus + lecture graph — build skipped")
        return
    import shutil
    cmd = (["conda", "run", "-n", "hung-yi-lee"] if shutil.which("conda") else []) + \
          ["python3", kb, "graph", "build", "--external"]
    r = subprocess.run(cmd, cwd=root)
    if r.returncode != 0:
        sys.exit(f"ERROR: graph build --external failed (rc={r.returncode})")
    _alignment_notice(root)


def _alignment_notice(root):
    """After a REBUILD (only — fresh runs never reach here), surface the top
    alignment candidates so drift shows up as soon as new data lands. The
    miner only suggests; the merge-vs-align call stays human (taxonomy
    judgment), so this prints a condensed notice, never edits the table.
    Best-effort: a miner hiccup must not fail the freshness pipeline."""
    miner = os.path.join(root, "scripts", "suggest_alignments.py")
    if not os.path.exists(miner):
        return
    try:
        r = subprocess.run([sys.executable, miner, "--top", "5"],
                           capture_output=True, text=True, timeout=120,
                           cwd=root)
        lines = [l for l in (r.stdout or "").splitlines() if l.strip()]
        if r.returncode != 0 or not lines:
            return
        head = next((l for l in lines if "candidates" in l), None)
        if head is None or head.startswith("no candidates"):
            return
        print(f"[alignment] {head.strip()}")
        pair_lines = [l for l in lines if "⇄" in l][:5]
        for l in pair_lines:
            print(f"[alignment] {l.strip()}")
        print("[alignment] review: python3 scripts/suggest_alignments.py "
              "(graph_alignment.json — merge vs align 判準見表頭)")
    except Exception as e:
        print(f"[alignment] candidate scan skipped: {e}", file=sys.stderr)


# ── Body rendering ───────────────────────────────────────────────────────────────
def hb_render(member, titles, member_origin, links, unresolved):
    """heptabase: PM JSON -> markdown; card mentions -> plain titles; member
    targets also collected into `links` (origin_ids, deduped, in order)."""
    # non-fatal read: a trashed card can linger in the tag index — the caller
    # records it as unreadable and moves on instead of killing the export.
    note = cli("note", "read", member["id"], fatal=False)
    if "content" not in note:
        raise RuntimeError(f"note read {member['id']} returned no content field")
    doc = json.loads(note["content"])
    body = Converter({"id": member["id"], "title": member["title"]}).convert(doc)

    def _resolve(m):
        cid = m.group(1)
        if cid in member_origin and cid != member["origin_id"] \
                and member_origin[cid] not in links:
            links.append(member_origin[cid])
        t = titles.get(cid)
        if t is None:
            unresolved[0] += 1
            return ""
        return t
    body = CARD_PLACEHOLDER.sub(_resolve, body)
    return OTHER_PLACEHOLDER.sub("", body)


def obs_render(ob, member, name_map, links):
    """obsidian: vault body is already markdown; wikilinks -> plain text;
    member targets collected into `links`."""
    body = ob.read_card(member["id"]).md

    def _resolve(m):
        name, alias = m.group(1).strip(), (m.group(2) or "").strip()
        target = name_map.get(name)
        if target and target != member["origin_id"] and target not in links:
            links.append(target)
        return alias or name
    return WIKILINK.sub(_resolve, body)


def write_doc(cdir, spec, member, body, links, used_names, model_names=None):
    # Heptabase titles have no newlines; full-width quotes keep the naive
    # frontmatter parser on the consumer side safe.
    title = member["title"]
    fm_title = title.replace('"', "”").replace("\n", " ")
    links_line = f'links: "{",".join(links)}"\n' if links else ""
    # curated short names (describes-edge signal 1); same quote-safety as title
    mn = [n.replace('"', "”").replace(",", "，") for n in (model_names or [])]
    mn_line = f'model_names: "{",".join(mn)}"\n' if mn else ""
    # aggregator docs curate MANY subjects — consumers must not infer a
    # single model identity from mention frequency (see graph builder).
    agg_line = "aggregator: true\n" if spec.get("aggregator") else ""
    md = (f"---\n"
          f'title: "{fm_title}"\n'
          f"source_type: {spec['source_type']}\n"
          f"collection: {spec['collection']}\n"
          f"origin_id: {member['origin_id']}\n"
          f"{links_line}"
          f"{mn_line}"
          f"{agg_line}"
          f"---\n\n# {title}\n\n{body}\n")
    # md5 of the FULL origin_id: uniform uniqueness for both backends (raw
    # obsidian ids share the "Papers/..." prefix, so a raw prefix would
    # collide systematically), plus a same-run collision guard.
    suffix = hashlib.md5(member["origin_id"].encode()).hexdigest()[:8]
    fname = f"{safe_filename(title)[:80]}-{suffix}.md"
    if fname in used_names:
        sys.exit(f"ERROR: filename collision {fname!r} "
                 f"(origin {member['origin_id']}) — refusing to overwrite")
    used_names.add(fname)
    with open(os.path.join(cdir, fname), "w", encoding="utf-8") as f:
        f.write(md)
    return fname


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help="raw/external ROOT (collections go in subdirs)")
    ap.add_argument("--backend", choices=["heptabase", "obsidian"], default=None,
                    help="override the config backend for this run")
    ap.add_argument("--if-stale", action="store_true",
                    help="skip/minimize the export when members are unchanged")
    ap.add_argument("--build", action="store_true",
                    help="then run `graph build --external` when the local "
                         "graph is older than the corpus or lecture graph")
    args = ap.parse_args()
    args.out = os.path.abspath(os.path.expanduser(args.out))
    os.makedirs(args.out, exist_ok=True)
    if os.path.basename(args.out) != "external":
        print(f"WARNING: --out {args.out} is not a raw/external root — "
              f"`graph build --external` will NOT ingest it")

    backend = resolve_backend(args.backend)
    ob = obs_backend() if backend == "obsidian" else None

    # 1) Enumerate all collections (cheap scans) + floor guards FIRST — a
    # suspiciously small scan must abort before it can match a (bad) stamp
    # or become authoritative for the prune step.
    members_by = {}
    for spec in COLLECTIONS:
        members = obs_members(ob, spec) if ob else hb_members(spec)
        if len(members) < spec["floor"]:
            sys.exit(f"ERROR: {spec['collection']} scan returned only "
                     f"{len(members)} members (floor {spec['floor']}) — aborting")
        members_by[spec["collection"]] = members

    # 2) Decide the run mode from the per-collection stamps.
    #    fresh        — nothing changed anywhere, files intact
    #    incremental  — same membership + titles, only content edits
    #    full         — membership/title changed, stamp missing/old-format
    #    (titles + links resolve ACROSS docs, so membership/titles are global
    #    state: any change there forces a full re-export of everything.)
    mn_map = model_names_map()
    mn_digest = _match_digest(mn_map)
    stamps, mode = {}, "incremental"
    fresh = True
    for spec in COLLECTIONS:
        cdir = os.path.join(args.out, spec["dirname"])
        os.makedirs(cdir, exist_ok=True)
        cur = _member_state(members_by[spec["collection"]])
        prev = _load_stamp(cdir)
        if prev is not None and prev.get("backend") != backend:
            # different backend = different id/ts scheme and body renderer —
            # its stamp must not be trusted for freshness or incrementality.
            prev = None
        if prev is not None and prev.get("match_digest") != mn_digest:
            # model_names come from the topology MATCH tables, not from the
            # members' lastEditedTime — a refreshed snapshot must re-emit the
            # frontmatter even though no card changed. Conservative: full.
            prev = None
        stamps[spec["collection"]] = (cdir, cur, prev)
        if prev is None:
            mode, fresh = "full", False
            continue
        if set(prev["members"]) != set(cur) or any(
                prev["members"][k]["title"] != v["title"] for k, v in cur.items()
                if k in prev["members"]):
            mode, fresh = "full", False
            continue
        files = prev.get("files") or {}
        known_unreadable = set(prev.get("unreadable") or [])
        missing = [k for k in cur
                   if k not in known_unreadable
                   and (k not in files
                        or not os.path.exists(os.path.join(cdir, files[k])))]
        changed = [k for k, v in cur.items() if prev["members"][k]["ts"] != v["ts"]]
        if missing or changed:
            fresh = False

    if args.if_stale and fresh:
        total = sum(len(m) for m in members_by.values())
        print(f"corpus fresh ({total} members across {len(COLLECTIONS)} "
              f"collections) — export skipped")
        if args.build:
            build_local_graph(args.out)
        return

    # 3) Cross-collection maps for title / link resolution.
    all_members = [m for ms in members_by.values() for m in ms]
    if ob:
        titles = None
        # basename AND folder-qualified keys; ambiguous basenames resolve to
        # NO link (a wrong link is worse than a dropped one).
        name_map, dupes = {}, set()
        for m in all_members:
            base = m["id"].split("/", 1)[-1]
            if base in name_map and name_map[base] != m["origin_id"]:
                dupes.add(base)
            name_map[base] = m["origin_id"]
            name_map[m["id"]] = m["origin_id"]
        for base in dupes:
            print(f"  WARNING: ambiguous note name {base!r} across folders — "
                  f"bare [[{base}]] wikilinks will not produce links")
            name_map.pop(base, None)
    else:
        # seed with the members themselves FIRST (their tags may be config
        # overrides outside TITLE_TAGS), then widen to the usual tag universe.
        titles = {m["origin_id"]: m["title"] for m in all_members}
        for tg in TITLE_TAGS:
            for c in tag_cards(tg):
                titles.setdefault(c["id"], c.get("title", ""))
        name_map = None
    member_origin = {m["origin_id"]: m["origin_id"] for m in all_members}

    # 4) Export per collection (full, or only changed/new/missing members).
    unresolved = [0]
    grand = {"rewrote": 0, "skipped": 0, "pruned": 0}
    for spec in COLLECTIONS:
        cname = spec["collection"]
        cdir, cur, prev = stamps[cname]
        prev_files = (prev or {}).get("files") or {}
        prev_unreadable = set((prev or {}).get("unreadable") or [])
        todo, files, unreadable = [], {}, []
        for m in sorted(members_by[cname], key=lambda x: x["title"]):
            oid = m["origin_id"]
            fname = prev_files.get(oid)
            same_ts = (mode == "incremental" and prev is not None
                       and prev["members"].get(oid, {}).get("ts") == m["ts"])
            if same_ts and oid in prev_unreadable:
                # known-dead card (e.g. trashed but still in the tag index):
                # don't retry until its ts changes (restore/edit bumps it).
                unreadable.append(oid)
                grand["skipped"] += 1
            elif same_ts and fname and os.path.exists(os.path.join(cdir, fname)):
                files[oid] = fname
                grand["skipped"] += 1
            else:
                todo.append(m)
        used_names = set(files.values())
        for m in todo:
            links = []
            oid = m["origin_id"]
            try:
                body = (obs_render(ob, m, name_map, links) if ob
                        else hb_render(m, titles, member_origin, links, unresolved))
            except RuntimeError as e:
                print(f"  !! unreadable, skipped: {m['title'][:50]} "
                      f"({oid[:8]}) — {e}")
                unreadable.append(oid)
                # a transient read failure must NOT cost us the existing doc:
                # keep the previous file in the manifest so prune spares it
                # (stale content beats a hole; retried when ts changes).
                old = prev_files.get(oid)
                if old and os.path.exists(os.path.join(cdir, old)):
                    files[oid] = old
                    used_names.add(old)
                continue
            mn = (mn_map.get(m.get("arxiv")) if spec["key"] == "papers"
                  and m.get("arxiv") else None)
            files[oid] = write_doc(cdir, spec, m, body, links, used_names,
                                   model_names=mn)
            grand["rewrote"] += 1
        # Prune: our-marker files not in the expected manifest (card left the
        # tag, or was retitled — the fresh filename is already in `files`).
        expected = set(files.values())
        for fname in os.listdir(cdir):
            if not fname.endswith(".md") or fname in expected:
                continue
            head = open(os.path.join(cdir, fname), encoding="utf-8").read(400)
            if f"source_type: {spec['source_type']}" not in head:
                continue  # not ours — never touch other corpora docs
            os.unlink(os.path.join(cdir, fname))
            grand["pruned"] += 1
        with open(_stamp_path(cdir), "w", encoding="utf-8") as f:
            json.dump({"version": 2, "backend": backend, "members": cur,
                       "files": files, "unreadable": sorted(unreadable),
                       "match_digest": mn_digest},
                      f, ensure_ascii=False)
        print(f"  {cname}: {len(members_by[cname])} members "
              f"({len(todo)} rewritten"
              + (f", {len(unreadable)} unreadable" if unreadable else "") + ")")

    print(f"\n[{backend}] {mode}: rewrote {grand['rewrote']} / skipped "
          f"{grand['skipped']} / pruned {grand['pruned']} -> {args.out}"
          + (f" ({unresolved[0]} unresolved mentions dropped)"
             if unresolved[0] else ""))
    if args.build:
        build_local_graph(args.out)
    else:
        print("next: conda run -n hung-yi-lee python3 "
              "~/.claude/skills/hung-yi-lee/scripts/hungyi_kb.py graph build --external")


if __name__ == "__main__":
    try:
        import hbconfig as _hbc
        if not _hbc.feature_enabled("study"):
            sys.exit("study 方向已在 config features.study 停用")
    except ImportError:
        pass
    main()
