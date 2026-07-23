#!/usr/bin/env python3
"""Append markdown to a project card; when the card would exceed Heptabase's
per-card size cap, spill into a continuation sub-card and link to it.

A project card may become a CHAIN — the append-only log grows past one card:

    entry (母卡)  →  續1  →  續2  →  …  →  tail

- `resolve_card.py` / the `.heptabase-card` marker / the registry always point at
  the ENTRY card (stable project identity — never re-pinned to a child).
- Appends WALK the chain to the current TAIL and append there.
- When appending to the tail would cross the cap, a new child card is created and
  the tail gets a machine-parseable continuation link:

      ▶ 續卡（本卡已達容量上限）：[[card:<child_id>]]

  The next append re-walks entry→…→child (the new tail). `hb read` / `heptabase
  note read` both surface card links as `[[card:<uuid>]]`, so the chain is
  recoverable from the card body alone (no side registry).

Transport is auto-picked like create_project_card.py, and — as there — the local
`heptabase` CLI and the `hb` bridge are driven as RAW CLIs (native markdown; id
links like `[[card:<uuid>]]` pass through verbatim). Only backend=obsidian goes
through the backend abstraction:
  - backend=obsidian  → file-backed vault: NO hard cap → always a plain append.
  - local `heptabase` CLI (Mac) → read/append/create; continuation child tagged.
  - `hb` bridge (cluster) → read/append/create; bridge has no tag capability, so
    the child card is left UNTAGGED and flagged for a Mac-side follow-up.

The Mac-only `project-card-merge` later consolidates a chain back into one card
(it needs overwrite/delete, which the append-only bridge lacks) — see
CARD-OVERFLOW.md for that half's spec.

Usage:
    python3 append_card.py --card <ENTRY_ID> --content-file section.md
    echo "<md>" | python3 append_card.py --card <ENTRY_ID> --content -
    python3 append_card.py --card <ENTRY_ID> --content-file section.md --dry-run
    python3 append_card.py --self-test        # pure-logic unit tests, no I/O

Prints one JSON line:
  {entry, tail, appended_to, overflowed, child, chain_len, transport, note}
Stdlib only (imports the plugin's pmmd/hbconfig lazily on the heptabase path).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import datetime
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                "..", "_shared"))

# ---- tunables (overridable via config heptabase.collections.projects.*) ------
# Heptabase's practical per-card cap; card-rewrite/rewrite_lib.py uses 100000 on
# the serialized doc. Capacity decisions compare in STORED units (hb --json
# content length; markdown converts via est_stored_len(), erring high); the
# THRESHOLD < cap margin absorbs UUID inflation and future appends.
DEFAULT_CAP = 100000
DEFAULT_THRESHOLD = 80000          # spill before we get close to the real cap
NEAR_CAP_BAND = 20000              # within this of threshold → force sync (no-queue)
CHAIN_MAX = 64                     # cycle / runaway guard when walking the chain
LINK_MARK = "續卡（本卡已達容量上限）"   # sentinel that precedes the card-link
HB_OUTBOX = os.path.expanduser("~/.heptabase-bridge/outbox.jsonl")  # hb offline queue
HB_PROJECT_LOG_EVENTS = os.path.expanduser(
    os.environ.get("HB_PROJECT_LOG_EVENT_QUEUE",
                   "~/.heptabase-bridge/project-log-events.jsonl"))
_UUID = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
# The card link renders differently per read path: `hb read` → [[card:<id>]];
# pmmd.Converter (local heptabase read) → %%HEPTA-CARD:<id>%%. Match the id right
# after the sentinel, ON THE SAME LINE, wrapper-agnostic (whichever form appears).
_CONT_RE = re.compile(re.escape(LINK_MARK) + r"[^\n]*?(" + _UUID + r")")


# ---- pure logic (unit-tested by --self-test; no I/O) -------------------------
def parse_continuation(body):
    """Return the child card id this card continues into, or None if it's a
    tail. Uses the LAST sentinel match so a card is never mistaken mid-body."""
    matches = _CONT_RE.findall(body or "")
    return matches[-1] if matches else None


def would_overflow(current_len, add_len, threshold=DEFAULT_THRESHOLD):
    # +len(link) headroom so the spill note itself never tips a borderline card.
    return current_len + add_len + 160 > threshold


def pending_outbox_len(card_id, outbox_path=None):
    """Estimated stored bytes already QUEUED for this card in hb's offline
    outbox but not yet landed. Counted into the capacity check so repeated
    offline appends can't accumulate past the cap unseen (each `hb read` only
    reflects landed content). Records look like
    {"method":"POST","path":"/note/<id>/append","body":{"content": md}}."""
    total = 0
    try:
        with open(outbox_path or HB_OUTBOX, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if card_id not in (rec.get("path") or ""):
                    continue
                body = rec.get("body")
                if isinstance(body, dict):
                    md = body.get("content")
                    md = md if isinstance(md, str) else json.dumps(body, ensure_ascii=False)
                else:
                    md = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
                total += est_stored_len(md)
    except FileNotFoundError:
        pass
    return total


def enqueue_project_log_event(report, path=None):
    """Durably tell the Mac drainer that a bridge-created log is ready for
    repair → note-sync → canvas refresh.

    The event is deliberately a separate cluster-local JSONL queue rather than
    another bridge write: online and offline log paths converge on the same
    host-pulled handoff, and the project log itself never depends on a Mac-side
    automation hook being installed.  One O_APPEND write keeps concurrent
    project sessions from interleaving records."""
    event = {
        "schema": 1,
        "kind": "project-card-log",
        "event_id": str(uuid.uuid4()),
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "entry_card": report["entry"],
        "log_card": report["log_card"],
        "timeline_card": report.get("appended_to") or report.get("tail")
                         or report["entry"],
        # A spill may have created a child successfully but failed to seal the
        # old tail's text-form ▶續卡 edge. Pinpoint repair of the new child
        # cannot recover that edge; the Mac must walk+seal from the entry.
        "repair_chain": bool(report.get("overflowed")
                             and not report.get("sealed")),
    }
    target = os.path.expanduser(path or HB_PROJECT_LOG_EVENTS)
    os.makedirs(os.path.dirname(target) or ".", mode=0o700, exist_ok=True)
    line = (json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            + "\n").encode()
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "ab") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
    return event


def est_stored_len(md):
    """Upper bound on the STORED (ProseMirror) size of a markdown string.
    MEASURED, not guessed: parse through the repo's own md2pm (the same
    grammar the backends use) and size the serialized nodes. Empirically this
    is >= the post-save stored size for every content family tested (plain
    prose / bold / italic / links / experiment logs) because the serializer
    keeps null attrs the app strips on save; x1.1 adds headroom for constructs
    outside that test set. Tight enough not to false-reject normal appends
    (a 30K-stored bold log measures ~41K, far from an 80K threshold), safe
    enough that mark-heavy pathologies measure ABOVE their stored size.
    Falls back to a deliberately-very-high mark-counting heuristic if the
    parser is unavailable or rejects the input (e.g. unknown block anchor)."""
    try:
        import md2pm
        ctx = {"self_id": "", "workspace": "", "name_to_card": {},
               "attach_to_fileid": {}, "anchor_short_to_full": {}}
        nodes = md2pm.BlockParser(ctx).parse(md)
        return int(len(json.dumps(nodes, ensure_ascii=False)) * 1.1)
    except Exception:
        lines = md.count("\n") + 1
        inline_cost = (130 * (md.count("**") // 2)
                       + 30 * md.count("*")
                       + 60 * md.count("`")
                       + 130 * md.count("[[")
                       + 180 * md.count("](")
                       + 130 * (md.count("~~") // 2)
                       + 130 * (md.count("==") // 2)
                       + 130 * md.count("<u>")
                       + 130 * md.count("<span")
                       + 130 * (md.count("$") // 2))
        return int(len(md) * 1.5) + 200 * lines + inline_cost


def seal_sentinel_paragraphs(nodes, child_id=None):
    """Convert TEXT-form continuation sentinels into real card-mention nodes,
    in place. The heptabase CLI's markdown append does NOT recognize
    `[[card:id]]` (verified 2026-07-17) — a spill writes the tail→child link
    as plain text, which PM-level chain parsers (merge scan, repair, orphan
    tooling) cannot see. A paragraph qualifies when it carries the LINK_MARK
    text, has NO card node yet, and its text contains a `[[card:<uuid>]]`
    literal (matching child_id when given). Returns the number of paragraphs
    rebuilt into the canonical sentinel form."""
    pat = re.compile(r"\[\[card:(" + _UUID + r")\]\]")
    sealed = 0
    for n in nodes or []:
        if n.get("type") != "paragraph":
            continue
        kids = n.get("content") or []
        if any(c.get("type") == "card" for c in kids):
            continue
        full = "".join(c.get("text", "") for c in kids if c.get("type") == "text")
        idx = full.find(LINK_MARK)
        if idx < 0:
            continue
        # the card literal must come AFTER the marker — prose like
        # "[[card:x]] … 續卡（…）" is deliberately NOT a sentinel (same rule
        # as last_sentinel_idx / the merge parser), and sealing it would
        # fabricate a bogus chain edge
        m = pat.search(full, idx + len(LINK_MARK))
        if not m or (child_id and m.group(1) != child_id):
            continue
        n["content"] = [
            {"type": "text", "text": "▶ "},
            {"type": "text", "marks": [{"type": "strong"}], "text": LINK_MARK},
            {"type": "text", "text": "："},
            {"type": "card", "attrs": {"cardId": m.group(1)}},
        ]
        sealed += 1
    return sealed


BACKREF_MARK = "母卡："       # continuation child → entry (chain)
PROJECTREF_MARK = "專案："     # log/progress card → its project card (same seal shape)


def seal_backref_paragraphs(nodes, parent_id=None, marks=None):
    """Convert a TEXT-form parent back-reference at the top of a child card
    (`…母卡：[[card:<entry>]]。…` from child_header — or a progress/log card's
    `專案：[[card:<project>]]　…` header, cf. project-card-repair) into a real
    card-mention node, in place — the sentinel seal fixes the tail→child edge,
    but the child→parent link the UI navigates by was still plain text (gap
    observed 2026-07-18; the log→project variant 2026-07-23). Unlike the
    sentinel rebuild, the surrounding prose is kept: the matching text node is
    SPLIT into text + card + text. Paragraphs that carry the sentinel LINK_MARK
    are left to seal_sentinel_paragraphs; ones that already contain a card node
    are done (idempotent).

    `marks` = which header labels qualify a paragraph (each must precede the
    `[[card:…]]` literal in the same paragraph). Defaults to (BACKREF_MARK,) so
    existing callers (repair_chain chain-walk) are unchanged; pass
    (BACKREF_MARK, PROJECTREF_MARK) to also seal log→project back-refs. Returns
    the number of paragraphs sealed."""
    marks = tuple(marks) if marks else (BACKREF_MARK,)
    pat = re.compile(r"\[\[card:(" + _UUID + r")\]\]")
    sealed = 0
    for n in nodes or []:
        if sealed:
            break                         # a card has exactly one back-ref
        if n.get("type") != "paragraph":
            continue
        kids = n.get("content") or []
        if any(c.get("type") == "card" for c in kids):
            continue
        full = "".join(c.get("text", "") for c in kids
                       if c.get("type") == "text")
        if LINK_MARK in full:
            continue                      # a sentinel — not ours to touch
        # only a header back-ref qualifies: one of `marks` must precede the
        # literal IN THE SAME paragraph — user prose merely quoting
        # [[card:id]] must never be rewritten
        prefix = full.split("[[card:", 1)[0]
        if not any(mk in prefix for mk in marks):
            continue
        for i, c in enumerate(kids):
            if c.get("type") != "text":
                continue
            m = pat.search(c.get("text", ""))
            if not m or (parent_id and m.group(1) != parent_id):
                continue
            marks = c.get("marks")
            pieces = []
            before, after = c["text"][:m.start()], c["text"][m.end():]
            if before:
                t = {"type": "text", "text": before}
                if marks:
                    t["marks"] = marks
                pieces.append(t)
            pieces.append({"type": "card", "attrs": {"cardId": m.group(1)}})
            if after:
                t = {"type": "text", "text": after}
                if marks:
                    t["marks"] = marks
                pieces.append(t)
            n["content"] = kids[:i] + pieces + kids[i + 1:]
            sealed += 1
            break
    return sealed


LOG_MARK = "📎"          # timeline link-line prefix: NOT yet distilled
LOG_DONE_MARK = "📗"     # distilled by project-card-merge — link kept forever
TIMELINE_HEADING = "📜 log 時間線"   # merge collects 📗 lines under this H2


def log_link_line(log_id, summary, date_str=None):
    """One human-readable timeline line for the chain tail. Kept to a single
    paragraph (NOT a bullet) so the seal pass can rebuild the [[card:…]]
    literal into a real card node at the top level."""
    import datetime
    d = date_str or datetime.date.today().isoformat()
    return f"\n{LOG_MARK} {d}　[[card:{log_id}]]　{summary}\n"


def seal_loglink_paragraphs(nodes):
    """Convert TEXT-form timeline link lines (📎 date [[card:id]] summary)
    into real card nodes, keeping the surrounding prose — same split shape
    as seal_backref_paragraphs. Idempotent; non-📎 paragraphs untouched."""
    pat = re.compile(r"\[\[card:(" + _UUID + r")\]\]")
    sealed = 0
    for n in nodes or []:
        if n.get("type") != "paragraph":
            continue
        kids = n.get("content") or []
        if any(c.get("type") == "card" for c in kids):
            continue
        full = "".join(c.get("text", "") for c in kids
                       if c.get("type") == "text")
        if not full.strip().startswith(LOG_MARK):
            continue
        for i, c in enumerate(kids):
            if c.get("type") != "text":
                continue
            m = pat.search(c.get("text", ""))
            if not m:
                continue
            marks = c.get("marks")
            pieces = []
            before, after = c["text"][:m.start()], c["text"][m.end():]
            if before:
                seg = {"type": "text", "text": before}
                if marks:
                    seg["marks"] = marks
                pieces.append(seg)
            pieces.append({"type": "card", "attrs": {"cardId": m.group(1)}})
            if after:
                seg = {"type": "text", "text": after}
                if marks:
                    seg["marks"] = marks
                pieces.append(seg)
            n["content"] = kids[:i] + pieces + kids[i + 1:]
            sealed += 1
            break
    return sealed


def find_relation_pid(props, tag, pname):
    """From `card properties` / `hb props` output, the id of <tag>'s relation
    property named <pname> — the chain convention: a continuation child (or a
    log card) points this property back at its entry card, so tag-level scans
    can tell entries from non-entries. None when the schema has no such
    property (feature quietly off for that tag)."""
    for tg in (props.get("tags") or []):
        if tg.get("tagName") != tag:
            continue
        for p in (tg.get("properties") or []):
            if p.get("type") == "relation" and p.get("name") == pname:
                return p.get("id")
        return None          # tag present but no matching relation property
    return None


def continuation_block(child_id):
    return f"\n\n---\n▶ **{LINK_MARK}**：[[card:{child_id}]]\n"


def child_title(entry_title, n):
    base = entry_title or "project card"
    return f"{base} · 續 {n}"


def child_header(entry_title, entry_id, n):
    """A child opens with a back-reference so it's self-explanatory in-app."""
    return (f"# {child_title(entry_title, n)}\n\n"
            f"（{entry_title or '母卡'} 的續卡 {n}／append 溢位；"
            f"母卡：[[card:{entry_id}]]。整併請用 project-card-merge。）\n\n")


