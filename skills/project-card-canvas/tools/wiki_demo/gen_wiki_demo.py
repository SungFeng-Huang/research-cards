#!/usr/bin/env python3
"""wiki-demo — render the wiki's example images for ALL four canvas views
with the REAL layout builders (fidelity by construction), one set per
language. Synthetic fictional project only (real canvases carry research
content). UI strings baked into the builders (legend/leaf headers/幕) stay
Chinese — that's what the product renders; demo CONTENT is translated.

Usage:  python3 gen_wiki_demo.py [outdir]     # default: ./out
Needs:  headless Google Chrome (screenshots), no card I/O.
"""
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, os.path.join(_HERE, "..", ".."))
for p in ("_shared", "project-card-merge"):
    sys.path.insert(0, os.path.join(_HERE, "..", "..", "..", p))
import context_mindmap as CM  # noqa: E402
import project_canvas as PCV  # noqa: E402

E = "00000000-0000-4000-8000-00000000000e"
L = [f"00000000-0000-4000-8000-0000000000{i:02d}" for i in range(1, 7)]
NOMAP = lambda cid: None  # noqa: E731
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# ── per-language demo content ───────────────────────────────────────────
T = {
 "en": dict(entry="Demo project",
  tl=[("2026-07-01", "baseline trained — quality OK, latency 3×", True, "cluster"),
      ("2026-07-04", "parameter sweep: latency −40%, quality dips", True, "cluster"),
      ("2026-07-08", "attribution run: culprit is a missing downstream cache", True, "cluster"),
      ("2026-07-12", "methods chapter rewrite: attribution flow into §3", False, "mac"),
      ("2026-07-15", "latency table lands in the draft + review-reply sketch", False, "mac")],
  hubs=[("baseline", "2026-07-01", "Q: how far does baseline quality go?",
         [("🔬", "30-epoch baseline + fixed eval slice."), ("💡", "quality OK (4.1/5) but latency 3× over budget.")]),
        ("sweep", "2026-07-04", "Q: which knob drives latency?",
         [("📊", "chunk size dominates: −40% latency, −0.3 quality."), ("⚖️", "where does quality drop? needs per-segment analysis.")]),
        ("seam analysis", "2026-07-08", "Q: which segments lose quality?",
         [("💡", "collapse sits at segment seams — not model capacity.")])],
  secs=[("status at a glance", "latency −40%, quality restored; seam fix deployed."),
        ("method", "streamed chunked inference + cache continuation."),
        ("experiments (1): sweep", None), ("experiments (2): seam attribution", None),
        ("Findings", "fix the pipeline before surgery on the model."),
        ("next steps", "widen eval corpus; deploy A/B.")],
  leaves={2: [("E0 baseline", "quality 4.1, latency 3×."), ("E1 chunk sweep", "−40% latency, −0.3 quality — cost sits at seams.")],
          3: [("E2 attribution 2×2", "downstream module alone causes it; missing cache confirmed.")]},
  story=[("idea", "💡 low-latency idea", "Act 1｜idea & sweep"),
         ("experiment", "🧪 parameter sweep", None), ("finding", "✅ quality wall found", None),
         ("question", "❓ why do seams collapse?", "Act 2｜attribution & fix"),
         ("experiment", "🧪 attribution 2×2", None), ("finding", "✅ culprit: missing cache", None),
         ("decision", "⚖️ one-line config fix", None), ("open", "⏳ ongoing", None)],
  el=("so", "but", "convicted", "fixed", "re-verify")),
 "zh-TW": dict(entry="Demo 專案",
  tl=[("2026-07-01", "基線訓練完成——品質達標但延遲 3×", True, "cluster"),
      ("2026-07-04", "參數掃描：延遲降 40%，品質開始掉", True, "cluster"),
      ("2026-07-08", "歸因實驗：真兇是下游模組的快取缺失", True, "cluster"),
      ("2026-07-12", "方法章改稿：把歸因流程寫進 §3", False, "mac"),
      ("2026-07-15", "表五延遲對照入稿＋審稿回覆草稿", False, "mac")],
  hubs=[("基線訓練", "2026-07-01", "這次要回答：基線品質能到哪？",
         [("🔬", "30 epochs 基線訓練＋固定評測切片。"), ("💡", "品質達標（4.1／5），但延遲 3× 超出目標。")]),
        ("參數掃描", "2026-07-04", "這次要回答：哪個參數主導延遲？",
         [("📊", "chunk 大小主導：延遲 −40%；品質 −0.3。"), ("⚖️", "品質掉在哪裡？需要逐段分析。")]),
        ("崩點分析", "2026-07-08", "這次要回答：品質掉在哪一段？",
         [("💡", "崩點集中在段落交界——不是模型能力問題。")])],
  secs=[("現狀（一眼掌握）", "延遲 −40% 且品質回滿；交界修復已部署。"),
        ("方法(Method)", "串流分塊推論＋快取接續。"),
        ("實驗統整(一)：參數掃描", None), ("實驗統整(二)：交界歸因", None),
        ("Findings / 設計理路", "先修管線、再談架構。"),
        ("下一步 / 計畫", "擴大評測語料；部署 A/B。")],
  leaves={2: [("E0 基線", "品質 4.1、延遲 3×。"), ("E1 chunk 掃描", "延遲 −40%、品質 −0.3——代價集中在交界。")],
          3: [("E2 歸因 2×2", "下游模組單獨致病；快取缺失實錘。")]},
  story=[("idea", "💡 低延遲想法", "第1幕｜想法與掃描"),
         ("experiment", "🧪 參數掃描", None), ("finding", "✅ 發現品質牆", None),
         ("question", "❓ 交界為什麼崩？", "第2幕｜歸因與修復"),
         ("experiment", "🧪 歸因 2×2", None), ("finding", "✅ 真兇：快取缺失", None),
         ("decision", "⚖️ 一行 config 修復", None), ("open", "⏳ 進行中", None)],
  el=("所以", "但是", "定罪", "對修", "回頭驗證")),
 "ja": dict(entry="Demo プロジェクト",
  tl=[("2026-07-01", "ベースライン完了——品質OK・遅延3×", True, "cluster"),
      ("2026-07-04", "パラメータ掃引：遅延−40%・品質低下", True, "cluster"),
      ("2026-07-08", "帰因実験：真犯人は下流のキャッシュ欠如", True, "cluster"),
      ("2026-07-12", "方法章の改稿：帰因フローを §3 に", False, "mac"),
      ("2026-07-15", "表5の遅延対照を原稿へ＋査読返信の下書き", False, "mac")],
  hubs=[("ベースライン", "2026-07-01", "今回の問い：ベースライン品質はどこまで？",
         [("🔬", "30 epochs ベースライン＋固定評価スライス。"), ("💡", "品質OK（4.1/5）だが遅延 3× 超過。")]),
        ("掃引", "2026-07-04", "今回の問い：どのパラメータが遅延を支配？",
         [("📊", "chunk サイズが支配：遅延 −40%・品質 −0.3。"), ("⚖️", "品質低下はどこ？セグメント別分析が必要。")]),
        ("崩れ分析", "2026-07-08", "今回の問い：どのセグメントで品質が落ちる？",
         [("💡", "崩れは継ぎ目に集中——モデル能力の問題ではない。")])],
  secs=[("現状", "遅延 −40%・品質回復；継ぎ目修正はデプロイ済み。"),
        ("方法", "ストリーム分塊推論＋キャッシュ接続。"),
        ("実験まとめ(一)：掃引", None), ("実験まとめ(二)：継ぎ目帰因", None),
        ("Findings", "アーキテクチャの前にパイプラインを直す。"),
        ("次の一手", "評価コーパス拡大；デプロイ A/B。")],
  leaves={2: [("E0 ベースライン", "品質 4.1・遅延 3×。"), ("E1 chunk 掃引", "遅延 −40%・品質 −0.3——コストは継ぎ目に集中。")],
          3: [("E2 帰因 2×2", "下流モジュール単独で発症；キャッシュ欠如を確証。")]},
  story=[("idea", "💡 低遅延のアイデア", "第1幕｜アイデアと掃引"),
         ("experiment", "🧪 パラメータ掃引", None), ("finding", "✅ 品質の壁を発見", None),
         ("question", "❓ なぜ継ぎ目で崩れる？", "第2幕｜帰因と修復"),
         ("experiment", "🧪 帰因 2×2", None), ("finding", "✅ 真犯人：キャッシュ欠如", None),
         ("decision", "⚖️ 一行 config 修正", None), ("open", "⏳ 進行中", None)],
  el=("だから", "しかし", "断定", "対処", "再検証")),
 "ko": dict(entry="Demo 프로젝트",
  tl=[("2026-07-01", "베이스라인 완료 — 품질 OK, 지연 3×", True, "cluster"),
      ("2026-07-04", "파라미터 스윕: 지연 −40%, 품질 하락", True, "cluster"),
      ("2026-07-08", "귀인 실험: 범인은 다운스트림 캐시 부재", True, "cluster"),
      ("2026-07-12", "방법 장 개고: 귀인 흐름을 §3에", False, "mac"),
      ("2026-07-15", "표5 지연 대조 원고 반영+심사 답변 초안", False, "mac")],
  hubs=[("베이스라인", "2026-07-01", "이번 질문: 베이스라인 품질은 어디까지?",
         [("🔬", "30 epochs 베이스라인+고정 평가 슬라이스."), ("💡", "품질 OK(4.1/5), 지연 3× 초과.")]),
        ("스윕", "2026-07-04", "이번 질문: 어떤 파라미터가 지연을 지배?",
         [("📊", "chunk 크기가 지배: 지연 −40%, 품질 −0.3."), ("⚖️", "품질은 어디서 떨어지나? 구간별 분석 필요.")]),
        ("붕괴 분석", "2026-07-08", "이번 질문: 어느 구간에서 품질이 떨어지나?",
         [("💡", "붕괴는 이음매에 집중 — 모델 능력 문제가 아님.")])],
  secs=[("현황", "지연 −40%, 품질 회복; 이음매 수정 배포됨."),
        ("방법", "스트림 분할 추론+캐시 연속."),
        ("실험 정리(1): 스윕", None), ("실험 정리(2): 이음매 귀인", None),
        ("Findings", "아키텍처보다 파이프라인을 먼저 고친다."),
        ("다음 단계", "평가 코퍼스 확대; 배포 A/B.")],
  leaves={2: [("E0 베이스라인", "품질 4.1, 지연 3×."), ("E1 chunk 스윕", "지연 −40%, 품질 −0.3 — 비용은 이음매에 집중.")],
          3: [("E2 귀인 2×2", "다운스트림 모듈 단독 발병; 캐시 부재 확증.")]},
  story=[("idea", "💡 저지연 아이디어", "1막｜아이디어와 스윕"),
         ("experiment", "🧪 파라미터 스윕", None), ("finding", "✅ 품질 벽 발견", None),
         ("question", "❓ 이음매는 왜 무너지나?", "2막｜귀인과 수정"),
         ("experiment", "🧪 귀인 2×2", None), ("finding", "✅ 범인: 캐시 부재", None),
         ("decision", "⚖️ 한 줄 config 수정", None), ("open", "⏳ 진행 중", None)],
  el=("그래서", "하지만", "판정", "수정", "재검증")),
}


