# research-cards — 宏毅先生に学ぶ研究術 📚

[English](README.md) | [繁體中文](README.zh-TW.md) | **日本語** | [한국어](README.ko.md)

論文の情報フローを、**あなたに教えてくれる研究ナレッジベース**へと変えます。1 枚 1 枚のカードが宏毅先生の授業のように——
まず「なぜ読むべきか」と必要な前提知識を伝え、次に WHY 駆動のナラティブで手法を腹落ちするまで解説し、
最後にトピック比較カードとナレッジマップの文脈の中に位置づけて、それぞれの論文が分野全体のどこにあるのかを常に把握できるようにします。

> 本プロジェクトは[李宏毅（Hung-yi Lee）先生](https://speech.ee.ntu.edu.tw/~hylee/)の教育スタイルへの
> オマージュであり、先生ご本人とは無関係です。ティーチングの魂は
> [hung-yi-lee skill](https://github.com/voidful/hung-yi-lee-skill)
> と同じ系譜にあります——併せてインストールするのがおすすめです（[連携](#連携オプション)を参照）。

**純粋な .md ファイルのフォルダ**だけで、箱から出してそのまま動きます——
ノートアプリは不要です。**Obsidian** と **Heptabase** はオプションのアップグレード
（それぞれ、より快適な閲覧体験と完全な双方向同期を提供）。AI agent は
**Claude Code** と **Codex** の 2 つをサポートし、どの組み合わせでも使えます。できることは：

- **クリッピング**：digest メール（または arxiv リンク 1 本）→ ティーチングスタイルのカード——クイックサマリーの
  toggle、意味ベースのカラーリング、図版、プロパティフィールドまで一度に揃います。
- **整理**：Tasks 分類法に従って各トピックの**比較オーバービューカード**へ自動ルーティング。ナラティブなガイド序文、
  トピック hub、横断リンク、可視化されたナレッジマップ付き。
- **同期**：カードライブラリ全体を Heptabase ↔ Obsidian 間で双方向同期——ブロック単位の書き戻し、
  非可逆（lossy）になるならコンフリクトとして報告して勝手に書かない、追跡できるコンフリクト台帳。
- **研究ログ**：どのプロジェクト repo のセッションからでも進捗を対応するプロジェクトカードへ記録し、
  あとで paper 級の完全な記述に統合——容量上限に達すると継続カードチェーンを自動で開き、詳細が
  100K のために要約で削られることは決してありません。
- **参考文献**：カードがリンクしている全論文の公式 BibTeX をワンアクションでエクスポート。

---

**目次** ·
[Skills 一覧](#skills-一覧) ·
[インストール](#インストール) ·
[設定](#設定) ·
[クイックスタート（純 .md）](#クイックスタート-a--純粋な-md-フォルダノートアプリ不要) ·
[クイックスタート（Heptabase）](#クイックスタート-b--heptabase--both) ·
[日常の使い方](#日常の使い方) ·
[Heptabase ↔ Obsidian 同期](#heptabase--obsidian-同期) ·
[研究実験 Campaign](#研究実験-campaign) ·
[無人スケジュール実行](#無人スケジュール実行クリッピングパイプライン) ·
[連携](#連携オプション) ·
[トラブルシューティング](#トラブルシューティング) ·
[License](#license)

> 📖 **ユースケース別ガイドは [Wiki](https://github.com/SungFeng-Huang/research-cards/wiki) にあります**：
> [日常研究 pipeline](https://github.com/SungFeng-Huang/research-cards/wiki/Daily-Research-Pipeline-ja)（どの場面でどの skill を使い、どうつなぐか）·
> [エコシステム連携](https://github.com/SungFeng-Huang/research-cards/wiki/Ecosystem-Integration-ja)（ARS／experiment-agent との分担と混用 recipes）·
> [Campaign 完全マニュアル](https://github.com/SungFeng-Huang/research-cards/wiki/Research-Campaign-ja)。
> README が扱うのはインストール・設定とコマンド対照表。「どの場面で何を使うか」は wiki をご覧ください。

## Skills 一覧

**📥 論文クリッピング**——流れ込む情報を、ティーチングカードへ

| Skill | 何をするか |
|---|---|
| `scholar-inbox-clip` | digest メール／URL → ティーチングカード（プロパティ、図版、journal 記録、オーバービューへのルーティング） |
| `card-rewrite` | 既存カードを完全なティーチング形式へ書き直す（一言のエッセンス / なぜ読むべきか / 前提知識 / WHY 駆動のナラティブ / 二言語併記の用語） |

**🗺️ トピックオーバービューとナレッジグラフ**——1 枚のカードが分野の地図へ育つ

| Skill | 何をするか |
|---|---|
| `overview` | 各トピックの比較オーバービューカードを維持：論文ごとの小節、次元比較テーブル、カバレッジチェック、arxiv ID 順ソート |
| `overview-daodu` | オーバービューカードの先頭にナラティブなガイド序文を挿入／リフレッシュ（冪等） |
| `overview-graph` | グラフ構造：トピック hub、横断 ↔/→ リンク、ナレッジマップ（Heptabase whiteboard / Obsidian JSON Canvas）、整合性監査。**project 側にも寄与**：Operation 5 はナレッジグラフを使ってプロジェクトカードの research-gap 分析を行います |

**🧪 研究プロジェクト**——あなた自身の研究も、カードに

| Skill | 何をするか |
|---|---|
| `project-card-log` | プロジェクト repo のセッション（ローカルでもリモートでも）からこのプロジェクトのカードを解決し、日付つき・コードに裏づけられた進捗を追記——追記のみで書き換えません。カードが容量上限に達したら**継続カードチェーンを自動で開始**（無損失。100K に収めるための要約圧縮は決してしません） |
| `project-card-merge` | もう片方の相棒：溜まった進捗ブロックを 1 枚の paper 級の完全なカードへ統合（フル編集側）。**chain-aware**：継続カードチェーン全体をまとめて読み、統合結果が上限を超えたら H2 セクション単位で新しいチェーンへオーバーフローさせ、孤児になった継続カードも自動回収 |
| `research-campaign` | 自律的な実験キャンペーンのミッションブリーフ形式＋記帳ルール：MISSION.md は repo へ、queue/ledger による中断・再開、有意性 gate の計測規律、進捗はプロジェクトカードへ自動還流。オプションのショーケース層：レポートページ＋**トレーニング log 曲線ダッシュボード**を GitHub/GitLab Pages へ自動デプロイ |

**✍️ 論文執筆**——paper を書くときにナレッジベースを収穫する

| Skill | 何をするか |
|---|---|
| `bib-export` | 任意のカードをアンカーに（オーバービューカードでもプロジェクトカードでも可）、そのカードがリンクする論文の公式 BibTeX をエクスポート——決して捏造せず、見つからないものは `% TODO` コメントになります |

**🔁 同期インフラ**

| Skill | 何をするか |
|---|---|
| `obsidian-sync` | Heptabase ↔ Obsidian 双方向同期（backend `both` のみ） |

スイッチの対応関係：config の `features.study` はクリッピング＋オーバービュー＋ナレッジグラフを、`features.project`
は研究プロジェクトの 3 点セット（log／merge／campaign）をカバーします。`bib-export` と `obsidian-sync` は方向スイッチの影響を受けません
（前者はあなたが渡すアンカーカードに、後者は backend に従います）。

## インストール

### 必要要件

| 使いたいもの | 必要なもの |
|---|---|
| 基本 | Python 3.10+、`pip install pyyaml`、agent CLI 1 つ（**Claude Code** または **Codex**） |
| `backend: heptabase` / `both` | macOS＋**Heptabase デスクトップ版**＋`heptabase` CLI **≥ 0.4.0**（ローカル API `127.0.0.1:21210`） |
| `backend: obsidian` / `both`（デフォルト） | **.md ファイルのフォルダが 1 つあれば十分**——どんなディレクトリでも OK。**Obsidian vault** として開くのはオプションの仕上げです（iCloud の vault には**フルディスクアクセス権限**が必要） |
| メールクリッピング（`scholar-inbox-clip`） | macOS **Mail.app**＋専用メールボックスフォルダ（Mail のルールで digest を振り分ける）＋`osascript` の自動化権限 |
| カードの図版 | `pip install pymupdf`（PDF ページ）＋`brew install librsvg`（SVG） |
| Claude Code のボーナス | **alphaXiv MCP**（クリッピング／リライトの内容根拠）と **heptabase MCP**（同期時に highlight 埋め込みを解決）。オプション——Codex は組み込みの HTTP 取得を使い、highlight は手動で補うようリストアップされます |
| オプションの連携 skills | **hung-yi-lee**（ティーチングスタイルのランタイム連携）と **alchemist-playbook**（campaign のハイパーパラメータ引用規律）——インストール方法と未導入時の挙動は[連携](#連携オプション)を参照 |

### Claude Code

GitHub から直接インストールします：

```
/plugin marketplace add SungFeng-Huang/research-cards
/plugin install research-cards@research-cards
```

または clone して repo を skills ディレクトリへ symlink します（例：
`~/.claude/skills/research-cards`）。`.claude-plugin/plugin.json` によって
plugin として読み込まれます。どちらの方法でも skills は `research-cards:<skill>` として現れます。

### Codex

Codex は「marketplace ディレクトリ」から plugin をインストールします。自分の clone 用にひとつ作ります（初回のみ）：

```bash
mkdir -p ~/plugins/.agents/plugins
git clone https://github.com/SungFeng-Huang/research-cards ~/plugins/research-cards
cat > ~/plugins/.agents/plugins/marketplace.json <<'EOF'
{
  "name": "my-plugins",
  "plugins": [
    { "name": "research-cards",
      "source": { "source": "local", "path": "./research-cards" },
      "policy": { "installation": "AVAILABLE" } }
  ]
}
EOF
codex plugin marketplace add ~/plugins
codex plugin add research-cards@my-plugins
```

Codex が実行するのは**静的な cache コピー**です：config に `plugin_root` を設定してください（状態の読み書き
は生きている repo にアンカーされます）。plugin を更新したら `codex plugin remove` ＋ `add` でのリフレッシュを忘れずに。

## 設定

`config.example.json` を `~/.config/research-cards/config.json` にコピーして
記入します——各フィールドの説明は example の中にインラインで書かれています。全体マップ：

| フィールド | 何を制御するか |
|---|---|
| `backend` | `heptabase` \| `obsidian` \| `both`。`both` は Heptabase を正とし、`obsidian-sync` が vault へミラーリング。`obsidian` は純粋な `.md`＋frontmatter で、Heptabase 不要 |
| `agent` | `claude` \| `codex`——無人実行スクリプトがテキスト生成にどちらの CLI を使うか（`claude --print` / `codex exec`） |
| `plugin_root` | 生きている plugin のパス——Codex 駆動時は必須（cache のアンカー） |
| `profile` | `reader` / `field`——カードが「誰に」教えるか（例：音声研究者）。各カードへ流れ込む「なぜ読むべきか」の素になります |
| `features` | `{"study": bool, "project": bool}`——方向まるごとのスイッチ |
| `email` | クリッピングパイプライン用の Mail.app `account`＋`mailbox` |
| `heptabase` | workspace id、各 collection の tag id／filter（`collections`）、プロパティ UUID（`props`）、コーパスの `scan_tags`、`graph` の ids（ルート目次カード、ナレッジマップ whiteboard、Level プロパティ、topology `hubs`）。id は `heptabase tag list` / `heptabase tag properties <tagId>` で調べます |
| `obsidian` | vault のパス、各 collection のフォルダ（`folders`）、`graph`（`.canvas` マップ、ルート目次ノート、`hubs` は `Folder/Name` id） |
| `integrations` | オプションの外部 skill——[連携](#連携オプション)を参照 |
| `gold_cards` | オプションのスタイル見本カード（card-rewrite / overview-daodu 用。未設定なら組み込み仕様を使用） |

知っておく価値のある 2 つの原則：

- **すべての id は必ずあなたの config 由来です。**heptabase モードのコマンドは、id が欠けていると
  どの key が未記入かを名指しして終了します——決して推測しません。
- **Topics はユーザーデータであり、plugin データではありません。**オーバービューのトピック設定は
  `~/.config/research-cards/topics/<key>/` に住んでいます（テンプレート：
  `skills/overview/topics/_example/`）。`aliases.json` と `projects.json`
  もその隣にあります。repo 自体には個人の分類法は一切含まれません。

## クイックスタート A — 純粋な .md フォルダ（ノートアプリ不要）

これが**基本のデフォルト**です：必要なのはディレクトリ 1 つだけ。カードは
YAML frontmatter 付きの純粋な Markdown ファイル——どんなエディタでも読めて、
grep でき、git でバージョン管理できます。ノートアプリなしで、10 分で論文
パイプラインを立ち上げます：

1. **インストール**：plugin（上記参照）＋ `pip install pyyaml`
   （図版が欲しければさらに `pymupdf` と `librsvg`）。
2. **フォルダを作成**（場所は自由。iCloud に置く場合は、ターミナルにフルディスクアクセス権限が必要です）。
3. **設定**——最小構成の `~/.config/research-cards/config.json`
   （`backend` のデフォルトがこの純粋 .md モードなので、書かなくても構いません）：

   ```json
   {
     "agent": "claude",
     "plugin_root": "/path/to/research-cards",
     "profile": { "reader": "あなたの読者像", "field": "あなたの分野" },
     "obsidian": { "vault": "~/Documents/ResearchCards",
                   "folders": { "papers": "Papers", "overviews": "Overviews" } }
   }
   ```

   （設定セクションの名前が `obsidian` なのは歴史的な経緯です——`vault` は
   ただのあなたのフォルダです。）
4. **最初のカード**——agent セッションでこう言います：
   「scholar-inbox-clip で https://arxiv.org/abs/XXXX.XXXXX をカードにして」。
   カードが `Papers/` に現れ、frontmatter プロパティ、クイックサマリー、意味ベースのカラーリングが揃います。
   （メールクリッピングはオプション——[スケジュール実行](#無人スケジュール実行クリッピングパイプライン)を参照。）
5. **関連論文が数本たまったら、構造を育てます**：
   1. `skills/overview/topics/_example/` を
      `~/.config/research-cards/topics/<あなたのトピック>/` へコピーし、`config.py` を記入します。
   2. **hub ノート**を 1 枚作ります：`## 子卡與閱讀順序`（サブカードと読む順序）の小節を持ち、
      `[[wikilinks]]` で比較カードを列挙し、frontmatter の `tasks` にあなたの Tasks
      値を入れること——hub の形式は API であり、どれか 1 つ欠けると topology はそのままエラーになります。
   3. hub を config の `obsidian.graph.hubs` に登録し、次を実行します：

      ```bash
      python3 /path/to/research-cards/skills/_shared/topology.py refresh <あなたのトピック>
      ```

   以後は `overview` / `overview-daodu` / `overview-graph` がこのトピックを維持します。

**ボーナス——同じフォルダをノートアプリで開く。**上記のすべてはそのまま
動き続けます。ノートアプリはただ、もっと読みやすくしてくれるだけです：

- **Obsidian**：vault をこのフォルダへ向けます——`[[wikilinks]]` がクリック可能になり、
  frontmatter に Properties UI が付き、ナレッジマップ（graph skills が維持する
  JSON Canvas ファイル）が本物の canvas として描画されます。
- **Heptabase**：完全なブロック単位の双方向同期——クイックスタート B と wiki の [Note App Backends](https://github.com/SungFeng-Huang/research-cards/wiki/Note-App-Backends-ja) を参照。

## クイックスタート B — Heptabase / both

Heptabase は完全なブロック単位の**双方向同期**をもたらします（`backend: both` は
Heptabase を正とし、あなたのフォルダへミラーリングし、vault 側の編集も書き戻します）。
セットアップは同じ流れに、id（tags、プロパティ UUID）を調べるステップが 1 つ
加わるだけ——完全な手順は wiki にあります：
[Note App Backends](https://github.com/SungFeng-Huang/research-cards/wiki/Note-App-Backends-ja)。

## 日常の使い方

各場面（朝のインプット、論文読み、週次メンテナンス、プロジェクト期、執筆期）ごとのシナリオ別の進め方は
wiki を参照：[Daily Research Pipeline](https://github.com/SungFeng-Huang/research-cards/wiki/Daily-Research-Pipeline-ja)。
本節はコマンド対照表です。日常でやるのは**skill を呼ぶこと**であって、コマンドを叩くことではありません：

- **自然言語（推奨）**——やりたいことをそのまま agent に伝えれば、適切な skill を選び、
  SKILL.md の契約どおりに実行してくれます。以下の各節に例文があります。
- **skill を名指し**——Claude Code ではスラッシュで：`/research-cards:<skill>`（例：
  `/research-cards:obsidian-sync`）。Codex ではメッセージの中で skill 名を挙げるだけで OK です。
- **低レベル CLI**——無人スケジュール実行や debug のときにだけ必要で、各節の
  「低レベルコマンド」の折りたたみに収めてあります（普段は agent がこれらをあなたの代わりに実行しています）。

### 📥 クリッピング

| あなたが言うこと | skill を指名して行うなら |
|---|---|
| 「https://arxiv.org/abs/XXXX.XXXXX をカードにして」 | `/research-cards:scholar-inbox-clip https://arxiv.org/abs/XXXX.XXXXX` |
| 「scholar inbox のメールボックスをスキャンして」——メールを読み、重複排除し、カードを作り、Tasks を付け、オーバービューカードへルーティング | `/research-cards:scholar-inbox-clip` |
| 「〈○○カード〉をティーチング形式に書き直して」——構造はアップグレード、事実はそのまま | `/research-cards:card-rewrite 〈カードタイトル〉` |

<details><summary>低レベルコマンド</summary>

```bash
python3 skills/scholar-inbox-clip/run.py    # ヘッドレスのスケジュール実行モード（スケジュール実行の節を参照）
```
</details>

### 🗺️ オーバービューとナレッジグラフ

| あなたが言うこと | skill を指名して行うなら |
|---|---|
| 「この新しい論文を <topic> のオーバービューカードに追加して」 | `/research-cards:overview <topic> 〈論文〉を追加` |
| 「<topic> のカバレッジは？　どの論文がまだ比較カードに入っていない？」 | `/research-cards:overview <topic> status` |
| 「このオーバービューカードのガイド序文をリフレッシュして」 | `/research-cards:overview-daodu 〈オーバービューカードのタイトル〉` |
| 「tokenizer と spoken の間に横断リンクを 1 本足して」 | `/research-cards:overview-graph 横断リンク追加 tokenizer ↔ spoken` |
| 「graph audit を実行して」——構造変更後に hub／横断リンク／ナレッジマップの整合性をチェック | `/research-cards:overview-graph audit` |
| 「〈○○ whiteboard〉を Obsidian Canvas にミラーリングして」——実際のレイアウト（座標/セクション/接続線＋自動 mention 線）を一方向で上書き。デフォルトでは app のローカルデータベースを読み（リアルタイム、app を開いたままでも OK）、バックアップファイルはフォールバック | `/research-cards:overview-graph mirror` |

構造的な変更（新しい hub、再分割、カードの移動）の後、agent は topology refresh を実行します——それは
オーバービュールーティングのデータソースであり、省略できません。

<details><summary>低レベルコマンド</summary>

```bash
cd skills/overview
python3 sync_overview.py <topic> status   # カバレッジ diff → どの論文が MISSING か
python3 sync_overview.py <topic> sort     # arxiv ID 順にリストを並べ直す
python3 ../_shared/topology.py refresh    # 全トピック。または refresh <topic>
```
</details>

### 🧪 研究プロジェクト

| あなたが言うこと | skill を指名して行うなら |
|---|---|
| 「今日の進捗を project card に記録して」——プロジェクト repo のセッション内で言うだけで OK。agent が対応するカードを解決し（marker → registry）、カードがなければ作るかどうか尋ねます | `/research-cards:project-card-log`（プロジェクト repo 内で、引数なし） |
| 「このプロジェクトに project card を 1 枚作って」——カード作成＋スケルトン＋tag 付け＋対応の固定までワンステップ | `/research-cards:project-card-log カード作成 "My Project"` |
| 「project card の進捗を paper 級に統合して」——溜まった進捗ブロックをまとめ上げる | `/research-cards:project-card-merge 〈プロジェクト名〉` |
| 「ナレッジグラフで私の project card の research-gap 分析をして」——分野の地図をプロジェクトカードと突き合わせ、まだ答えられていないギャップを見つける（Operation 5） | `/research-cards:overview-graph gap 〈プロジェクトカード〉` |
| 「この repo に研究実験 campaign を立ち上げて」——repo の準備状況チェック → 対話式 intake → MISSION.md ミッションブリーフ＋queue/ledger を生成 | `/research-cards:research-campaign init` |
| 「campaign を続けて」／「campaign の進捗は？」 | `/research-cards:research-campaign`（その repo のセッション内で）／`… status` |

対応関係はどこへ行ったのか：git repo 内なら git root の `.heptabase-card` marker。
「project root が git repo ではなく、repos がその 1 階層下にある」レイアウトでは registry
`~/.config/research-cards/projects.json` に入ります（配下のすべての repo が同じカードへ解決されます）。

**カードが満杯になったら（Heptabase の 100K 上限）**：何もしなくて大丈夫です——append がしきい値に
達すると「継続カード」を自動で開いて書き続けます（親カードの末尾にリンクが残り、Heptabase 内でたどれます）。
merge のときはチェーン全体をまとめて統合し、上限を超えたら H2 セクション単位で無損失に新しいチェーンへ
オーバーフローさせます。paper 級の詳細が 1 枚のカードに収めるために要約されることは決してありません。

<details><summary>低レベルコマンド</summary>

```bash
python3 skills/project-card-log/resolve_card.py                      # この repo ↔ どのカード
python3 skills/project-card-log/create_project_card.py --title "My Project"
#   monorepo のサブプロジェクトでは --marker-dir "$(pwd)" を渡してください
```
</details>

### ✍️ 論文執筆

| あなたが言うこと | skill を指名して行うなら |
|---|---|
| 「〈このオーバービューカード〉の BibTeX をエクスポートして」 | `/research-cards:bib-export 〈カードタイトル〉` |
| 「<hub カード> 配下のトピック全体の参考文献を全部エクスポートして」（hub → 子オーバービューカード → 論文） | `/research-cards:bib-export 〈hub カード〉 --depth 2` |

解決チェーン：Semantic Scholar → arxiv `/bibtex` → ACL Anthology → OpenReview。
見つからないものはすべて `% TODO` コメントになります——エントリを捏造することは決してないので、安心して `.bib` に貼り付けられます。

<details><summary>低レベルコマンド</summary>

```bash
cd skills/bib-export
python3 bib_export.py <card-id>                  # このカードが直接リンクする論文
python3 bib_export.py <hub-card-id> --depth 2    # hub → 子オーバービューカード → 論文
python3 bib_export.py <card-id> -o refs.bib      # '-' = stdout
```
</details>

### 🔁 同期

| あなたが言うこと | skill を指名して行うなら |
|---|---|
| 「obsidian-sync を実行して」 | `/research-cards:obsidian-sync` |
| 「まず dry-run で、どのカードが動くのか見せて」 | `/research-cards:obsidian-sync --dry-run` |
| 「コンフリクトはある？　Sync Conflicts を案内して」 | `/research-cards:obsidian-sync コンフリクト確認` |

仕組みの詳細は次の節を参照。agent は実行後に JSON レポートを読み、コンフリクトと TODO をあなたに展開して見せます。

## Heptabase ↔ Obsidian 同期

`backend: both`＝Heptabase を正として vault へミラーリング。ブロック単位の書き戻し、
手作りの .md の取り込み（adoption）、コンフリクト台帳、プロパティの 3-way 同期付き。
仕組み、round-trip を安全にする markdown 方言、コマンド対照表は wiki にあります：
[Note App Backends](https://github.com/SungFeng-Huang/research-cards/wiki/Note-App-Backends-ja)。

## 研究実験 Campaign

`research-campaign` は「1 つの project の長期的な自律実験キャンペーン」を標準化します：ミッションブリーフ
（MISSION.md）は project の中に住み、実験ラダーと結果台帳は中断・再開が可能で、計測規律は強制的に
ゲートされ、進捗はプロジェクトカードへ自動還流します。これは**トレーニング実行エンジンではありません**——トレーニングをどう走らせるかはあなたの
MISSION が決めます。skill が受け持つのは形式、記帳、そしてナレッジベースとの接続です。

完全なループ（これは本 plugin ならではのストーリーです）：

```
ナレッジベース  ──Op5 gap 分析──▶  MISSION 実験設計
   ▲                                    │
   │                            （campaign 実行）
   └──project-card-log でカードへ還流──  ledger の結果
        （merge で統合 → bib-export で参考文献を回収 → paper）
```

4 つのフェーズの入口（完全な操作マニュアル——準備状況チェックリスト、レイアウト選択、計測規律の全文、
showcase／トレーニング進捗ダッシュボードの設定——は wiki を参照：
[Research Campaign](https://github.com/SungFeng-Huang/research-cards/wiki/Research-Campaign-ja)）：

| フェーズ | あなたが言うこと | または実行 |
|---|---|---|
| **Setup** | 「この repo に研究実験 campaign を立ち上げて」——準備状況チェック → 事前調査でプレフィル → 一括の質疑応答 → MISSION ドラフトの承認 | `campaign.py init --repo <project> [--git]` |
| **Run** | 「campaign を続けて」——MISSION どおりに実行＋計測規律＋ledger への記帳＋カードへ還流 | （project セッション内で） |
| **Status** | 「campaign の進捗は？」——success gate まであと何が足りないか | `campaign.py status --dir runs/auto_research` |
| **Showcase**（オプション） | 自動更新される対外向けレポートページ＋トレーニング進捗ダッシュボード（GitHub／GitLab Pages） | `campaign.py pages-setup` ＋ `report`／`progress` |

核心の規律を一言で：**どんな「勝ち」も paired-delta の 95% CI が 0 を排除していること、一度に変えるのは
1 つだけ、評価 1 件につき ledger 1 行（schema ツールが門番）、ハイパーパラメータの決定は出典つきの推奨を引用すること**
（[alchemist-playbook](#連携オプション)）。単発の実験（キャンペーンを開かない場合）の軽量な代替は
wiki の [Ecosystem Integration](https://github.com/SungFeng-Huang/research-cards/wiki/Ecosystem-Integration-ja)
（experiment-agent の節）を参照。

## 無人スケジュール実行（クリッピングパイプライン）

`scholar-inbox-clip/run.py` はヘッドレスで実行できます：設定した Mail.app のメールボックスを読み、カードを作り、
テキスト生成のときにだけ設定した `agent` CLI を呼びます。モードは 3 つ：

- **Agent routine（推奨）**——agent に周期的な prompt をスケジュールします（例：Claude
  Code routines）：「scholar-inbox-clip のスケジュールフローを実行して」。agent が判断力を
  持って SKILL.md の契約を実行します（重複排除、Tasks タグ付け、オーバービューへのルーティング、図版の配置）——品質は最高です。
- **launchd（macOS）純スクリプト**——いちばん省エネ。カードは作られますが、Tasks タグ付けなどは対話式の
  backfill であとから補います：

  ```xml
  <!-- ~/Library/LaunchAgents/com.you.scholar-clip.plist -->
  <plist version="1.0"><dict>
    <key>Label</key><string>com.you.scholar-clip</string>
    <key>ProgramArguments</key>
    <array><string>/opt/homebrew/bin/python3</string><!-- pyyaml/pymupdf を
           入れたインタープリタと同一にすること（venv のパスでも可） -->
           <string>/path/to/research-cards/skills/scholar-inbox-clip/run.py</string></array>
    <key>StartInterval</key><integer>10800</integer>
    <key>StandardOutPath</key><string>/tmp/scholar-clip.log</string>
  </dict></plist>
  ```

- **cron + codex**——同じスクリプトを config `"agent": "codex"` と組み合わせるか、
  `codex exec` の prompt をそのまま routine の内容にします。

注意点：

- 無人実行の `osascript` は、**それを起動する実行ファイル自体**が一度自動化権限を取得している必要があります——
  先に同じインタープリタで対話式に 1 回実行し、Mail.app の許可プロンプトを承認しておいてください。
- 状態／重複排除は `~/.config/research-cards/scholar_inbox_state.json` に保存されます。処理済み
  メールの再実行は低コストの no-op なので、どれだけ高頻度にスケジュールしても安全です——ただし**重複排除 key は
  下流のステップが失敗した場合にも記録される**ため、スケジュールする前にまず対話式でパイプライン全体を通してください。
  さもないと、失敗した初回実行がメールを処理済みにマークしたのにカードは無い、という状態になります。
- Digest のソース：**Scholar Inbox**（スコアもリンクも解析）と **HuggingFace
  Daily Papers**（arxiv ID はリンクから直接取得。ランキングは個人化されていないため、採用の前に
  `email.hf_min_upvotes` の upvote しきい値＋config `profile.field` に基づく分野関連
  性フィルタを通します——agent が全部無関係と判断したらそのメールは丸ごとスキップ）を完全サポート。そのほか
  arxiv/alphaXiv リンクを含む任意の digest からも抽出できます。複数のソースが同じメールボックスフォルダを共有し、
  メールごとに自動で振り分けられます。

## 連携（オプション）

**Academic Research Skills（ARS）＋ experiment-agent（研究アウトプットライン）**——
research-cards が受け持つのは**長期ナレッジベース**。[Imbad0202](https://github.com/Imbad0202)
氏の [ARS](https://github.com/Imbad0202/academic-research-skills)（research →
write → review → revise の単一論文 pipeline。
[Codex 版](https://github.com/Imbad0202/academic-research-skills-codex)もあり）と
[experiment-agent](https://github.com/Imbad0202/experiment-agent)（実験の
実行＋監視＋統計解釈＋再現検証）が受け持つのは**単一の原稿と単発の実験**——この 2 つは
同じ作者で互いにネイティブに統合されていますが、本プロジェクトとは所属関係がありません。3 者は互いに依存せず、
それでいて深く混用できます：ディープリサーチの結果をカードライブラリへ clip し戻す、`bib-export`／オーバービューカード／プロジェクト台帳で
ARS の執筆ラインに供給する、experiment-agent の validate を campaign ledger の第二の目にする。
分担マトリクス、重なる部分の選び方、4 つの混用 recipe は wiki を参照：
[Ecosystem Integration](https://github.com/SungFeng-Huang/research-cards/wiki/Ecosystem-Integration-ja)。
（両者のライセンスは CC-BY-NC-4.0。インストールはそれぞれの README に従ってください。）

**alchemist-playbook（“錬丹”ハイパーパラメータ調整アドバイザー）**——`research-campaign` のハイパーパラメータ規律の
パートナー：campaign の契約は、すべてのハイパーパラメータ／schedule の決定に出典つきの推奨を引用することを要求します（ledger
の `playbook_rules_cited` フィールド）。alchemist-playbook はまさにそのために生まれました——
公開されたトレーニング記録（LLaMA/OLMo/DeepSeek-V3/Whisper/wav2vec 2.0/HuBERT…）から蒸留
された recipe アドバイザーで、どの数値にも `[config]`/`[paper]`/`[reported]` の信頼度ラベルが付きます。
side-by-side でインストールします（skill は repo のサブフォルダです）：

```bash
git clone https://github.com/voidful/AlchemistPlaybook ~/AlchemistPlaybook
ln -s ~/AlchemistPlaybook/alchemist-playbook ~/.claude/skills/alchemist-playbook
# Codex 側も同様に ~/.agents/skills/ へ link
```

未導入の場合 → campaign は通常どおり動作し、ハイパーパラメータ引用規律は「その他の出典つき推奨」（出所を
自分で明記）に格下げされます。MISSION テンプレートの REQUIRED READING には常備しておくことをおすすめします。

**hung-yi-lee teaching skill**——本 plugin の精神的な源流で、関係は 2 層あります：

1. **スタイル**：ガイド序文／リライトの執筆ルールは各 SKILL.md にすでに埋め込まれています——未導入でも完全な
   ティーチングスタイルが使えます。
2. **ランタイム**：`overview-graph` はあなたのオーバービューカードを external corpus として
   エクスポートし、この skill のナレッジグラフに供給できます（`export_hungyi_corpus.py` →
   `hungyi_kb.py graph build --external`）。これで「宏毅先生」の Q&A があなた自身の
   カードライブラリを直接引用するようになります。

この skill は本 plugin に同梱されません（独自の上流と PR フローがあり、しかも Codex の静的
plugin cache はネストした repo を読み込めないためです）。並列にインストールします。**本プロジェクト作者の fork の
`local/conda-env-integration` ブランチを入れることをおすすめします**——ランタイム連携に必要な拡張
（external corpus、出典マーキングなど）はこのブランチにあり、まだすべてが上流に入ったわけではありません。本 plugin も
このブランチに対してテストされています：

```bash
git clone -b local/conda-env-integration \
  https://github.com/SungFeng-Huang/hung-yi-lee-skill ~/.claude/skills/hung-yi-lee
pip install -r ~/.claude/skills/hung-yi-lee/requirements.txt
```

（ティーチングスタイルだけが欲しくて、エクスポート連携が不要なら、上流の
`voidful/hung-yi-lee-skill` を入れても構いません——MIT ライセンスで、その README の末尾に記載があります。）

そして config でそこを指します：

```json
"integrations": { "hung_yi_lee": { "skill_path": "~/.claude/skills/hung-yi-lee" } }
```

未導入の場合 → エクスポート機能は使えません。それ以外はすべて通常どおりです。

## トラブルシューティング

| 症状 | 原因／対処 |
|---|---|
| heptabase モードのコマンドが終了し、特定の config key を名指しする | その id が未記入です——メッセージが正確な key を示します。`heptabase tag list` / `heptabase tag properties <tagId>` で調べてください |
| iCloud の vault に触ると `Operation not permitted` が出る | ターミナル（またはスケジューラのインタープリタ）に**フルディスクアクセス権限**を与えてください |
| スケジュール実行が Mail を読めない | 自動化権限は「起動する実行ファイル」に紐づきます——同じインタープリタで対話式に 1 回実行し、プロンプトを承認してください |
| Codex が古い版の plugin を実行する | Codex は静的な cache コピーを実行しています——`codex plugin remove`＋`add` でリフレッシュし、`plugin_root` が生きている clone を指しているか確認してください |
| `obsidian-sync` が実行を拒否する | これは `backend: "both"` でのみ意味を持ちます——単一 backend では同期するものがありません |
| 同期が conflict を報告する | 仕様であってバグではありません：そのカードに非可逆な編集があるか、両側で分岐しています。レポート／`Sync Conflicts.md` の中のブロックと理由を確認し、残したい側を直して、再実行してください |

## License

MIT — [LICENSE](LICENSE) を参照。