# ---- config + transport ------------------------------------------------------
class BridgeDown(Exception):
    """hb bridge unreachable (Mac asleep / tunnel down / timeout) — reads are
    impossible, but the offline outbox can still QUEUE writes."""


def sh(args, timeout=60):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def hb_read_cmd(args, timeout=60):
    """Run an hb READ; raise BridgeDown when the bridge is unreachable instead
    of exiting, so the caller can decide on an offline fallback."""
    try:
        r = sh(args, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise BridgeDown(f"{' '.join(args[:3])} timed out（Mac/tunnel 離線？）")
    if r.returncode != 0:
        err = (r.stderr or "") + (r.stdout or "")
        if re.search(r"unreachable|URLError|Connection refused|timed out|Bad Gateway",
                     err, re.IGNORECASE):
            raise BridgeDown(err.strip()[:200])
        sys.exit(f"{' '.join(args[:3])} 失敗：{err.strip()[:200]}")
    return r


def hb_write(args_prefix, md, timeout=60):
    """Run an hb write passing content via `-f <tempfile>` — markdown starting
    with '-'/'--- ' would otherwise be eaten by hb's argparse as options."""
    fd, path = tempfile.mkstemp(suffix=".md", text=True)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(md)
        return sh(args_prefix + ["-f", path], timeout=timeout)
    finally:
        os.unlink(path)


def load_cfg():
    """Missing config -> {} (auto transport). INVALID existing config -> fail
    fast, exactly like create_project_card.py — a broken backend=obsidian must
    never silently fall back to Heptabase, and a broken config on a cluster must
    not silently write to the hb bridge."""
    try:
        import hbconfig
    except Exception:
        return {}
    if not os.path.exists(hbconfig.CONFIG_PATH):
        return {}
    try:
        return hbconfig.load_config()
    except Exception as e:
        sys.exit(f"config 讀取失敗（{hbconfig.CONFIG_PATH}）：{e}"
                 f"——修正後再 append，避免寫到錯的 backend")


def _projects_cfg(cfg):
    return (((cfg.get("heptabase") or {}).get("collections") or {})
            .get("projects") or {})


def tag_name(cfg):
    t = _projects_cfg(cfg).get("tag_name")
    if isinstance(t, str) and t.startswith("<") and t.endswith(">"):
        t = None
    return t or "project"


def relation_property_name(cfg):
    """Name of the tag's relation property that points back at the entry card.
    Defaults to the tag's own name (the schema convention: tag `project` has a
    relation property `project`); config relation_property overrides."""
    n = _projects_cfg(cfg).get("relation_property")
    if isinstance(n, str) and n.startswith("<") and n.endswith(">"):
        n = None
    return n or tag_name(cfg)


def log_tag_name(cfg):
    """Tag for log-as-card cards. Defaults to the projects tag's `progress`
    CHILD tag（`project/progress`）— log cards are progress records, not
    project cards, so they get their own family and stop flooding the
    project-tag scan. config log_tag_name overrides (set it equal to
    tag_name to restore the pre-0.40 behaviour)."""
    n = _projects_cfg(cfg).get("log_tag_name")
    if isinstance(n, str) and n.startswith("<") and n.endswith(">"):
        n = None
    return n or f"{tag_name(cfg)}/progress"


def cap_threshold(cfg):
    proj = _projects_cfg(cfg)
    try:
        return (int(proj.get("char_cap", DEFAULT_CAP)),
                int(proj.get("spill_threshold", DEFAULT_THRESHOLD)))
    except (TypeError, ValueError):
        return DEFAULT_CAP, DEFAULT_THRESHOLD


def detect_transport(cfg):
    """obsidian (config) > local heptabase CLI > hb bridge."""
    if cfg.get("backend") == "obsidian":
        return "obsidian"
    if sh(["which", "heptabase"]).returncode == 0:
        return "heptabase"
    if sh(["which", "hb"]).returncode == 0:
        return "hb"
    sys.exit("找不到 heptabase CLI 或 hb bridge（config backend 也非 obsidian）")


class Transport:
    """read/append/create over the active backend. create -> (id, tagged).

    heptabase & hb are driven as raw CLIs (native markdown; [[card:uuid]] links
    pass through verbatim). obsidian goes through the backend abstraction (and
    never spills — files have no hard cap)."""
    def __init__(self, kind, cfg):
        self.kind = kind
        self.cfg = cfg
        self.tag = tag_name(cfg)
        self._obe = None
        if kind == "obsidian":
            import backend
            self._obe = backend.get_backend(cfg)

    # --- heptabase note read -> markdown, via the same converter backend uses --
    def _hepta_read(self, card_id):
        r = sh(["heptabase", "note", "read", card_id])
        if r.returncode != 0:
            sys.exit(f"heptabase note read {card_id} 失敗：{r.stderr[:200]}")
        return json.loads(r.stdout)

    def _pm_to_md(self, note, card_id):
        from pmmd import Converter
        conv = Converter({"id": card_id, "title": note.get("title") or ""})
        return conv.convert(json.loads(note["content"]))

    def read(self, card_id):
        if self.kind == "hb":
            return hb_read_cmd(["hb", "read", card_id]).stdout
        if self.kind == "heptabase":
            return self._pm_to_md(self._hepta_read(card_id), card_id)
        return self._obe.read_card(card_id).md or ""

    def title(self, card_id):
        if self.kind == "heptabase":
            return self._hepta_read(card_id).get("title") or ""
        if self.kind == "obsidian":
            return self._obe.read_card(card_id).title or ""
        m = re.match(r"#\s+(.+)", self.read(card_id).lstrip())
        return m.group(1).strip() if m else ""

    def _seal_card(self, card_id, seal_fn):
        """read → transform(doc content nodes) → optimistic-locked save.
        NOT _hepta_read(): that helper sys.exit()s on failure, which
        `except Exception` cannot catch — and a transient read error here
        must never fail a spill that already landed (a retried spill would
        create a duplicate child). Best-effort: bool."""
        try:
            r = sh(["heptabase", "note", "read", card_id])
            if r.returncode != 0:
                return False
            note = json.loads(r.stdout)
            doc = json.loads(note["content"])
            if not seal_fn(doc.get("content")):
                return False
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                             encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False)
                tmp = f.name
            try:
                r = sh(["heptabase", "note", "save", card_id,
                        "--content-md5", note.get("contentMd5") or "",
                        "--content-file", tmp])
            finally:
                os.unlink(tmp)
            return r.returncode == 0
        except Exception:
            return False

    def seal_continuation(self, tail_id, child_id, entry_id=None):
        """Rebuild the just-written TEXT-form links into real card-mention
        nodes: the tail→child sentinel, AND (given entry_id) the child's
        opening back-reference to the entry card — both land as plain text
        because the CLI's markdown append doesn't parse [[card:id]].
        heptabase transport does it locally via `note save`; the hb bridge
        via its `seal` verb (server-side fixed transform; clients/servers
        without the third arg gracefully degrade to sentinel-only).
        obsidian never spills. Best-effort: the return value reports the
        SENTINEL seal (the chain-parser-critical edge); the back-ref is
        UI-navigation polish and never fails the spill."""
        if self.kind == "hb":
            try:
                args = ["hb", "seal", tail_id, child_id]
                r = sh(args + ([entry_id] if entry_id else []))
                if r.returncode != 0 and entry_id:
                    r = sh(args)          # old client: no third positional
                if r.returncode != 0:
                    return False
                out = json.loads(r.stdout.strip().splitlines()[-1])
                return int(out.get("sealed", 0)) > 0
            except Exception:
                return False
        if self.kind != "heptabase":
            return False
        ok = self._seal_card(tail_id,
                             lambda ns: seal_sentinel_paragraphs(ns, child_id))
        if entry_id:
            self._seal_card(child_id,
                            lambda ns: seal_backref_paragraphs(ns, entry_id))
        return ok

    def size(self, card_id):
        """Serialized-payload length for the capacity decision. `read()` returns
        RENDERED markdown, where a preserved figure collapses to `![image]`; the
        stored ProseMirror (with data-URL figures) can be far larger and is what
        actually hits Heptabase's cap. Measure that instead."""
        if self.kind == "hb":
            r = hb_read_cmd(["hb", "read", card_id, "--json"])
            try:  # same {id,title,content,…} shape as `heptabase note read` —
                # measure the stored content only, not the JSON envelope/escaping
                content = json.loads(r.stdout).get("content") or ""
            except json.JSONDecodeError as e:
                sys.exit(f"hb read --json {card_id} 輸出非 JSON（無法判定容量）：{e}")
            if not isinstance(content, str):  # ProseMirror object → serialize first
                content = json.dumps(content, ensure_ascii=False)
            # + bytes queued offline for this card (landed-only reads miss them)
            return len(content) + pending_outbox_len(card_id)
        if self.kind == "heptabase":
            return len(self._hepta_read(card_id).get("content") or "")
        return len(self._obe.read_card(card_id).md or "")  # obsidian: no hard cap

    def _append_cmd(self, card_id, md, no_queue):
        """Low-level append → CompletedProcess (or None for obsidian). Normal
        enrichment appends SHOULD queue offline (the bridge's durable outbox);
        only the spill's tail→child link passes no_queue=True (it must land
        synchronously so the chain never has a dangling, unlinked child)."""
        if self.kind == "hb":
            args = ["hb", "append"] + (["--no-queue"] if no_queue else [])
            return hb_write(args + [card_id], md)
        if self.kind == "heptabase":  # local CLI is synchronous; no queue concept
            return sh(["heptabase", "note", "append", card_id, "--content", md])
        self._obe.append_card(card_id, md)
        return None

    def append(self, card_id, md, no_queue=False):
        """Returns True if the write LANDED, False if hb QUEUED it to the offline
        outbox (exit 0 + 'QUEUED' hint) — callers must not report a queued write
        as already on the card."""
        r = self._append_cmd(card_id, md, no_queue)
        if r is None:
            return True
        if r.returncode != 0:
            sys.exit(f"{self.kind} append {card_id} 失敗：{r.stderr[:200]}")
        return "QUEUED" not in (r.stderr or "") + (r.stdout or "")

    def _parse_new_id(self, out):
        try:
            data = json.loads(out)
            cid = data.get("id") or data.get("card")
        except Exception:
            m = re.search(_UUID, out)
            cid = m.group(0) if m else None
        if not cid:
            sys.exit(f"create 輸出無法解析出卡片 id：{out[:200]}")
        return cid

    def create(self, title, body, tag=None):
        """New card (body already opens with '# {title}'). -> (id, tagged).
        `tag` overrides the tag applied at birth (default self.tag — the
        projects tag; log-as-card passes log_tag_name's child tag instead).
        obsidian ignores it (folder model)."""
        use_tag = tag or self.tag
        if self.kind == "hb":
            # --no-queue: a continuation child needs its id NOW. Queuing it (Mac
            # offline) would 0-exit with no id, and a later drain would build an
            # ORPHAN child with no inbound tail link. Fail fast instead — the
            # caller retries when online and re-walks the (still childless) chain.
            r = hb_write(["hb", "create", "--no-queue"], body, timeout=90)
            if r.returncode != 0:
                sys.exit(f"hb create --no-queue 失敗（Mac/tunnel 可能離線；續卡需即時 id，"
                         f"不排隊）：{r.stderr[:200]}")
            cid = self._parse_new_id(r.stdout.strip())
            # bridge 484db04+ has `hb tag-add` (idempotent; offline it QUEUES
            # and the drain replays it — still counts as tagged). An older
            # client has no such verb → non-zero → flag for a Mac follow-up.
            # Swallow raises too (timeout, spawn failure): the child exists but
            # its tail link doesn't yet — metadata must never orphan it.
            try:
                t = sh(["hb", "tag-add", cid, use_tag])
                tagged = (t.returncode == 0)
            except Exception:                                # noqa: BLE001
                tagged = False
            return cid, tagged
        if self.kind == "heptabase":
            r = sh(["heptabase", "note", "create", "--content", body])
            if r.returncode != 0:
                sys.exit(f"heptabase note create 失敗：{r.stderr[:200]}")
            cid = self._parse_new_id(r.stdout.strip())
            try:                          # same never-orphan rule as hb above
                t = sh(["heptabase", "tag", "add", "--card-id", cid,
                        "--tag-name", use_tag])
                tagged = (t.returncode == 0)
            except Exception:                                # noqa: BLE001
                tagged = False
            return cid, tagged
        cid = self._obe.create_card("projects", title, body)
        return cid, True

    def set_project_relation(self, card_id, entry_id, tag=None):
        """Best-effort: point card_id's relation property (config
        relation_property, default = the projects tag's own name) back at the
        chain's entry card. `tag` names WHOSE schema to look in (default
        self.tag; log cards pass their own log tag — wire a relation property
        onto that tag in-app and log cards pick it up with no code change).
        Skips quietly when the tag schema has no such property or the card
        isn't tagged (yet — e.g. the tag-add was queued offline). Metadata
        polish like the back-ref seal: never fails the caller. obsidian is
        out of scope (different property model)."""
        try:
            if self.kind == "hb":
                r = sh(["hb", "props", card_id])
            elif self.kind == "heptabase":
                r = sh(["heptabase", "card", "properties", card_id])
            else:
                return False
            if r.returncode != 0:
                return False
            pid = find_relation_pid(json.loads(r.stdout), tag or self.tag,
                                    relation_property_name(self.cfg))
            if not pid:
                return False
            val = json.dumps([entry_id])   # set-property wants an ID array,
            if self.kind == "hb":          # not the {id,type} objects reads give
                r = sh(["hb", "set-prop", card_id, "--pid", pid, "--json", val])
            else:
                r = sh(["heptabase", "card", "set-property", card_id,
                        "--property-id", pid, "--json-value", val])
            return r.returncode == 0
        except Exception:                                    # noqa: BLE001
            return False