LEG = {  # legend 行翻譯（logs/chain/story 各模式；zh-TW 原樣）
 "en": {"entry（HEAD→最新 📗）": "entry (HEAD → newest 📗)", "Mac 端": "Mac side", "cluster 端": "cluster side", "判不出來源": "origin unknown", "📎 待蒸餾（HEAD 上方）／📗 已蒸餾": "📎 backlog (above HEAD) / 📗 distilled", "圖例": "Legend", "軸卡（root）": "entry card (root)",
        "log 卡（hub）": "log card (hub)",
        "定位／現狀／進展／Findings": "positioning / status / milestones / findings",
        "實驗統整": "experiment sections", "方法／評估": "method / evaluation",
        "開放項（🔍／下一步／發想／待補）": "open items (🔍 / next / ideas / TODO)",
        "其他／H3 細節": "other / H3 details",
        "💡 想法／❓ 提問": "💡 idea / ❓ question", "🧪 實驗": "🧪 experiment",
        "📊 結果": "📊 result", "✅ 發現／⚖️ 定案": "✅ finding / ⚖️ decision",
        "🔀 轉向／⏳ 進行中": "🔀 pivot / ⏳ ongoing",
        "（向下弧線＝跨幕接續或跨層長邊）": "(downward arcs = cross-act / long links)",
        "❓ 這次要回答": "❓ question", "💡 這代表什麼": "💡 what it means",
        "⚖️ 待裁決／下一步": "⚖️ decisions / next",
        "🔬 做了什麼／📊 結果": "🔬 what was done / 📊 results"},
 "ja": {"entry（HEAD→最新 📗）": "entry（HEAD→最新の 📗）", "Mac 端": "Mac 側", "cluster 端": "cluster 側", "判不出來源": "由来不明", "📎 待蒸餾（HEAD 上方）／📗 已蒸餾": "📎 未蒸留（HEADの上）／📗 蒸留済み", "圖例": "凡例", "軸卡（root）": "エントリーカード（root）",
        "log 卡（hub）": "log カード（hub）",
        "定位／現狀／進展／Findings": "定位／現状／マイルストーン／Findings",
        "實驗統整": "実験まとめ", "方法／評估": "方法／評価",
        "開放項（🔍／下一步／發想／待補）": "オープン項目（🔍／次の一手／アイデア／TODO）",
        "其他／H3 細節": "その他／H3 詳細",
        "💡 想法／❓ 提問": "💡 アイデア／❓ 問い", "🧪 實驗": "🧪 実験",
        "📊 結果": "📊 結果", "✅ 發現／⚖️ 定案": "✅ 発見／⚖️ 裁決",
        "🔀 轉向／⏳ 進行中": "🔀 転換／⏳ 進行中",
        "（向下弧線＝跨幕接續或跨層長邊）": "（下向きの弧＝幕またぎ／長距離リンク）",
        "❓ 這次要回答": "❓ 今回の問い", "💡 這代表什麼": "💡 意味すること",
        "⚖️ 待裁決／下一步": "⚖️ 裁決待ち／次の一手",
        "🔬 做了什麼／📊 結果": "🔬 実施したこと／📊 結果"},
 "ko": {"entry（HEAD→最新 📗）": "entry(HEAD→최신 📗)", "Mac 端": "Mac 측", "cluster 端": "cluster 측", "判不出來源": "출처 불명", "📎 待蒸餾（HEAD 上方）／📗 已蒸餾": "📎 대기(HEAD 위)/📗 증류 완료", "圖例": "범례", "軸卡（root）": "엔트리 카드(root)",
        "log 卡（hub）": "log 카드(hub)",
        "定位／現狀／進展／Findings": "포지셔닝/현황/마일스톤/Findings",
        "實驗統整": "실험 정리", "方法／評估": "방법/평가",
        "開放項（🔍／下一步／發想／待補）": "오픈 항목(🔍/다음/아이디어/TODO)",
        "其他／H3 細節": "기타/H3 세부",
        "💡 想法／❓ 提問": "💡 아이디어/❓ 질문", "🧪 實驗": "🧪 실험",
        "📊 結果": "📊 결과", "✅ 發現／⚖️ 定案": "✅ 발견/⚖️ 결정",
        "🔀 轉向／⏳ 進行中": "🔀 전환/⏳ 진행 중",
        "（向下弧線＝跨幕接續或跨層長邊）": "(아래 방향 호=막 넘김/장거리 링크)",
        "❓ 這次要回答": "❓ 이번 질문", "💡 這代表什麼": "💡 의미",
        "⚖️ 待裁決／下一步": "⚖️ 결정 대기/다음",
        "🔬 做了什麼／📊 結果": "🔬 수행한 것/📊 결과"},
 "zh-TW": {},
}

