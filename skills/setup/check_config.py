#!/usr/bin/env python3
"""Config health check for research-cards — the setup skill's verifier.

Reports, without ever writing anything:
  - where the active config lives (env override / new path / legacy path)
  - whether it loads (hbconfig.load_config validation, with the exact error)
  - backend-specific reachability: the vault directory for obsidian mode,
    the `heptabase` CLI (and optionally the running app) for heptabase mode
  - profile / features at a glance
  - "available upgrades": keys that config.example.json documents but the
    live config does not set (new settings ship faster than configs update)

Usage:
    python3 check_config.py            # human-readable report
    python3 check_config.py --json     # machine-readable
    python3 check_config.py --probe    # additionally test the Heptabase app
                                       # connection (runs `heptabase tag list`)

Exit code: 0 = config loads (warnings possible), 1 = missing/invalid config.
Stdlib only; imports the plugin's hbconfig for the single source of truth.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

_HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "_shared"))
import hbconfig  # noqa: E402

EXAMPLE = os.path.join(_HERE, "..", "..", "config.example.json")


def _is_set(v):
    """A value counts as set only when non-empty AND not an example
    placeholder like `<tag-uuid>` — same rule as hbconfig.hb_id, so the
    health check never green-lights a copied-but-unfilled config."""
    s = str(v or "").strip()
    return bool(s) and not (s.startswith("<") and s.endswith(">"))


def upgrade_hints(cfg, example):
    """Keys the example documents (top level and one level deep) that the
    live config leaves unset — the setup skill offers these as opt-ins.
    $comment keys are documentation, not settings."""
    hints = []
    for k, v in example.items():
        if k.startswith("$"):
            continue
        if k not in cfg:
            hints.append(k)
            continue
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            for kk in v:
                if kk.startswith("$"):
                    continue
                if kk not in cfg[k]:
                    hints.append(f"{k}.{kk}")
    return hints


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--probe", action="store_true",
                    help="also test the live Heptabase app connection")
    args = ap.parse_args()

    out = {"config_path": hbconfig.CONFIG_PATH,
           "exists": os.path.exists(hbconfig.CONFIG_PATH),
           "loads": False, "backend": None, "checks": [], "warnings": [],
           "upgrade_hints": []}

    def check(name, ok, detail=""):
        out["checks"].append({"name": name, "ok": bool(ok), "detail": detail})

    if not out["exists"]:
        out["warnings"].append(
            f"config 不存在（{hbconfig.CONFIG_PATH}）——setup skill 可從 "
            f"config.example.json 帶你建立；最小 config 只需要 obsidian.vault")
    else:
        try:
            cfg = hbconfig.load_config()
            out["loads"] = True
            out["backend"] = cfg["backend"]
            out["backends"] = cfg["backends"]
            out["profile"] = cfg.get("profile") or {}
            out["features"] = cfg.get("features") or {"study": True, "project": True}
            out["output_language"] = hbconfig.output_language()

            if cfg["backend"] in ("obsidian", "both"):
                vault = (cfg.get("obsidian") or {}).get("vault", "")
                ok = os.path.isdir(vault)
                check("vault directory", ok, vault)
                if ok and not os.access(vault, os.W_OK):
                    out["warnings"].append(f"vault 不可寫：{vault}")
            if cfg["backend"] in ("heptabase", "both"):
                cli = shutil.which("heptabase")
                check("heptabase CLI on PATH", bool(cli), cli or "not found")
                hb = cfg.get("heptabase") or {}
                check("heptabase.workspace_id", _is_set(hb.get("workspace_id")))
                cols = {k: _is_set((v or {}).get("tag_id"))
                        for k, v in (hb.get("collections") or {}).items()
                        if isinstance(v, dict)}
                check("collections with tag_id",
                      any(cols.values()), json.dumps(cols, ensure_ascii=False))
                if args.probe and cli:
                    r = subprocess.run(["heptabase", "tag", "list"],
                                       capture_output=True, text=True, timeout=20)
                    check("Heptabase app reachable", r.returncode == 0,
                          (r.stderr or "")[:120])
            if (cfg.get("hackmd") or {}).get("collections"):
                hm_cli = shutil.which("hackmd-cli")
                check("hackmd-cli on PATH", bool(hm_cli), hm_cli or "not found")
                has_tok = bool(os.environ.get("HMD_API_ACCESS_TOKEN")) or \
                    os.path.exists(os.path.expanduser("~/.hackmd/config.json"))
                check("HackMD token (login or env)", has_tok,
                      "" if has_tok else "run `hackmd-cli login` or set "
                                         "HMD_API_ACCESS_TOKEN")
                if args.probe and hm_cli and has_tok:
                    r = subprocess.run(["hackmd-cli", "whoami"],
                                       capture_output=True, text=True,
                                       stdin=subprocess.DEVNULL, timeout=20)
                    check("HackMD API reachable", r.returncode == 0,
                          (r.stderr or r.stdout)[:120])
            try:
                example = json.load(open(EXAMPLE))
                out["upgrade_hints"] = upgrade_hints(cfg, example)
            except Exception:                                # noqa: BLE001
                pass
        except hbconfig.ConfigError as e:
            out["error"] = str(e)
        except Exception as e:                               # noqa: BLE001
            out["error"] = f"unexpected: {e}"

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"config: {out['config_path']}"
              f" ({'存在' if out['exists'] else '不存在'})")
        if out.get("error"):
            print(f"✗ 載入失敗：{out['error']}")
        elif out["loads"]:
            print(f"✓ 載入成功  backends={out.get('backends')}"
                  f"（首位＝正本）  language={out.get('output_language')}")
            for c in out["checks"]:
                print(f"  {'✓' if c['ok'] else '✗'} {c['name']}"
                      + (f"  ({c['detail']})" if c["detail"] else ""))
        for w in out["warnings"]:
            print(f"  ⚠ {w}")
        if out["upgrade_hints"]:
            print(f"  ℹ example 有、此 config 未設（可加購）："
                  f"{', '.join(out['upgrade_hints'][:12])}")
    ok = (out["loads"] and not out.get("error")) or not out["exists"]
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