# ---- chain walk + append -----------------------------------------------------
def walk_to_tail(t, entry_id):
    """entry → … → tail. Returns (tail_id, chain_ids). Guards against cycles."""
    chain = [entry_id]
    seen = {entry_id}
    cur = entry_id
    for _ in range(CHAIN_MAX):
        nxt = parse_continuation(t.read(cur))
        if not nxt:
            return cur, chain
        if nxt in seen:
            sys.exit(f"續卡鏈出現迴圈（{nxt} 已在鏈中）——請人工檢查卡片 {entry_id}")
        chain.append(nxt)
        seen.add(nxt)
        cur = nxt
    sys.exit(f"續卡鏈超過 {CHAIN_MAX} 張——疑似異常，停止並請人工檢查 {entry_id}")


def append_or_spill(t, entry_id, new_md, dry_run=False):
    cap, threshold = cap_threshold(t.cfg)
    tail, chain = walk_to_tail(t, entry_id)
    # Reaching here means the bridge is UP — but the Mac-side drainer may not
    # have replayed earlier QUEUED writes yet. A landed append now would place
    # NEWER content before OLDER (queued) content when the outbox drains later,
    # inverting the dated-section order merge relies on. Require a drain first.
    if t.kind == "hb":
        # Check the WHOLE chain, not just the tail: an older write queued to the
        # entry (e.g. `hb log-exp --to`) draining later would land after newer
        # content — or after a continuation link — on ANY card in the chain.
        pending = {c: p for c in chain if (p := pending_outbox_len(c)) > 0}
        if pending:
            msg = (f"續卡鏈上仍有未同步的 outbox queued writes（{pending}）"
                   f"——等 drain 清空（hb drain-status）再 append，否則本次內容"
                   f"先落卡、queued 舊內容後 drain，段落順序會顛倒。")
            if dry_run:
                return {"entry": entry_id, "tail": tail, "appended_to": None,
                        "overflowed": None, "child": None, "chain_len": len(chain),
                        "dry_run": True, "note": "would block — " + msg}
            sys.exit(msg)
    tail_size = t.size(tail)     # serialized payload, not rendered markdown
    add_est = est_stored_len(new_md)   # compare in the SAME (stored) units
    if not would_overflow(tail_size, add_est, threshold):
        # Near the cap, force a synchronous (no-queue) append: `hb read` only sees
        # LANDED bytes, not the offline outbox, so multiple queued sub-threshold
        # appends could otherwise accumulate and silently push the card over the
        # cap on drain. In the near-cap band we'd rather fail while offline
        # (caller goes online) than break the overflow-safe guarantee.
        near_cap = would_overflow(tail_size, add_est, threshold - NEAR_CAP_BAND)
        landed = True
        if not dry_run:
            landed = t.append(tail, new_md, no_queue=near_cap)
        return {"entry": entry_id, "tail": tail,
                "appended_to": None if dry_run else tail,
                "overflowed": False, "child": None, "chain_len": len(chain),
                "dry_run": dry_run, "near_cap_sync": near_cap,
                "queued": (not landed) if not dry_run else None,
                "note": (f"would append to tail {tail}（--dry-run，未寫入）" if dry_run
                         else "⚠️ Mac/tunnel 離線：內容已排入 hb outbox（尚未落卡），"
                              "之後自動同步（hb drain-status 查看）" if not landed
                         else "近上限：已強制同步 append（no-queue）" if near_cap
                         else None)}
    # tail would overflow. Spilling MOVES this append out of the entry into a
    # child card — safe only once project-card-merge follows the 續卡 chain (see
    # CARD-OVERFLOW.md). That prerequisite shipped in 0.16.0, so spill is ON by
    # default since 0.24.1 — critically, a config-less box (the cluster runs
    # through the hb bridge with no ~/.config/research-cards/config.json) must
    # still be able to open a continuation card instead of dead-ending a full
    # tail. Set overflow_spill=false explicitly to restore the old fail-fast.
    spill_enabled = bool(_projects_cfg(t.cfg).get("overflow_spill", True))
    if not spill_enabled:
        msg = (f"卡 {tail} 接近容量上限（+本次 append 會超過 {threshold}）、overflow_spill "
               f"被 config 顯式關閉——請先在 Mac 用 project-card-merge 整併母卡，"
               f"或移除／改回 config 的 heptabase.collections.projects.overflow_spill=true。")
        if dry_run:
            return {"entry": entry_id, "tail": tail, "appended_to": None,
                    "overflowed": True, "child": None, "chain_len": len(chain),
                    "dry_run": True, "spill_enabled": False, "note": "would block — " + msg}
        sys.exit(msg)
    # (pending-outbox gate above already guarantees no queued writes for this
    # tail here — the continuation link can safely be the final block.)
    # spill: new child off the tail, then link the tail → child
    entry_title = t.title(entry_id)
    n = len(chain)  # 續 1, 續 2, … (entry is index 0)
    child_body = child_header(entry_title, entry_id, n) + new_md
    # A single append bigger than the threshold can't fit in ANY card — the
    # freshly created child would be over-cap on arrival. Fail fast instead.
    if would_overflow(0, est_stored_len(child_body), threshold):
        msg = (f"單次 append 內容（{len(new_md)} chars，儲存估計 "
               f"{est_stored_len(child_body)}）本身就超過 spill_threshold "
               f"{threshold}——連新續卡也裝不下。請拆成多次較小的 append 或精簡內容。")
        if dry_run:
            return {"entry": entry_id, "tail": tail, "appended_to": None,
                    "overflowed": True, "child": None, "chain_len": len(chain),
                    "dry_run": True, "spill_enabled": True,
                    "note": "would block — " + msg}
        sys.exit(msg)
    # The old tail must still fit the continuation link itself (vs the real CAP,
    # not the threshold) — otherwise we'd create a child that can never be linked
    # (instant orphan). Check BEFORE creating the child.
    link_est = est_stored_len(continuation_block("0" * 36))
    if tail_size + link_est > cap:
        msg = (f"舊 tail {tail} 連續卡 link（估 {link_est}）都放不下"
               f"（{tail_size}/{cap}）——請先回 Mac 用 project-card-merge 整併。")
        if dry_run:
            return {"entry": entry_id, "tail": tail, "appended_to": None,
                    "overflowed": True, "child": None, "chain_len": len(chain),
                    "dry_run": True, "spill_enabled": True,
                    "note": "would block — " + msg}
        sys.exit(msg)
    if dry_run:
        return {"entry": entry_id, "tail": tail, "appended_to": None,
                "overflowed": True, "child": "<dry-run>", "chain_len": len(chain),
                "dry_run": True, "spill_enabled": True,
                "note": f"would create 續卡 {n} off {tail}（--dry-run，未寫入；"
                        f"cap={cap}, thr={threshold}）"}
    child_id, tagged = t.create(child_title(entry_title, n), child_body)
    # The tail→child link MUST land synchronously (no_queue): if it were queued
    # and the bridge dropped, the child would be created but unreachable from the
    # entry walk — a silent orphan. On failure, surface child_id + a recovery cmd.
    linkr = t._append_cmd(tail, continuation_block(child_id), no_queue=True)
    if linkr is not None and linkr.returncode != 0:
        # Recovery must go through -f: the block starts with "---", which hb's
        # argparse would eat as an option if passed as positional text.
        rec = os.path.join(tempfile.gettempdir(),
                           f"research-cards-linkfix-{child_id[:8]}.md")
        with open(rec, "w") as f:
            f.write(continuation_block(child_id))
        fix = (f"hb append --no-queue {tail} -f {rec}" if t.kind == "hb" else
               f"heptabase note append {tail} --content \"$(cat {rec})\"")
        sys.exit(f"續卡 {child_id} 已建立，但把續卡 link 寫回舊 tail {tail} 失敗"
                 f"（Mac/tunnel 可能剛斷）：{(linkr.stderr or '')[:150]}。"
                 f"→ link 內容已存 {rec}，恢復後手動補：{fix}"
                 f"（不補則子卡 {child_id} 成孤兒）。")
    # The markdown append above lands the sentinel as PLAIN TEXT (the CLI does
    # not convert [[card:id]] to a mention node) — PM-level parsers (merge
    # scan, repair, orphan tooling) would not see the edge. Seal it into a
    # real card node where we can (Mac); on the bridge, flag for a Mac-side
    # `repair_chain.py --seal` pass.
    sealed = t.seal_continuation(tail, child_id, entry_id)
    # entry-pointer relation: lets tag-level scans tell continuations from
    # entries. Needs the tag to be ON the card already, so skip when untagged.
    related = bool(tagged) and t.set_project_relation(child_id, entry_id)
    notes = []
    if not tagged:
        notes.append(
            f"子卡 {child_id} 未上 tag（hb client 過舊或 tag-add 失敗）——"
            f"更新 cluster 端 hb client 後補 `hb tag-add {child_id} {t.tag}`，"
            f"或回 Mac 跑 `heptabase tag add --card-id {child_id} "
            f"--tag-name {t.tag}`（之後再補 relation 指回 {entry_id}）")
    if not sealed:
        notes.append(
            f"tail {tail} 的續卡 link 是文字型（此傳輸層無法轉真 card 節點）——"
            f"回 Mac 跑 `repair_chain.py --card {entry_id} --seal` 收斂，"
            f"merge／orphan 掃描前必須先 seal")
    return {"entry": entry_id, "tail": child_id, "appended_to": child_id,
            "overflowed": True, "child": child_id, "chain_len": len(chain) + 1,
            "dry_run": False, "tagged": tagged, "sealed": sealed,
            "related": related,
            "note": "；".join(notes) if notes else None}