UI = {   # builder 內建中文 UI 字串 → 各語言（demo 影像不摻他語）
 "en": {"❓ 這次要回答": "❓ Question this round", "🔬 做了什麼": "🔬 What was done",
        "📊 結果": "📊 Results", "💡 這代表什麼": "💡 What it means",
        "⚖️ 待裁決／下一步": "⚖️ Decisions / next"},
 "ja": {"❓ 這次要回答": "❓ 今回の問い", "🔬 做了什麼": "🔬 実施したこと",
        "📊 結果": "📊 結果", "💡 這代表什麼": "💡 意味すること",
        "⚖️ 待裁決／下一步": "⚖️ 裁決待ち／次の一手"},
 "ko": {"❓ 這次要回答": "❓ 이번 질문", "🔬 做了什麼": "🔬 수행한 것",
        "📊 結果": "📊 결과", "💡 這代表什麼": "💡 의미",
        "⚖️ 待裁決／下一步": "⚖️ 결정 대기/다음"},
 "zh-TW": {},
}
import re as _re


def i18n(canvas, lang):
    """Demo post-process: drop legend/glossary/audit nodes and the
    degradation/card-id noise lines; translate leaf headers so a
    non-Chinese page's image contains no Chinese."""
    drop = {PCV._nid(E, "mm-glossary"), PCV._nid(E, "mm-audit")}
    canvas["nodes"] = [n for n in canvas["nodes"] if n["id"] not in drop]
    for n in canvas["nodes"]:
        t = n.get("text")
        if not t:
            continue
        t = _re.sub(r"\n?（未鏡像；Heptabase card [0-9a-f]{8}）", "", t)
        t = _re.sub(r"\n?（Heptabase card [0-9a-f]{8}）", "", t)
        t = t.replace("\n（entry 卡未鏡像）", "").replace("（entry 卡未鏡像）", "")
        for zh, tr in UI.get(lang, {}).items():
            t = t.replace(zh, tr)
        if n["id"] in (PCV._nid(E, "mm-legend"), PCV._nid(E, "legend")):
            for zh, tr in LEG.get(lang, {}).items():
                t = t.replace(zh, tr)
            n["width"] = 420                  # 翻譯後行較長：放寬防截行
            n["height"] = 64 + 30 * t.count("\n")
        n["text"] = t
    return canvas


