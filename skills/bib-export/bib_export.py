#!/usr/bin/env python3
"""bib-export — official BibTeX for the papers a card links to.

Read an anchor card (overview / project / any card), collect its card
mentions, read each mentioned paper card's `arxiv ID` property, and fetch
BibTeX from official sources only. NEVER fabricates an entry: anything
unresolvable becomes a `% TODO (unresolved)` comment in the output.

Fetch chain per id kind (same id vocabulary as scholar-inbox-clip):

  2606.12345          arxiv       Semantic Scholar citationStyles (has the
                                  published venue when one exists)
                                  -> arxiv.org/bibtex/<id> (official)
  aclanthology:<id>   ACL         official https://aclanthology.org/<id>.bib
  openreview:<id>     OpenReview  API v2 -> v1 `content._bibtex`
  alphaxiv:<slug>     no arxiv    S2 title match, accepted ONLY when the
                                  normalized titles are equal, else TODO

Usage:
  python3 bib_export.py <card-id|vault-relpath> [-o out.bib] [--depth 2]
  python3 bib_export.py --ids 2606.12345,aclanthology:2026.eacl-short.18
`--depth 2` follows mentioned cards that have no arxiv ID (e.g. a topic hub
whose mentions are sub-overview cards) one more hop. `-o -` prints to stdout.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                "..", "_shared"))
import backend as B  # noqa: E402

UA = {"User-Agent": "research-cards/bib-export (research plugin)"}
S2_API = "https://api.semanticscholar.org/graph/v1/paper"


# ------------------------------------------------------------------ http
def _get(url, retries=2):
    """GET -> text, with one retry on 429/5xx (S2 rate limit). None on 404."""
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (429, 500, 502, 503) and attempt < retries:
                time.sleep(3 * (attempt + 1))
                continue
            return None
        except Exception:
            if attempt < retries:
                time.sleep(2)
                continue
            return None
    return None


def _norm_title(t):
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


# ------------------------------------------------------------------ fetchers
def fetch_s2_bib(ref):
    """ref like 'arXiv:2606.12345' or 'ACL:2026.eacl-short.18'."""
    url = f"{S2_API}/{urllib.parse.quote(ref)}?fields=citationStyles"
    txt = _get(url)
    if not txt:
        return None
    try:
        bib = (json.loads(txt).get("citationStyles") or {}).get("bibtex")
    except Exception:
        return None
    return bib if bib and bib.lstrip().startswith("@") else None


def fetch_arxiv_bib(arxiv_id):
    txt = _get(f"https://arxiv.org/bibtex/{arxiv_id}")
    return txt if txt and txt.lstrip().startswith("@") else None


def fetch_acl_bib(acl_id):
    txt = _get(f"https://aclanthology.org/{acl_id}.bib")
    return txt if txt and txt.lstrip().startswith("@") else None


def fetch_openreview_bib(or_id):
    for host in ("https://api2.openreview.net", "https://api.openreview.net"):
        txt = _get(f"{host}/notes?id={urllib.parse.quote(or_id)}")
        if not txt:
            continue
        try:
            notes = json.loads(txt).get("notes") or []
            if not notes:
                continue
            bib = (notes[0].get("content") or {}).get("_bibtex")
            if isinstance(bib, dict):        # API v2 wraps values
                bib = bib.get("value")
            if bib and bib.lstrip().startswith("@"):
                return bib
        except Exception:
            continue
    return None


def fetch_s2_title_match(title):
    """Title search; accept ONLY a normalized-title-equal match (no guessing)."""
    if not title:
        return None
    url = (f"{S2_API}/search/match?query={urllib.parse.quote(title)}"
           "&fields=citationStyles,title")
    txt = _get(url)
    if not txt:
        return None
    try:
        hits = json.loads(txt).get("data") or []
    except Exception:
        return None
    for h in hits[:3]:
        if _norm_title(h.get("title")) == _norm_title(title):
            bib = (h.get("citationStyles") or {}).get("bibtex")
            if bib and bib.lstrip().startswith("@"):
                return bib
    return None


def resolve_bib(paper_id, title=None):
    """(bibtex, source) for one paper id, or (None, reason)."""
    if re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", paper_id or ""):
        bare = paper_id.split("v")[0]
        bib = fetch_s2_bib(f"arXiv:{bare}")
        if bib:
            return bib, "semanticscholar"
        bib = fetch_arxiv_bib(bare)
        return (bib, "arxiv") if bib else (None, "arxiv id not found upstream")
    if (paper_id or "").startswith("aclanthology:"):
        aid = paper_id.split(":", 1)[1]
        bib = fetch_acl_bib(aid)
        if bib:
            return bib, "aclanthology"
        bib = fetch_s2_bib(f"ACL:{aid}")
        return (bib, "semanticscholar") if bib else (None, "ACL id not found")
    if (paper_id or "").startswith("openreview:"):
        bib = fetch_openreview_bib(paper_id.split(":", 1)[1])
        if bib:
            return bib, "openreview"
        bib = fetch_s2_title_match(title)
        return (bib, "semanticscholar/title") if bib else (None, "no _bibtex on OpenReview")
    if (paper_id or "").startswith("alphaxiv:"):
        bib = fetch_s2_title_match(title)
        return (bib, "semanticscholar/title") if bib else \
            (None, "alphaXiv-only paper; no exact title match on S2")
    return None, f"unrecognized id form: {paper_id!r}"


# ------------------------------------------------------------------ card side
def _read_doc(be, card_id):
    """PM doc for either backend. Heptabase CLI returns ProseMirror JSON
    directly (mentions are `card` nodes). Obsidian: the shared converter only
    rebuilds BARE [[wikilinks]] into card mentions (aliased [[Name|label]]
    links deliberately become link marks) — for mention COLLECTION we want
    both, so strip aliases from the raw body before converting."""
    if hasattr(be, "read_doc"):
        body = be.read_content_str(card_id)
        body = re.sub(r"\[\[([^\]|#]+)\|[^\]]*\]\]", r"[[\1]]", body)
        return be._md_to_doc(body, resolve_wikilinks=True)
    note = B._cli("note", "read", card_id)
    return json.loads(note["content"])


def _mentions(doc):
    out, stack = [], list(doc.get("content") or [])
    while stack:
        n = stack.pop(0)
        if isinstance(n, dict):
            if n.get("type") == "card" and (n.get("attrs") or {}).get("cardId"):
                out.append(n["attrs"]["cardId"])
            stack.extend(n.get("content") or [])
    seen, uniq = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def _arxiv_prop(card):
    # Heptabase props are keyed by display name; Obsidian frontmatter by fm_key.
    v = card.props.get("arxiv ID") or card.props.get(B.fm_key("arxiv ID"))
    return str(v).strip() if v else None


def _strip_prefix(title):
    return re.sub(r"^\[[^\]]+\]\s*", "", title or "").strip()


def _is_container(card):
    """Overview/hub cards carry the graph's `Level` property; paper and blog
    cards do not. Only these descend at --depth 2 — a paper/blog card missing
    its arxiv ID must surface as a TODO even when its body has card links."""
    return ("Level" in card.props) or (B.fm_key("Level") in card.props)


def collect_papers(be, anchor_id, depth):
    """[(card_id, title, paper_id_or_None)] from the anchor's mention tree."""
    papers, visited = [], {anchor_id}
    frontier = _mentions(_read_doc(be, anchor_id))
    for level in range(depth):
        nxt = []
        for cid in frontier:
            if cid in visited:
                continue
            visited.add(cid)
            try:
                card = be.read_card(cid)
            except Exception as e:
                papers.append((cid, f"<unreadable: {e}>", None))
                continue
            pid = _arxiv_prop(card)
            if pid:
                papers.append((cid, _strip_prefix(card.title), pid))
            elif level + 1 < depth and _is_container(card):
                try:
                    nxt.extend(_mentions(_read_doc(be, cid)))
                except Exception:
                    papers.append((cid, card.title, None))
            else:  # non-container without arxiv ID: always report, never hide
                papers.append((cid, card.title, None))
        frontier = nxt
    return papers