# ---- self-test (pure logic; no network / no CLI) -----------------------------
def log_card_and_link(t, entry_id, log_title, body, summary,
                      dry_run=False):
    """log-as-card mode: every log event is its OWN self-contained card;
    the chain tail only gains one human-readable timeline line
    (📎 date [[card]] summary). The chain stays a readable project
    timeline; the full context lives on the log card."""
    full_body = (body if body.lstrip().startswith("#")
                 else f"# {log_title}\n\n{body}")
    log_tag = log_tag_name(t.cfg)   # resolved once — every return reports it
    # obsidian: file-backed vault, NO hard cap and no chains — the link line
    # goes straight onto the entry file (matching main()'s plain-append
    # contract); wikilink targets the FILENAME (create_card de-dupes
    # same-titled files to "Title (2)")
    if t.kind == "obsidian":
        import datetime
        if dry_run:
            return {"entry": entry_id, "tail": entry_id,
                    "log_card": "<dry-run>", "chain_len": 1, "dry_run": True,
                    "mode": "log-card", "log_tag": log_tag,
                    "note": f"would create log card「{log_title}」+ 時間線行"}
        log_id, tagged = t.create(log_title, full_body, tag=log_tag)
        base = log_id.rsplit("/", 1)[-1]
        link_md = (f"\n{LOG_MARK} {datetime.date.today().isoformat()}"
                   f"　[[{base}]]　{summary}\n")
        try:
            t.append(entry_id, link_md)
        except Exception as e:                               # noqa: BLE001
            rec = os.path.join(tempfile.gettempdir(),
                               f"research-cards-loglink-{base[:24]}.md")
            with open(rec, "w") as f:
                f.write(link_md)
            sys.exit(f"log 卡 {log_id} 已建立，但時間線行 append 失敗："
                     f"{str(e)[:200]}。→ 行內容已存 {rec}，恢復後手動補："
                     f"python3 append_card.py --card {entry_id} "
                     f"--content-file {rec}（不補則 log 卡成孤兒）")
        return {"entry": entry_id, "tail": entry_id, "appended_to": entry_id,
                "overflowed": False, "chain_len": 1, "mode": "log-card",
                "log_card": log_id, "log_title": log_title,
                "log_tagged": tagged, "log_tag": log_tag,
                "link_sealed": True}

    # walk FIRST: if the bridge is down or the chain is unwalkable we must
    # find out BEFORE creating the log card (a create followed by a failed
    # link append would orphan it)
    tail, chain = walk_to_tail(t, entry_id)
    if dry_run:
        return {"entry": entry_id, "tail": tail, "log_card": "<dry-run>",
                "chain_len": len(chain), "dry_run": True, "mode": "log-card",
                "log_tag": log_tag,
                "note": f"would create log card「{log_title}」+ 時間線行 on {tail}"}
    log_id, tagged = t.create(log_title, full_body, tag=log_tag)
    link_md = log_link_line(log_id, summary)

    def _orphan_exit(reason):
        rec = os.path.join(tempfile.gettempdir(),
                           f"research-cards-loglink-{log_id[:8]}.md")
        with open(rec, "w") as f:
            f.write(link_md)
        sys.exit(f"log 卡 {log_id} 已建立，但時間線行落鏈被擋：{reason}。"
                 f"→ 行內容已存 {rec}，處理完原因後手動補："
                 f"python3 append_card.py --card {entry_id} "
                 f"--content-file {rec}（不補則 log 卡 {log_id} 成孤兒）")

    try:
        rep = append_or_spill(t, entry_id, link_md, dry_run=False)
    except SystemExit as e:
        # append_or_spill exits for pending outbox / spill-disabled / link
        # failures — all AFTER the log card exists. Re-raise with the
        # orphan-recovery instructions attached.
        _orphan_exit(e.code if isinstance(e.code, str) else repr(e.code))
    except Exception as e:                                   # noqa: BLE001
        _orphan_exit(str(e)[:300])
    # entry-pointer relation on the log card too — looked up in the LOG tag's
    # schema (it has none out of the box → quiet False; add a relation
    # property named like relation_property to that tag in-app and log cards
    # start carrying their "belongs to <entry>" edge automatically).
    rep.update({"mode": "log-card", "log_card": log_id,
                "log_title": log_title, "log_tagged": tagged,
                "log_tag": log_tag,
                "log_related": bool(tagged) and
                               t.set_project_relation(log_id, entry_id,
                                                      tag=log_tag)})
    target = rep.get("appended_to") or rep.get("tail")
    if t.kind == "heptabase" and target:
        rep["link_sealed"] = t._seal_card(target, seal_loglink_paragraphs)
    elif t.kind == "hb":
        rep["link_sealed"] = False
        extra = (f"時間線行是文字型（bridge 無 seal loglink）——回 Mac 跑 "
                 f"repair_chain.py --card {entry_id} --seal 收斂")
        rep["note"] = f"{rep['note']}；{extra}" if rep.get("note") else extra
    if not tagged:
        extra = (f"log 卡 {log_id} 未上 tag（hb client 過舊或 tag-add 失敗）——"
                 f"更新 cluster 端 hb client 後補 `hb tag-add {log_id} '{log_tag}'`，"
                 f"或回 Mac heptabase tag add --card-id {log_id} "
                 f"--tag-name '{log_tag}'")
        rep["note"] = f"{rep['note']}；{extra}" if rep.get("note") else extra
    if t.kind == "hb":
        try:
            event = enqueue_project_log_event(rep)
            rep["automation_event"] = event["event_id"]
            rep["automation_queued"] = True
        except Exception as e:                                   # noqa: BLE001
            # The Heptabase mutation already succeeded.  Never turn a healthy
            # log card into an apparent failure solely because the optional
            # Mac-side refresh queue could not be written.
            rep["automation_queued"] = False
            extra = ("Mac 自動 repair/sync/canvas 事件排隊失敗"
                     f"（{str(e)[:160]}）——本次 log 已落卡，回 Mac 手動補跑")
            rep["note"] = f"{rep['note']}；{extra}" if rep.get("note") else extra
    return rep