def para(t):
    return {"type": "paragraph", "content": [{"type": "text", "text": t}]}


def txt(n):
    return "".join(c.get("text", "") for c in n.get("content", [])
                   if isinstance(c, dict))


def shoot(canvas, out_png, outdir, scale):
    j = os.path.join(outdir, out_png.replace(".png", ".json"))
    h = os.path.join(outdir, out_png.replace(".png", ".html"))
    json.dump(canvas, open(j, "w"), ensure_ascii=False)
    wh = subprocess.run([sys.executable, os.path.join(_HERE, "canvas2html.py"),
                         j, h, str(scale)],
                        capture_output=True, text=True).stdout.split()[-1]
    w, ht = wh.split("x")
    subprocess.run([CHROME, "--headless", "--disable-gpu",
                    f"--screenshot={os.path.join(outdir, out_png)}",
                    f"--window-size={w},{ht}", "--hide-scrollbars",
                    os.path.abspath(h)], capture_output=True)
    print(" ", out_png, wh)


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    for lang, v in T.items():
        # timeline (origin colors — the 0.51 default)
        entries = [{"log": L[i], "date": d, "summary": s, "done": dn,
                    "seq": i, "origin": o}
                   for i, (d, s, dn, o) in enumerate(v["tl"])]
        c = PCV.build_canvas(E, v["entry"], [E], entries, NOMAP,
                             color_by="origin")
        shoot(i18n(c, lang), f"canvas-timeline-{lang}.png", outdir, 1.0)
        # logs
        logs, decomp = [], {}
        for i, (title, date, q, secs) in enumerate(v["hubs"]):
            logs.append({"log": L[i], "date": date, "seq": i})
            icon2 = {"🔬": ("🔬 做了什麼", None), "📊": ("📊 結果", None),
                     "💡": ("💡 這代表什麼", "4"), "⚖️": ("⚖️ 待裁決／下一步", "1")}
            decomp[L[i]] = {"title": title, "question": q,
                            "sections": [(*icon2[ic], t) for ic, t in secs],
                            "cites": [L[i - 1]] if i else []}
        c, _ = CM.build_mindmap(E, v["entry"], logs, decomp, NOMAP)
        shoot(i18n(c, lang), f"canvas-logs-{lang}.png", outdir, 0.8)
        # chain
        secs = []
        for i, (h2, lead) in enumerate(v["secs"]):
            subs = [(t, [para(b)]) for t, b in v["leaves"].get(i, [])]
            secs.append((h2, [para(lead)] if lead else [], subs))
        c = CM.build_chainmap(E, v["entry"], [(E, "", secs)], NOMAP, txt_of=txt)
        root = next(n for n in c["nodes"] if n["id"] == PCV._nid(E, "mm-root"))
        root.update({"type": "text", "text": f'# {v["entry"]}'})
        shoot(i18n(c, lang), f"canvas-chain-{lang}.png", outdir, 0.85)
        # story
        gnodes = []
        for i, (kind, label, stage) in enumerate(v["story"]):
            n = {"id": f"n{i+1}", "kind": kind, "label": label.split(" ", 1)[-1],
                 "text": ""}
            if stage:
                n["stage"] = stage
            gnodes.append(n)
        el = v["el"]
        gedges = [{"from": "n1", "to": "n2", "label": el[0]},
                  {"from": "n2", "to": "n3"},
                  {"from": "n3", "to": "n4", "label": el[1]},
                  {"from": "n4", "to": "n5"},
                  {"from": "n5", "to": "n6", "label": el[2]},
                  {"from": "n6", "to": "n7", "label": el[3]},
                  {"from": "n7", "to": "n8"},
                  {"from": "n3", "to": "n7", "label": el[4]}]
        c, _ = CM.build_storymap(E, v["entry"], gnodes, gedges, NOMAP)
        root = next(n for n in c["nodes"] if n["id"] == PCV._nid(E, "mm-root"))
        root.update({"type": "text", "text": f'# {v["entry"]}'})
        shoot(i18n(c, lang), f"canvas-story-{lang}.png", outdir, 0.6)
        # CJK 防漏：en/ko 影像不得含漢字（ja 合法使用漢字）
        if lang in ("en", "ko"):
            import glob as _g
            import re as _re2
            for jf in _g.glob(os.path.join(outdir, f"canvas-*-{lang}.json")):
                for n in json.load(open(jf))["nodes"]:
                    hits = _re2.findall(r"[一-鿿]+", n.get("text") or "")
                    if hits:
                        print(f"  ⚠️ CJK LEAK {jf}: {hits}")
                        raise SystemExit(1)   # 防漏＝硬失敗，杜絕帶漏出貨
    print("done →", outdir)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(_HERE, "out"))