# ------------------------------------------------------------------ assembly
def _bib_key(entry):
    m = re.match(r"\s*@\w+\s*\{\s*([^,\s]+)\s*,", entry)
    return m.group(1) if m else None


def _c(x):
    """Comment-safe: no control chars, so a title/reason can never break out
    of its `%` line and inject an active BibTeX entry."""
    return re.sub(r"[\x00-\x1f]+", " ", str(x)).strip()


def assemble(results):
    """results: [(title, paper_id, bib_or_None, source_or_reason)] -> bib text."""
    out, used = [], {}
    for title, pid, bib, src in results:
        if not bib:
            out.append(f"% TODO (unresolved): {_c(title)} — id: {_c(pid or 'no arxiv ID')} — {_c(src)}")
            continue
        bib = bib.strip()
        key = _bib_key(bib)
        if key:
            ident = pid or _norm_title(title) or bib  # what makes this paper distinct
            if key in used and used[key] == ident:
                continue  # same paper reached twice: emit once
            if key in used and used[key] != ident:
                n = 2
                while f"{key}-{n}" in used:
                    n += 1
                bib = bib.replace(key, f"{key}-{n}", 1)
                key = f"{key}-{n}"
            used[key] = ident
        out.append(f"% {_c(title)} [{_c(src)}]\n{bib}")
    return "\n\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("card", nargs="?", help="anchor card id (or vault relpath in obsidian mode)")
    ap.add_argument("--ids", help="comma-separated paper ids, skip card reading")
    ap.add_argument("-o", "--out", help="output .bib path ('-' = stdout)")
    ap.add_argument("--depth", type=int, default=1,
                    help="mention hops; 2 follows non-paper cards once (default 1)")
    args = ap.parse_args()
    if not args.card and not args.ids:
        ap.error("need a card id or --ids")

    if args.ids:
        triples = [(None, None, p.strip()) for p in args.ids.split(",") if p.strip()]
        anchor_title = "papers"
    else:
        be = B.get_backend()
        triples = collect_papers(be, args.card, max(1, args.depth))
        anchor_title = be.read_card(args.card).title or args.card

    results, ok = [], 0
    for cid, title, pid in triples:
        if not pid:
            results.append((title or cid, None, None, "card has no arxiv ID property"))
            continue
        bib, src = resolve_bib(pid, title=title)
        if bib:
            ok += 1
        results.append((title or pid, pid, bib, src))
        time.sleep(1.0)  # stay under the anonymous S2 rate limit

    text = assemble(results)
    if args.out == "-":
        sys.stdout.write(text)
    else:
        path = args.out or re.sub(r"[^\w\-]+", "-", anchor_title).strip("-") + ".bib"
        with open(path, "w") as f:
            f.write(text)
        print(f"wrote {path}", file=sys.stderr)
    # status goes to stderr so `-o - > refs.bib` stays valid BibTeX
    unresolved = [r for r in results if not r[2]]
    print(f"resolved {ok}/{len(results)}", file=sys.stderr)
    for title, pid, _, reason in unresolved:
        print(f"  UNRESOLVED: {title} ({pid or 'no id'}) — {reason}", file=sys.stderr)


if __name__ == "__main__":
    main()