def _self_test():
    # mark-heavy pathologies must clear the spill threshold (stored ~82-88k)
    assert est_stored_len("**x**" * 2000) > 100000
    assert est_stored_len(("*x* " * 1125).rstrip()) > 87967   # real stored size
    # ...while a normal bold experiment log must NOT false-trip an 80k threshold
    assert est_stored_len(("**step 1234** loss=0.123 **val** wer=5.6\n" * 155).rstrip()) < 60000
    cid = "12345678-1234-1234-1234-1234567890ab"
    # log-as-card: timeline line format + sealer
    line = log_link_line(cid, "一句摘要", "2026-07-21").strip()
    assert line.startswith(LOG_MARK) and "[[card:" + cid + "]]" in line
    para = {"type": "paragraph", "attrs": {}, "content": [
        {"type": "text", "text": line}]}
    assert seal_loglink_paragraphs([para]) == 1
    kinds = [c["type"] for c in para["content"]]
    assert "card" in kinds and kinds[0] == "text", kinds
    assert seal_loglink_paragraphs([para]) == 0          # idempotent
    prose = {"type": "paragraph", "attrs": {}, "content": [
        {"type": "text", "text": f"內文提到 [[card:{cid}]] 但不是時間線行"}]}
    assert seal_loglink_paragraphs([prose]) == 0         # non-📎 untouched
    assert parse_continuation("no link here") is None
    assert parse_continuation(f"body\n▶ **{LINK_MARK}**：[[card:{cid}]]\n") == cid
    # wrapper-agnostic: pmmd.Converter round-trips the link to %%HEPTA-CARD:<id>%%
    assert parse_continuation(f"▶ **{LINK_MARK}**：%%HEPTA-CARD:{cid}%%") == cid
    # only the sentinel-tagged link counts (plain card links / back-refs ignored)
    assert parse_continuation(f"see [[card:{cid}]] elsewhere") is None
    assert parse_continuation(f"母卡：[[card:{cid}]]（back-ref, no sentinel）") is None
    # last sentinel wins
    two = "aaaaaaaa-1111-2222-3333-444444444444"
    body = (f"▶ **{LINK_MARK}**：[[card:{cid}]]\n"
            f"▶ **{LINK_MARK}**：[[card:{two}]]\n")
    assert parse_continuation(body) == two
    assert would_overflow(79900, 500, 80000) is True    # 79900+500+160 > 80000
    assert would_overflow(1000, 500, 80000) is False
    assert would_overflow(79000, 500, 80000) is False   # 79660 < 80000 (margin)
    # stored-size estimate: strictly conservative (> raw len), grows with blocks
    assert est_stored_len("- a\n- b") > len("- a\n- b")
    assert est_stored_len("x\n" * 100) > est_stored_len("x" * 200)  # blocks cost more
    # outbox accounting: only records for THIS card count; missing file = 0
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps({"method": "POST", "path": f"/note/{cid}/append",
                            "body": {"content": "hello world"}}) + "\n")
        f.write(json.dumps({"method": "POST", "path": f"/note/{two}/append",
                            "body": {"content": "x" * 5000}}) + "\n")
        f.write("not json\n")
        ob = f.name
    try:
        mine = pending_outbox_len(cid, outbox_path=ob)
        assert mine == est_stored_len("hello world"), mine
        assert pending_outbox_len("no-such-card", outbox_path=ob) == 0
    finally:
        os.unlink(ob)
    assert pending_outbox_len(cid, outbox_path="/nonexistent/outbox.jsonl") == 0
    assert child_title("Cosyvoice Streaming Flow", 1) == "Cosyvoice Streaming Flow · 續 1"
    assert f"[[card:{cid}]]" in continuation_block(cid)
    # continuation_block is itself re-parseable (round-trip)
    assert parse_continuation("x" + continuation_block(cid)) == cid
    # config helpers tolerate junk / missing shapes
    assert tag_name({}) == "project"
    assert tag_name({"heptabase": {"collections": {"projects": {"tag_name": "proj"}}}}) == "proj"
    assert cap_threshold({}) == (DEFAULT_CAP, DEFAULT_THRESHOLD)
    # relation property name: defaults to the tag's own name; config overrides;
    # "<placeholder>" values are ignored like tag_name's
    assert relation_property_name({}) == "project"
    assert relation_property_name(
        {"heptabase": {"collections": {"projects": {"tag_name": "proj"}}}}) == "proj"
    assert relation_property_name(
        {"heptabase": {"collections": {"projects":
                                       {"relation_property": "parent"}}}}) == "parent"
    assert relation_property_name(
        {"heptabase": {"collections": {"projects":
                                       {"relation_property": "<name>"}}}}) == "project"
    # entry-pointer pid lookup from `card properties` output
    props = {"tags": [{"tagName": "project", "properties": [
        {"id": "PID-1", "name": "Status", "type": "select"},
        {"id": "PID-2", "name": "project", "type": "relation"}]}]}
    assert find_relation_pid(props, "project", "project") == "PID-2"
    assert find_relation_pid(props, "project", "parent") is None  # name mismatch
    assert find_relation_pid(props, "other", "project") is None   # tag absent
    assert find_relation_pid({}, "project", "project") is None    # no tags at all
    # type must be relation — a text property with the right name never matches
    text_only = {"tags": [{"tagName": "project", "properties": [
        {"id": "PID-3", "name": "project", "type": "text"}]}]}
    assert find_relation_pid(text_only, "project", "project") is None
    # log tag: defaults to the projects tag's `progress` child; config overrides
    assert log_tag_name({}) == "project/progress"
    assert log_tag_name(
        {"heptabase": {"collections": {"projects": {"tag_name": "proj"}}}}) == "proj/progress"
    assert log_tag_name(
        {"heptabase": {"collections": {"projects":
                                       {"log_tag_name": "logs"}}}}) == "logs"
    assert log_tag_name(
        {"heptabase": {"collections": {"projects":
                                       {"log_tag_name": "<tag>"}}}}) == "project/progress"
    # relation lookup honours the log tag's OWN schema section
    log_props = {"tags": [{"tagName": "project/progress", "properties": [
        {"id": "PID-9", "name": "project", "type": "relation"}]}]}
    assert find_relation_pid(log_props, "project/progress", "project") == "PID-9"
    assert find_relation_pid(log_props, "project", "project") is None
    print("append_card self-test: OK")


