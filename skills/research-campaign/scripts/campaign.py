#!/usr/bin/env python3
"""Campaign bookkeeping for the research-campaign skill (thin, stdlib-only).

    campaign.py init   --repo <path> [--rungs E0 E1 ...]   # scaffold runs/auto_research/
    campaign.py status --dir <runs/auto_research>          # queue + ledger summary
    campaign.py ledger-append --dir <...> --json '<row>'   # schema-checked append

The MISSION content itself is authored by the agent+user (see SKILL.md Mode 1);
this tool only owns the mechanical, easy-to-get-wrong parts: scaffolding,
ledger schema, and status math. No third-party dependencies.
"""
import argparse
import json
import os
import sys

# The minimal locked ledger schema — every row must carry these. `metrics` is
# an open dict (campaigns define their own); everything else is free-form.
LEDGER_REQUIRED = ("experiment", "config_hash", "metrics", "significant", "decision")
QUEUE_STATUSES = ("pending", "running", "done", "failed")


def _feature_gate():
    """Soft gate on config features.project — mirrors project-card-log: a
    missing/broken config never blocks (cluster repos may have none)."""
    try:
        here = os.path.dirname(os.path.realpath(__file__))
        sys.path.insert(0, os.path.join(here, "..", "..", "_shared"))
        import hbconfig
        if os.path.exists(hbconfig.CONFIG_PATH) and not hbconfig.feature_enabled("project"):
            sys.exit("project 方向已在 config features.project 停用")
    except SystemExit:
        raise
    except Exception:
        pass


def cmd_init(args):
    root = os.path.join(os.path.abspath(args.repo), "runs", "auto_research")
    mission = os.path.join(root, "MISSION.md")
    if os.path.exists(mission):
        sys.exit(f"已存在 {mission}——不覆蓋既有任務書（改用編輯，或先手動移除）")
    os.makedirs(root, exist_ok=True)
    tpl = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                       "..", "assets", "MISSION.template.md")
    with open(tpl) as f:
        template = f.read()
    with open(mission, "w") as f:
        f.write(template)
    queue = os.path.join(root, "queue.json")
    if not os.path.exists(queue):
        with open(queue, "w") as f:
            json.dump({"experiments": [
                {"id": r, "status": "pending"} for r in (args.rungs or [])
            ]}, f, ensure_ascii=False, indent=2)
    ledger = os.path.join(root, "ledger.jsonl")
    if not os.path.exists(ledger):
        open(ledger, "w").close()
    print(json.dumps({"scaffolded": root,
                      "mission": mission,
                      "rungs": args.rungs or [],
                      "next": "把核可後的 MISSION 內容寫進 MISSION.md（模板含逐段指引）"},
                     ensure_ascii=False))


def _load_dir(d):
    root = os.path.abspath(d)
    if not os.path.isdir(root):
        sys.exit(f"找不到 campaign 目錄：{root}（先跑 init）")
    return root


def cmd_status(args):
    root = _load_dir(args.dir)
    out = {"dir": root}
    qp = os.path.join(root, "queue.json")
    if os.path.exists(qp):
        with open(qp) as f:
            exps = json.load(f).get("experiments", [])
        counts = {s: 0 for s in QUEUE_STATUSES}
        for e in exps:
            counts[e.get("status", "pending")] = counts.get(e.get("status", "pending"), 0) + 1
        out["queue"] = counts
        out["running"] = [e["id"] for e in exps if e.get("status") == "running"]
        out["next_pending"] = next((e["id"] for e in exps if e.get("status") == "pending"), None)
    lp = os.path.join(root, "ledger.jsonl")
    rows = []
    if os.path.exists(lp):
        with open(lp) as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
    out["ledger_rows"] = len(rows)
    out["recent"] = [{"experiment": r.get("experiment"),
                      "significant": r.get("significant"),
                      "decision": (r.get("decision") or "")[:80]}
                     for r in rows[-args.recent:]]
    bp = os.path.join(root, "BLOCKED.md")
    if os.path.exists(bp):
        with open(bp) as f:
            out["BLOCKED"] = f.read()[:300]
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_ledger_append(args):
    root = _load_dir(args.dir)
    try:
        row = json.loads(args.json)
    except json.JSONDecodeError as e:
        sys.exit(f"--json 不是合法 JSON：{e}")
    if not isinstance(row, dict):
        sys.exit("ledger row 必須是 JSON object")
    missing = [k for k in LEDGER_REQUIRED if k not in row]
    if missing:
        sys.exit(f"ledger row 缺必要欄位 {missing}（schema：{list(LEDGER_REQUIRED)}）")
    if not isinstance(row["metrics"], dict):
        sys.exit("metrics 必須是 object（campaign 自訂指標的容器）")
    if not isinstance(row["significant"], bool):
        sys.exit("significant 必須是布林——顯著性 gate 的結論不許含糊")
    if not row.get("playbook_rules_cited"):
        print("[warn] 這行沒有 playbook_rules_cited——超參決策應引用出處",
              file=sys.stderr)
    with open(os.path.join(root, "ledger.jsonl"), "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"appended": row["experiment"]}, ensure_ascii=False))


def main():
    _feature_gate()
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="scaffold runs/auto_research/ in a repo")
    p.add_argument("--repo", default=".")
    p.add_argument("--rungs", nargs="*", default=None)
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("status", help="queue + ledger summary")
    p.add_argument("--dir", default="runs/auto_research")
    p.add_argument("--recent", type=int, default=5)
    p.set_defaults(fn=cmd_status)
    p = sub.add_parser("ledger-append", help="schema-checked ledger append")
    p.add_argument("--dir", default="runs/auto_research")
    p.add_argument("--json", required=True)
    p.set_defaults(fn=cmd_ledger_append)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
