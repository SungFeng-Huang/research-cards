#!/usr/bin/env python3
"""Story-graph lifecycle markers, migration, and append-safe revisions.

Ordinary story nodes are immutable.  A node becomes lifecycle-managed only
when it carries BOTH:

    "semantic": "open_thread|open_hole|next_step|pending_capture"
    "lifecycle": {"state": "open|active|resolved|abandoned|superseded",
                  "revision": 0}

Managed nodes may evolve while open/active; everything else remains
append-only.  This module is intentionally independent from rendering so an
agent-authored proposal can be checked before it ever touches the live graph.
"""
import argparse
import copy
import json
import os
import re
import tempfile
from pathlib import Path

SEMANTICS = {"open_thread", "open_hole", "next_step", "pending_capture"}
STATES = {"open", "active", "resolved", "abandoned", "superseded"}
OPEN_STATES = {"open", "active"}
TRANSITIONS = {
    "open": STATES,
    "active": {"active", "resolved", "abandoned", "superseded"},
}
MUTABLE_FIELDS = {
    "kind", "label", "text", "anchor", "date", "sources", "lifecycle",
}
TOP_APPEND_LISTS = {"coverage_ignore", "glossary"}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def atomic_dump(path, graph):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(graph, f, ensure_ascii=False, indent=1)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def infer_semantic(node):
    """One-time compatibility mapping for legacy kind=open nodes."""
    text = f"{node.get('label', '')} {node.get('text', '')}"
    if re.search(r"開放洞|漏洞|hole", text, re.I):
        return "open_hole"
    if re.search(r"下一步|next", text, re.I):
        return "next_step"
    if re.search(r"待捕|待補|capture|todo", text, re.I):
        return "pending_capture"
    return "open_thread"


def migrate(graph):
    """Mark every legacy kind=open node; return (new_graph, changed_ids)."""
    out = copy.deepcopy(graph)
    changed = []
    for node in out.get("nodes") or []:
        if node.get("kind") != "open":
            continue
        has_semantic = "semantic" in node
        has_lifecycle = "lifecycle" in node
        if has_semantic != has_lifecycle:
            raise ValueError(
                f"{node.get('id')}: semantic/lifecycle 必須成對出現")
        if not has_semantic:
            node["semantic"] = infer_semantic(node)
            node["lifecycle"] = {"state": "open", "revision": 0}
            changed.append(node.get("id"))
        _validate_marker(node)
    return out, changed


def _validate_marker(node):
    has_semantic = "semantic" in node
    has_lifecycle = "lifecycle" in node
    if has_semantic != has_lifecycle:
        raise ValueError(
            f"{node.get('id')}: semantic/lifecycle 必須成對出現")
    if not has_semantic:
        return
    if node["semantic"] not in SEMANTICS:
        raise ValueError(
            f"{node.get('id')}: unknown semantic {node['semantic']!r}")
    lc = node["lifecycle"]
    if not isinstance(lc, dict) or set(lc) != {"state", "revision"}:
        raise ValueError(
            f"{node.get('id')}: lifecycle 只能含 state/revision")
    if lc["state"] not in STATES:
        raise ValueError(
            f"{node.get('id')}: unknown lifecycle state {lc['state']!r}")
    if not isinstance(lc["revision"], int) or lc["revision"] < 0:
        raise ValueError(
            f"{node.get('id')}: lifecycle revision 必須是非負整數")
    if lc["state"] in OPEN_STATES and node.get("kind") != "open":
        raise ValueError(
            f"{node.get('id')}: open/active lifecycle 必須維持 kind=open")


def _is_prefix(old, new):
    return isinstance(old, list) and isinstance(new, list) and new[:len(old)] == old


def validate_revision(before, after):
    """Raise ValueError unless *after* is an append-safe proposal."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValueError("story graph 必須是 JSON object")
    bnodes, anodes = before.get("nodes") or [], after.get("nodes") or []
    bedges, aedges = before.get("edges") or [], after.get("edges") or []
    if len(anodes) < len(bnodes):
        raise ValueError("不可刪除既有 story node")
    if len(aedges) < len(bedges) or aedges[:len(bedges)] != bedges:
        raise ValueError("既有 edges 必須原樣保留；新 edge 只能附加在尾端")
    bids = [n.get("id") for n in bnodes]
    aids = [n.get("id") for n in anodes]
    if aids[:len(bids)] != bids:
        raise ValueError("既有 nodes 的 id/順序必須原樣保留；新 node 只能附加")
    if len(aids) != len(set(aids)) or not all(aids):
        raise ValueError("story node ids 必須唯一且非空")

    for key in set(before) | set(after):
        if key in {"nodes", "edges"}:
            continue
        if key in TOP_APPEND_LISTS:
            if not _is_prefix(before.get(key) or [], after.get(key) or []):
                raise ValueError(f"{key} 只能在尾端附加，不可刪改")
        elif before.get(key) != after.get(key):
            raise ValueError(f"top-level {key!r} 不可改動")

    changed, appended = [], aids[len(bids):]
    for old, new in zip(bnodes, anodes):
        _validate_marker(old)
        _validate_marker(new)
        if old == new:
            continue
        nid = old.get("id")
        if "semantic" not in old:
            raise ValueError(f"{nid}: 未標 lifecycle 的歷史節點不可修改")
        if old["semantic"] != new.get("semantic"):
            raise ValueError(f"{nid}: semantic 角色不可修改")
        forbidden = {
            k for k in set(old) | set(new)
            if k not in MUTABLE_FIELDS and old.get(k) != new.get(k)
        }
        if forbidden:
            raise ValueError(
                f"{nid}: lifecycle 更新不可改 {sorted(forbidden)}")
        old_lc, new_lc = old["lifecycle"], new["lifecycle"]
        if old_lc["state"] not in OPEN_STATES:
            raise ValueError(f"{nid}: 已結案 lifecycle 節點不可再次修改")
        if new_lc["state"] not in TRANSITIONS[old_lc["state"]]:
            raise ValueError(
                f"{nid}: 非法 lifecycle transition "
                f"{old_lc['state']}→{new_lc['state']}")
        if new_lc["revision"] != old_lc["revision"] + 1:
            raise ValueError(f"{nid}: lifecycle revision 必須恰好 +1")
        if not _is_prefix(old.get("sources") or [], new.get("sources") or []):
            raise ValueError(f"{nid}: sources 只能附加，不可刪改")
        changed.append(nid)

    for node in anodes[len(bnodes):]:
        _validate_marker(node)
    idset = set(aids)
    for edge in aedges:
        if edge.get("from") not in idset or edge.get("to") not in idset:
            raise ValueError(
                f"edge {edge.get('from')}→{edge.get('to')} 指到未知 node")
    return {"changed_lifecycle_nodes": changed,
            "appended_nodes": appended,
            "appended_edges": len(aedges) - len(bedges)}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    mig = sub.add_parser("migrate")
    mig.add_argument("graph")
    mig.add_argument("--write", action="store_true")
    val = sub.add_parser("validate")
    val.add_argument("before")
    val.add_argument("after")
    args = ap.parse_args()
    if args.command == "migrate":
        graph, changed = migrate(load(args.graph))
        if args.write and changed:
            atomic_dump(args.graph, graph)
        rep = {"graph": args.graph, "changed": changed,
               "written": bool(args.write and changed)}
    else:
        rep = validate_revision(load(args.before), load(args.after))
    print(json.dumps(rep, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