def main():
    ap = argparse.ArgumentParser(description="Append to a project card; spill to a "
                                             "continuation sub-card on overflow.")
    ap.add_argument("--card", help="ENTRY card id (chain head; never a child)")
    ap.add_argument("--log-title",
                    help="log-as-card 模式：建立此標題的 self-contained log 卡，"
                         "鏈尾只 append 一行時間線連結（content＝log 卡內文）")
    ap.add_argument("--log-summary",
                    help="時間線行的一句人話摘要（--log-title 模式必填）")
    ap.add_argument("--content", help="markdown, or '-' for stdin")
    ap.add_argument("--content-file", help="read markdown from a file")
    ap.add_argument("--dry-run", action="store_true",
                    help="report the decision without writing")
    ap.add_argument("--queue-offline", action="store_true",
                    help="bridge 離線時仍把內容 queue 進 hb outbox（跳過 chain walk "
                         "與容量檢查、一律排到 ENTRY 卡）。有續卡鏈或 near-cap 時"
                         "可能落錯卡/超限——僅在確定母卡單卡且離上限遠時使用")
    ap.add_argument("--self-test", action="store_true", help="run pure-logic tests")
    args = ap.parse_args()

    if args.self_test:
        return _self_test()
    if not args.card:
        ap.error("--card is required")
    if args.content_file:
        with open(args.content_file) as f:
            new_md = f.read()
    elif args.content == "-":
        new_md = sys.stdin.read()
    elif args.content is not None:
        new_md = args.content
    else:
        ap.error("give --content / --content-file / --content -")
    new_md = new_md.strip("\n")
    if not new_md.strip():
        ap.error("empty content")

    cfg = load_cfg()
    t = Transport(detect_transport(cfg), cfg)
    if args.log_title:
        if not args.log_summary:
            ap.error("--log-title 模式需要 --log-summary（時間線行的一句摘要）")
        out = log_card_and_link(t, args.card, args.log_title, new_md,
                                args.log_summary, dry_run=args.dry_run)
        out["transport"] = t.kind
        return print(json.dumps(out, ensure_ascii=False))
    if t.kind == "obsidian":   # file-backed: no hard cap → always plain append
        if not args.dry_run:
            t.append(args.card, new_md)
        return print(json.dumps({"entry": args.card, "tail": args.card,
                                 "appended_to": None if args.dry_run else args.card,
                                 "overflowed": False, "child": None, "chain_len": 1,
                                 "transport": "obsidian", "dry_run": args.dry_run,
                                 "note": "would append（--dry-run，未寫入）"
                                         if args.dry_run else None},
                                ensure_ascii=False))
    try:
        out = append_or_spill(t, args.card, new_md, dry_run=args.dry_run)
    except BridgeDown as e:
        # Bridge offline → chain walk & capacity check impossible. Fail CLOSED by
        # default（別台機器可能已開 spill 建鏈、entry 也可能 near-cap，盲寫會落錯
        # 卡或 drain 時超限）。--queue-offline 是明確的 informed-consent 逃生口：
        # 跳過檢查、queue 到 ENTRY（舊工作流語義）。
        if args.dry_run or not args.queue_offline:
            sys.exit(f"bridge 離線，無法確認續卡鏈 tail 與容量：{e}\n"
                     f"→ 恢復連線後重跑；或確定母卡單卡且離上限遠時，"
                     f"用 --queue-offline 明確跳過檢查排入 outbox。")
        if bool(_projects_cfg(t.cfg).get("overflow_spill", True)):
            # same default as the spill gate above — the two reads of this key
            # MUST agree, or a config-less box would spill online but skip this
            # offline guard
            sys.exit(f"bridge 離線且 overflow_spill 啟用（可能存在續卡鏈）——"
                     f"--queue-offline 也不允許，恢復連線後再 append：{e}")
        landed = t.append(args.card, new_md)   # allow_queue：離線落 outbox
        out = {"entry": args.card, "tail": args.card,
               "appended_to": args.card, "overflowed": False, "child": None,
               "chain_len": None, "dry_run": False, "queued": not landed,
               "capacity_check": "skipped-offline (--queue-offline)",
               "note": "⚠️ bridge 離線：--queue-offline 已明確跳過 chain/容量檢查，"
                       "內容排入 hb outbox（排到 ENTRY 卡）；hb drain-status 查看"}
    out["transport"] = t.kind
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
