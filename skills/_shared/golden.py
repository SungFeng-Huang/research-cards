#!/usr/bin/env python3
"""Golden-snapshot harness for overview-topic migrations (dirs with a sync_overview.py).

Captures, for one skill dir, (a) the exact stdout+exit code of
`python3 sync_overview.py status` and (b) the full doc JSON of every card in
the skill's OVERVIEW_CARDS union, into a labelled snapshot. Diffing two labels
proves a migration is behavior-neutral (status byte-identical, no card doc
changed).

  python3 golden.py capture <skill_dir> <label>
  python3 golden.py diff    <skill_dir> <label1> <label2>

Snapshots live under ~/.cache/overview-golden/<skill_name>/<label>/.
"""
import os, re, sys, json, subprocess, difflib, importlib.util


def _strip_ids(text):
    """Semantic mode (--semantic): null out node ids — Heptabase reassigns them
    on every save, so byte diffs after a re-save are noise; content is what matters."""
    return re.sub(r'"id":\s*"[0-9a-f-]{36}"', '"id": null', text)

BASE = os.path.expanduser("~/.cache/overview-golden")


def _load_module(skill_dir):
    path = os.path.join(skill_dir, "sync_overview.py")
    spec = importlib.util.spec_from_file_location("sync_overview_golden", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _card_ids(skill_dir):
    mod = _load_module(skill_dir)
    for attr in ("OVERVIEW_CARDS",):
        if hasattr(mod, attr):
            return list(getattr(mod, attr))
    if hasattr(mod, "TOPIC"):   # migrated skills expose an OverviewTopic
        return list(mod.TOPIC.overview_cards)
    sys.exit(f"ERROR: {skill_dir}/sync_overview.py has neither OVERVIEW_CARDS nor TOPIC")


def _snapdir(skill_dir, label):
    return os.path.join(BASE, os.path.basename(os.path.abspath(skill_dir)), label)


def capture(skill_dir, label):
    out = _snapdir(skill_dir, label)
    os.makedirs(out, exist_ok=True)
    r = subprocess.run([sys.executable, "sync_overview.py", "status"],
                       cwd=skill_dir, capture_output=True, text=True)
    with open(os.path.join(out, "status.txt"), "w", encoding="utf-8") as f:
        f.write(f"exit={r.returncode}\n{r.stdout}")
    if r.returncode != 0:
        print(f"WARNING: status exited {r.returncode}; stderr: {r.stderr.strip()[:160]}")
    ids = _card_ids(skill_dir)
    for cid in ids:
        rr = subprocess.run(["heptabase", "note", "read", cid], capture_output=True, text=True)
        try:
            doc = json.loads(json.loads(rr.stdout)["content"])
        except Exception:
            sys.exit(f"ERROR: could not read card {cid}")
        with open(os.path.join(out, f"{cid}.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"captured {label}: status + {len(ids)} card docs → {out}")


def diff(skill_dir, l1, l2):
    d1, d2 = _snapdir(skill_dir, l1), _snapdir(skill_dir, l2)
    findings = 0
    files = sorted(set(os.listdir(d1)) | set(os.listdir(d2)))
    for name in files:
        p1, p2 = os.path.join(d1, name), os.path.join(d2, name)
        if not os.path.exists(p1) or not os.path.exists(p2):
            findings += 1
            print(f"!! {name}: only in {'first' if os.path.exists(p1) else 'second'} snapshot")
            continue
        a = open(p1, encoding="utf-8").read()
        b = open(p2, encoding="utf-8").read()
        if "--semantic" in sys.argv:
            a, b = _strip_ids(a), _strip_ids(b)
        if a != b:
            findings += 1
            print(f"!! {name} differs:")
            for line in list(difflib.unified_diff(
                    a.splitlines(), b.splitlines(), l1, l2, lineterm=""))[:24]:
                print("   " + line)
    print(f"{'IDENTICAL' if not findings else f'{findings} file(s) differ'} "
          f"({l1} vs {l2}, {len(files)} files)")
    return 0 if not findings else 1


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "capture":
        capture(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 5 and sys.argv[1] == "diff":
        sys.exit(diff(sys.argv[2], sys.argv[3], sys.argv[4]))
    else:
        print(__doc__)
        sys.exit(64)
