# research-cards — 훙이 리 교수처럼 연구 배우기 📚

[English](README.md) | [繁體中文](README.zh-TW.md) | [日本語](README.ja.md) | **한국어**

논문 피드를 **여러분을 가르쳐 주는 연구 지식 베이스**로 바꿔 줍니다. 모든 카드는
훙이 리 교수의 강의 한 편 같습니다 — 먼저 "왜 읽어야 하는지"와 필요한 사전 지식을
알려 주고, WHY 중심의 서사로 방법을 이해시킨 다음, 마지막으로 토픽 비교 카드와
지식 맵의 맥락 속에 배치해, 각 논문이 분야 전체에서 어디에 위치하는지 언제든 알 수
있게 합니다.

> 이 프로젝트는 [Hung-yi Lee 교수](https://speech.ee.ntu.edu.tw/~hylee/)의 티칭
> 스타일에 대한 오마주이며, 교수 본인과는 무관합니다. 티칭의 영혼은
> [hung-yi-lee skill](https://github.com/voidful/hung-yi-lee-skill)과
> 같은 맥을 잇습니다 — 함께 설치하시길 권합니다([통합](#통합선택-사항) 참고).

**순수 .md 파일 폴더**만으로 곧바로 동작합니다 — 노트 앱은 필요 없습니다.
**Obsidian**과 **Heptabase**는 선택형 업그레이드이고(각각 더 좋은 읽기
경험과 완전한 양방향 동기화를 제공), **Claude Code**와 **Codex** 어느
쪽으로도 구동되며 어떤 조합이든 됩니다. 이 플러그인이 해 주는 일:

- **클리핑**: digest 메일(또는 arxiv 링크 하나) → 티칭 스타일 카드 — 빠른 요약
  toggle, 시맨틱 컬러링, 그림, 속성 필드까지 한 번에 갖춰집니다.
- **조직화**: Tasks 분류 체계에 따라 각 토픽의 **비교 오버뷰 카드**로 자동
  라우팅하고, 서사형 가이드 서문, 토픽 허브, 횡적 링크, 시각화된 지식 맵을 곁들입니다.
- **동기화**: 카드 라이브러리 전체를 Heptabase ↔ Obsidian 간에 양방향 동기화합니다 —
  블록 단위 라이트백, 손실이 생길 상황이면 함부로 쓰지 않고 충돌로 보고,
  충돌 원장으로 추적 가능합니다.
- **연구 로그**: 어떤 프로젝트 repo의 session에서든 진행 상황을 해당 프로젝트 카드에
  기록하고, 나중에 paper 수준의 완결된 서술로 통합합니다 — 용량 상한에 도달하면
  자동으로 연속 카드 체인을 열어, 세부 내용이 100K 때문에 요약·압축되는 일은 결코 없습니다.
- **참고 문헌**: 카드가 링크한 모든 논문의 공식 BibTeX를 원클릭으로 내보냅니다.

---

**목차** ·
[Skills 개요](#skills-개요) ·
[설치](#설치) ·
[설정](#설정) ·
[빠른 시작(순수 .md)](#빠른-시작-a--순수-md-폴더노트-앱-불필요) ·
[빠른 시작(노트 앱)](#빠른-시작-b--노트-앱-사용하기) ·
[일상 사용법](#일상-사용법) ·
[연구 실험 Campaign](#연구-실험-campaign) ·
[무인 스케줄링](#무인-스케줄링클리핑-파이프라인) ·
[통합](#통합선택-사항) ·
[문제 해결](#문제-해결) ·
[License](#license)

> 📖 **사용 시나리오 가이드는 [Wiki](https://github.com/SungFeng-Huang/research-cards/wiki)에 있습니다**:
> [일상 연구 pipeline](https://github.com/SungFeng-Huang/research-cards/wiki/Daily-Research-Pipeline-ko)(어느 시점에 어떤 skill을 어떻게 이어 쓰는지) ·
> [생태계 통합](https://github.com/SungFeng-Huang/research-cards/wiki/Ecosystem-Integration-ko)(ARS / experiment-agent와의 역할 분담과 혼용 recipes) ·
> [Campaign 완전 매뉴얼](https://github.com/SungFeng-Huang/research-cards/wiki/Research-Campaign-ko) ·
> [Note App Backends](https://github.com/SungFeng-Huang/research-cards/wiki/Note-App-Backends-ko)(Heptabase／Obsidian 설정과 양방향 동기화).
> README는 설치·설정과 명령 대조표를 다루고, "어떤 상황에 무엇을 쓰는지"는 wiki를 보세요.

## Skills 개요

**📥 논문 클리핑** — 흘러 들어온 피드가 티칭 카드가 됩니다

| Skill | 하는 일 |
|---|---|
| `scholar-inbox-clip` | digest 메일/URL → 티칭 카드(속성, 그림, journal 기록, 오버뷰 라우팅) |
| `card-rewrite` | 기존 카드를 완전한 티칭 포맷으로 리라이트(한 줄 요약 / 왜 읽어야 하는가 / 사전 지식 / WHY 중심 서사 / 이중 언어 용어) |

**🗺️ 토픽 오버뷰와 지식 그래프** — 낱장 카드가 분야 지도로 자랍니다

| Skill | 하는 일 |
|---|---|
| `overview` | 각 토픽의 비교 오버뷰 카드를 유지 관리: 논문별 소절, 차원 비교 표, 커버리지 검사, arxiv ID 순 정렬 |
| `overview-daodu` | 오버뷰 카드 맨 위에 서사형 가이드 서문을 삽입/갱신(멱등) |
| `overview-graph` | 그래프 구조: 토픽 허브, 횡적 ↔/→ 링크, 지식 맵(Heptabase whiteboard / Obsidian JSON Canvas), 일관성 감사. **project 방향도 지원**: Operation 5는 지식 그래프로 프로젝트 카드의 research-gap 분석을 수행 |

**🧪 연구 프로젝트** — 여러분 자신의 연구도 카드입니다

| Skill | 하는 일 |
|---|---|
| `project-card-log` | 프로젝트 repo의 session(로컬 또는 원격)에서 이 프로젝트의 카드를 찾아내고, 날짜와 코드 근거가 있는 진행 기록을 덧붙입니다 — 추가만 하고 고치지 않습니다. 카드가 용량 상한에 도달하면 **자동으로 연속 카드 체인을 엽니다**(무손실, 100K에 욱여넣으려고 요약·압축하는 일은 절대 없음) |
| `project-card-merge` | 나머지 반쪽: 쌓인 진행 블록들을 paper 수준의 완결된 카드 한 장으로 통합합니다(풀 편집 환경 측). **chain-aware**: 연속 카드 체인 전체를 함께 읽고, 통합 결과가 상한을 넘으면 H2 섹션 단위로 새 체인으로 오버플로하며, 고아가 된 연속 카드는 자동 회수 |
| `project-card-canvas` | 프로젝트 체인의 시각 뷰(생성형 JSON Canvas): git-graph식 **타임라인**(entry=HEAD, log 카드=commits, 증류 상태 또는 실행 머신별 색상)과 **컨텍스트 마인드맵** 3가지 모드 — log 카드별 서브트리, 체인 본문 H2/H3 구조, 또는 연구 **스토리**를 막(幕) 단위 다중 행 DAG로(agent가 체인을 읽고 "아이디어→실험→결과→전환" 서사 그래프를 작성, script가 결정적으로 배치) |
| `research-campaign` | 자율 실험 캠페인의 미션 브리프 포맷 + 부기 관례: MISSION.md는 repo에 들어가고, queue/ledger로 중단 지점부터 재개하며, 유의성 gate 측정 규율을 지키고, 진행 상황은 프로젝트 카드로 자동 환류됩니다. 선택형 쇼케이스 레이어: 리포트 페이지 + **학습 log 곡선 대시보드**를 GitHub/GitLab Pages에 자동 배포 |

**✍️ 논문 작성** — paper를 쓸 때 지식 베이스를 수확합니다

| Skill | 하는 일 |
|---|---|
| `bib-export` | 아무 카드나 앵커로 삼아(오버뷰 카드, 프로젝트 카드 모두 가능) 그 카드가 링크한 논문들의 공식 BibTeX를 내보냅니다 — 절대 지어내지 않으며, 찾지 못한 항목은 `% TODO` 주석이 됩니다 |

**🔁 동기화 인프라**

| Skill | 하는 일 |
|---|---|
| `note-sync` | **동기화 체인의 단일 진입점** — `backends`(첫 항목=정본)에 따라 적용되는 각 세그먼트를 실행하고, HackMD 라이트백을 같은 실행에서 Heptabase까지 전달하며, 전 세그먼트의 충돌을 집계합니다. `--mode heptabase\|hackmd`로 단일 세그먼트만 실행 |

**⚙️ 설정**

| Skill | 하는 일 |
|---|---|
| `setup` | 대화형 config 마법사: example의 인라인 문서를 따라 `config.json`을 생성 / 점검 / 조정하며, 헬스 체크 검증기(`check_config.py`) 포함 |

스위치 소속: config `features.study`는 클리핑 + 오버뷰 + 지식 그래프를,
`features.project`는 연구 프로젝트 3종 세트(log／merge／campaign)를 관할합니다. `bib-export`와
`note-sync`는 방향 스위치의 영향을 받지 않습니다(전자는 여러분이 준
앵커 카드를, 후자는 backend를 따릅니다).

## 설치

### 요구 사항

| 사용할 기능 | 필요한 것 |
|---|---|
| 기본 | Python 3.10+, `pip install pyyaml`, agent CLI 하나(**Claude Code** 또는 **Codex**) |
| `backends`에 `"heptabase"` 포함 | macOS + **Heptabase 데스크톱 앱** + `heptabase` CLI **≥ 0.4.0**(로컬 API `127.0.0.1:21210`) |
| `backends`에 `"local"` 포함(기본값) | **.md 폴더 하나면 충분** — 어떤 디렉터리든 됩니다; **Obsidian vault**로 여는 것은 선택형 보너스(iCloud vault는 **전체 디스크 접근 권한** 필요) |
| HackMD 미러링(`note-sync --mode hackmd`) | `npm install -g @hackmd/hackmd-cli` + 한 번의 `hackmd-cli login`(API 토큰은 hackmd.io → Settings → API에서 발급; plugin config에는 절대 저장되지 않습니다) |
| 메일 클리핑(`scholar-inbox-clip`) | macOS **Mail.app** + 전용 메일함 폴더(Mail 규칙으로 digest를 그리로 유도) + `osascript` 자동화 권한 |
| 카드 그림 | `pip install pymupdf`(PDF 페이지) + `brew install librsvg`(SVG) |
| Claude Code 보너스 | **alphaXiv MCP**(클리핑/리라이트의 내용 근거)와 **heptabase MCP**(동기화 시 highlight 임베드 해석). 선택 사항 — Codex는 내장 HTTP 가져오기를 쓰고, highlight는 수동 보완 목록으로 제시됩니다 |
| 선택형 통합 skills | **hung-yi-lee**(티칭 스타일의 런타임 통합)와 **alchemist-playbook**(campaign의 하이퍼파라미터 인용 규율) — 설치법과 미설치 시 동작은 [통합](#통합선택-사항) 참고 |

### Claude Code

GitHub에서 바로 설치합니다:

```
/plugin marketplace add SungFeng-Huang/research-cards
/plugin install research-cards@research-cards
```

또는 clone한 뒤 repo를 skills 디렉터리에 symlink하면(예:
`~/.claude/skills/research-cards`), `.claude-plugin/plugin.json` 덕분에
plugin 형태로 로드됩니다. 두 방식 모두 skills는 `research-cards:<skill>`로 나타납니다.

### Codex

Codex는 "marketplace 디렉터리"에서 plugin을 설치합니다. 여러분의 clone을 위해 하나 만들어 둡니다(1회성):

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

Codex가 실행하는 것은 **정적 cache 사본**입니다: config에 `plugin_root`를
설정하세요(상태 읽기/쓰기가 살아 있는 repo에 앵커링됩니다). plugin을
업데이트한 뒤에는 `codex plugin remove` + `add`로 갱신하는 것을 잊지 마세요.

## 설정

가장 빠른 길: **"research-cards 설정해 줘"** 한마디면 됩니다 — `setup`
skill이 `config.example.json`의 인라인 문서를 따라 여러분을 인터뷰하고,
최소 config를 작성하고(순수 .md 모드는 `local.vault` 하나면 충분),
`skills/setup/check_config.py`로 검증합니다 — 이 검증기는 **upgrade
hints**(여러분의 config가 아직 옵트인하지 않은 새 설정)도 함께 보고합니다.
나중의 조정도 같은 방식입니다: "출력 언어를 바꿔 줘", "Heptabase를 연결해
줘" — 지목한 것만 고치고, 고친 뒤 다시 검증합니다.

전체 필드 지도와 설계 원칙(id는 절대 추측하지 않음, topics는 사용자
데이터)은 wiki에 있습니다:
[Configuration](https://github.com/SungFeng-Huang/research-cards/wiki/Configuration-ko).

## 빠른 시작 A — 순수 .md 폴더(노트 앱 불필요)

이것이 **기본값**입니다: 디렉터리 하나만 있으면 됩니다. 카드는 YAML
frontmatter가 붙은 순수 Markdown 파일이라 어떤 편집기로도 읽을 수 있고,
grep이 되고, git으로 버전 관리할 수 있습니다. 노트 앱 없이 10분 만에
논문 파이프라인을 세웁니다:

1. **설치** — plugin(위 참고) + `pip install pyyaml`
   (그림까지 원하면 `pymupdf`와 `librsvg` 추가).
2. **폴더 생성**(디스크 어디든 자유; iCloud에 둘 경우 터미널에 전체 디스크 접근 권한이 있어야 합니다).
3. **설정** — 최소 `~/.config/research-cards/config.json`
   (`backends`의 기본값이 `["local"]` — 바로 이 순수 .md 모드 — 라서 생략해도 됩니다):

   ```json
   {
     "agent": "claude",
     "plugin_root": "/path/to/research-cards",
     "profile": { "reader": "여러분의 독자 정체성", "field": "여러분의 분야" },
     "local": { "vault": "~/Documents/ResearchCards",
                   "folders": { "papers": "Papers", "overviews": "Overviews" } }
   }
   ```

   (`vault`는 그냥 여러분의 폴더입니다. 이 섹션은 개명 전의 옛 이름
   `obsidian`으로도 동작합니다.)
4. **첫 카드** — agent session에서 이렇게 말하세요:
   "scholar-inbox-clip으로 https://arxiv.org/abs/XXXX.XXXXX 를 카드로 만들어 줘".
   카드가 `Papers/`에 frontmatter 속성, 빠른 요약, 시맨틱 컬러링과 함께 나타납니다.
   (메일 클리핑은 선택 사항 — [스케줄링](#무인-스케줄링클리핑-파이프라인) 참고.)
5. **관련 논문이 몇 편 쌓이면, 구조를 키웁니다**:
   1. `skills/overview/topics/_example/`를
      `~/.config/research-cards/topics/<나의-토픽>/`으로 복사하고 `config.py`를 채웁니다.
   2. **hub 노트**를 한 장 만듭니다: `## 子卡與閱讀順序`(하위 카드와 읽기 순서)
      소절이 있어야 하고, `[[wikilinks]]`로 비교 카드를 나열하며, frontmatter
      `tasks`에 여러분의 Tasks 값이 들어가야 합니다 — hub 포맷은 API라서,
      하나라도 빠지면 topology가 곧바로 에러를 냅니다.
   3. hub를 config `local.graph.hubs`에 등록한 다음:

      ```bash
      python3 /path/to/research-cards/skills/_shared/topology.py refresh <나의-토픽>
      ```

   이후에는 `overview` / `overview-daodu` / `overview-graph`가 이 토픽을 유지 관리합니다.

## 빠른 시작 B — 노트 앱 사용하기

같은 폴더와 같은 파이프라인이 언제든 — 빠른 시작 A 전이든 후든 —
노트 앱과 짝을 이룹니다:

- **Obsidian**: 폴더를 vault로 여세요 — `[[wikilinks]]`가 클릭 가능해지고,
  Properties UI가 생기며, 지식 맵이 진짜 canvas로 렌더링됩니다.
  마이그레이션 제로, config 변경 제로.
- **Heptabase**: Heptabase에서 작성하거나(`backends: ["heptabase"]`), `backends: ["heptabase", "local"]`로
  Heptabase와 폴더 간의 완전한 블록 단위 **양방향 동기화**를 돌리세요 —
  라이트백, 직접 만든 .md 파일의 입양, 충돌 원장, 속성 3-way 동기화.
- **HackMD**(게시 우선): `note-sync`의 hackmd 세그먼트가 선택한 collection을 진짜 노트 간
  링크가 달린 HackMD 노트로 미러링합니다 — 오버뷰를 협업자와 공유하기
  위해 만들어졌습니다. 옵트인 `write_back`으로 "HackMD에서 나만 편집할 수
  있는" 노트는 양방향이 됩니다(공동 편집 가능한 노트는 절대 되돌려 쓰지
  않습니다).

두 앱의 설정 방법과 이중 저장소 모드(`backends: ["heptabase", "local"]`)의 완전한 동기화 메커니즘은 wiki에 있습니다:
[Note App Backends](https://github.com/SungFeng-Huang/research-cards/wiki/Note-App-Backends-ko).

## 일상 사용법

각 시점(아침 수집, 논문 읽기, 주간 유지 보수, 프로젝트 기간, 집필 기간)별 시나리오 흐름은
wiki를 보세요: [Daily Research Pipeline](https://github.com/SungFeng-Huang/research-cards/wiki/Daily-Research-Pipeline-ko).
이 절은 명령 대조표입니다. 일상적으로는 **skill을 부르는 것**이지, 명령을 돌리는 게 아닙니다:

- **자연어(권장)** — agent에게 원하는 것을 그냥 말하면, 알맞은 skill을 골라
  SKILL.md의 계약대로 실행합니다. 아래 각 절에 예문이 있습니다.
- **skill 지명** — Claude Code는 슬래시로: `/research-cards:<skill>`(예:
  `/research-cards:note-sync`); Codex는 메시지에서 skill 이름을 불러 주면 됩니다.
- **로우레벨 CLI** — 무인 스케줄링이나 debug 때만 필요하며, 각 절의
  "로우레벨 명령" 접이식 섹션에 담아 두었습니다(agent가 평소에 여러분 대신 돌리는 게 바로 이것들입니다).

### 📥 클리핑

| 이렇게 말하면 | 지정 skill로 하는 방법 |
|---|---|
| "https://arxiv.org/abs/XXXX.XXXXX 를 카드로 만들어 줘" | `/research-cards:scholar-inbox-clip https://arxiv.org/abs/XXXX.XXXXX` |
| "scholar inbox 메일함 한번 훑어 줘" — 메일 읽기, 중복 제거, 카드 생성, Tasks 태깅, 오버뷰 카드로 라우팅 | `/research-cards:scholar-inbox-clip` |
| "〈아무개 카드〉를 티칭 포맷으로 다시 써 줘" — 구조는 업그레이드, 사실은 그대로 | `/research-cards:card-rewrite 〈카드 제목〉` |

<details><summary>로우레벨 명령</summary>

```bash
python3 skills/scholar-inbox-clip/run.py    # 헤드리스 스케줄 모드(스케줄링 절 참고)
```
</details>

### 🗺️ 오버뷰와 지식 그래프

| 이렇게 말하면 | 지정 skill로 하는 방법 |
|---|---|
| "이 새 논문을 <topic> 오버뷰 카드에 추가해 줘" | `/research-cards:overview <topic> 〈논문〉 추가` |
| "<topic> 커버리지는 어때? 어떤 논문이 아직 비교 카드에 안 들어갔지?" | `/research-cards:overview <topic> status` |
| "이 오버뷰 카드의 가이드 서문을 갱신해 줘" | `/research-cards:overview-daodu 〈오버뷰 카드 제목〉` |
| "tokenizer와 spoken 사이에 횡적 링크 하나 추가해 줘" | `/research-cards:overview-graph 횡적 링크 추가 tokenizer ↔ spoken` |
| "graph audit 돌려 줘" — 구조 변경 후 hub/횡적 링크/지식 맵 일관성 검사 | `/research-cards:overview-graph audit` |
| "〈어느 whiteboard〉를 Obsidian Canvas로 미러링해 줘" — 실제 레이아웃(좌표/구역/연결선 + 자동 mention 선)을 단방향 덮어쓰기; 기본값은 app의 로컬 데이터베이스를 읽으며(실시간, app이 켜져 있어도 OK), 백업 파일은 예비 수단 | `/research-cards:overview-graph mirror` |

구조적 변경(새 hub, 재분할, 카드 이동) 후에는 agent가 topology refresh를
돌립니다 — 오버뷰 라우팅의 데이터 소스라서 생략할 수 없습니다.

<details><summary>로우레벨 명령</summary>

```bash
cd skills/overview
python3 sync_overview.py <topic> status   # 커버리지 diff → 어떤 논문이 MISSING인지
python3 sync_overview.py <topic> sort     # arxiv ID 순으로 목록 재정렬
python3 ../_shared/topology.py refresh    # 전체 토픽; 또는 refresh <topic>
```
</details>

### 🧪 연구 프로젝트

| 이렇게 말하면 | 지정 skill로 하는 방법 |
|---|---|
| "오늘 진행 상황을 project card에 기록해 줘" — 프로젝트 repo의 session에서 말하기만 하면 됩니다; agent가 해당 카드를 찾아내고(marker → registry), 카드가 없으면 만들지 물어봅니다 | `/research-cards:project-card-log`(프로젝트 repo 안에서, 인자 없이) |
| "이 프로젝트에 project card 한 장 만들어 줘" — 카드 생성 + 스켈레톤 + 태그 부착 + 매핑 고정을 한 번에 | `/research-cards:project-card-log 카드 생성 "My Project"` |
| "project card의 진행 기록을 paper 수준으로 통합해 줘" — 쌓인 진행 블록을 거둬들입니다 | `/research-cards:project-card-merge 〈프로젝트 이름〉` |
| "이 프로젝트의 canvas를 그려/업데이트해 줘" — git-graph 타임라인 + 컨텍스트 마인드맵; story 뷰는 agent가 체인을 읽고 서사 그래프를 작성하며, coverage 감사가 지도에 아직 무엇이 빠졌는지 알려 줍니다 | `/research-cards:project-card-canvas`(프로젝트 repo의 session 안에서) |
| "지식 그래프로 내 project card의 research-gap 분석을 해 줘" — 분야 지도를 프로젝트 카드와 대조해 아직 답해지지 않은 갭을 찾습니다(Operation 5) | `/research-cards:overview-graph gap 〈프로젝트 카드〉` |
| "이 repo에 연구 실험 campaign을 하나 열어 줘" — repo 준비 상태 점검 → 인터랙티브 intake → MISSION.md 미션 브리프 + queue/ledger 생성 | `/research-cards:research-campaign init` |
| "campaign 이어서 해 줘" / "campaign 진행 상황 어때" | `/research-cards:research-campaign`(해당 repo session 안에서) / `… status` |

매핑은 어디에 있나: git repo 안에서는 git root의 `.heptabase-card` marker;
"project root가 git repo가 아니고 repos가 한 층 아래에 있는" 레이아웃이라면 registry
`~/.config/research-cards/projects.json`에 들어갑니다(그 아래 모든 repo가 같은 카드로 해석됩니다).

**카드가 가득 차면(Heptabase 100K 상한)**: 아무것도 안 해도 됩니다 — append가
문턱값에 도달하면 자동으로 "연속 카드"를 열어 이어 씁니다(부모 카드 끝에 링크가 남아
Heptabase 안에서 클릭해 넘어갈 수 있습니다); merge 때는 체인 전체를 함께 거둬들이고,
상한을 넘으면 H2 섹션 단위로 무손실 오버플로해 새 체인을 만듭니다. paper 수준의
세부 내용이 카드 한 장에 욱여넣기 위해 요약·압축되는 일은 영원히 없습니다.

<details><summary>로우레벨 명령</summary>

```bash
python3 skills/project-card-log/resolve_card.py                      # 이 repo ↔ 어느 카드
python3 skills/project-card-log/create_project_card.py --title "My Project"
#   monorepo 하위 프로젝트는 --marker-dir "$(pwd)" 를 전달하세요
```
</details>

### ✍️ 논문 작성

| 이렇게 말하면 | 지정 skill로 하는 방법 |
|---|---|
| "〈이 오버뷰 카드〉의 BibTeX를 내보내 줘" | `/research-cards:bib-export 〈카드 제목〉` |
| "<hub 카드> 아래 토픽 전체의 참고 문헌을 다 내보내 줘"(hub → 하위 오버뷰 카드 → 논문) | `/research-cards:bib-export 〈hub 카드〉 --depth 2` |

해석 체인: Semantic Scholar → arxiv `/bibtex` → ACL Anthology → OpenReview.
찾지 못한 것은 전부 `% TODO` 주석이 됩니다 — 항목을 절대 지어내지 않으니,
안심하고 `.bib`에 붙여 넣어도 됩니다.

<details><summary>로우레벨 명령</summary>

```bash
cd skills/bib-export
python3 bib_export.py <card-id>                  # 이 카드가 직접 링크한 논문
python3 bib_export.py <hub-card-id> --depth 2    # hub → 하위 오버뷰 카드 → 논문
python3 bib_export.py <card-id> -o refs.bib      # '-' = stdout
```
</details>

### 🔁 동기화

| 이렇게 말하면 | 지정 skill로 하는 방법 |
|---|---|
| "노트 동기화/전부 동기화" | `/research-cards:note-sync` |
| "Heptabase↔vault 세그먼트만 돌려 줘" | `/research-cards:note-sync --mode heptabase` |
| "먼저 dry-run으로 어떤 카드가 바뀔지 보여 줘" | `/research-cards:note-sync --dry-run` |
| "충돌 있어? 같이 봐 줘" | `/research-cards:note-sync`(집계 리포트에 전 세그먼트의 충돌이 나열됩니다) |

메커니즘 세부 사항은 wiki의 [Note App Backends](https://github.com/SungFeng-Huang/research-cards/wiki/Note-App-Backends-ko)를 보세요; agent는 실행 후 JSON 리포트를 읽고
충돌과 할 일을 여러분 앞에 펼쳐 보여 줍니다.

## 연구 실험 Campaign

`research-campaign`은 "한 project의 장기 자율 실험 캠페인"을 표준화합니다: 미션 브리프
(MISSION.md)는 project 안에 살고, 실험 사다리와 결과 원장은 중단 지점부터 재개할 수
있으며, 측정 규율이 강제로 지켜지고, 진행 상황은 프로젝트 카드로 자동 환류됩니다.
이것은 **학습 실행기가 아닙니다** — 학습을 어떻게 돌릴지는 여러분의
MISSION이 결정합니다; skill이 관리하는 것은 포맷, 부기, 그리고 지식 베이스와의 인터페이스입니다.

완전한 폐쇄 루프(이것이 본 plugin만의 서사입니다):

```
지식 베이스  ──Op5 gap 분석──▶  MISSION 실험 설계
   ▲                                 │
   │                          (campaign 실행)
   └──project-card-log 카드 반영──  ledger 결과
        (merge 통합 → bib-export 참고 문헌 수확 → paper)
```

네 단계의 진입점(완전한 운영 매뉴얼 — 준비 상태 체크리스트, 레이아웃 선택, 측정 규율 전문,
showcase/학습 진행 대시보드 설정 — 은 wiki 참고:
[Research Campaign](https://github.com/SungFeng-Huang/research-cards/wiki/Research-Campaign-ko)):

| 단계 | 이렇게 말하면 | 또는 실행 |
|---|---|---|
| **Setup** | "이 repo에 연구 실험 campaign을 하나 열어 줘" — 준비 상태 점검 → 사전 조사로 미리 채움 → 일괄 질의응답 한 번 → MISSION 초안 승인 | `campaign.py init --repo <project> [--git]` |
| **Run** | "campaign 이어서 해 줘" — MISSION대로 실행 + 측정 규율 + ledger 부기 + 카드 반영 | (project session 안에서) |
| **Status** | "campaign 진행 상황 어때" — success gate까지 무엇이 남았는지 | `campaign.py status --dir runs/auto_research` |
| **Showcase**(선택 사항) | 자동 갱신되는 대외 리포트 페이지 + 학습 진행 대시보드(GitHub/GitLab Pages) | `campaign.py pages-setup` + `report`/`progress` |

핵심 규율 한 줄: **모든 "승리"는 paired-delta 95% CI가 0을 배제해야 하고, 한 번에
하나만 바꾸며, 평가 하나당 ledger 한 줄(schema 도구가 검증), 하이퍼파라미터 결정은
출처 있는 권고를 인용해야 합니다**([alchemist-playbook](#통합선택-사항)). 단발 실험
(캠페인을 열지 않을 때)의 경량 대안은 wiki의
[Ecosystem Integration](https://github.com/SungFeng-Huang/research-cards/wiki/Ecosystem-Integration-ko)
(experiment-agent 절)을 보세요.

## 무인 스케줄링(클리핑 파이프라인)

`scholar-inbox-clip/run.py`는 헤드리스로 실행할 수 있습니다: 설정된 Mail.app
메일함을 읽어 카드를 만들고, 텍스트 생성 때만 설정된 `agent` CLI를 호출합니다. 세 가지 모드:

- **Agent routine(권장)** — agent에 주기적 prompt를 하나 등록합니다(예: Claude
  Code routines): "scholar-inbox-clip의 스케줄 플로를 실행해 줘". agent가 판단력을
  갖고 SKILL.md 계약(중복 제거, Tasks 태깅, 오버뷰 라우팅, 그림 배치)을 수행합니다 — 품질이 가장 높습니다.
- **launchd(macOS) 순수 스크립트** — 가장 가볍습니다; 카드는 만들어지지만 Tasks
  태깅 등은 인터랙티브 backfill로 나중에 보완합니다:

  ```xml
  <!-- ~/Library/LaunchAgents/com.you.scholar-clip.plist -->
  <plist version="1.0"><dict>
    <key>Label</key><string>com.you.scholar-clip</string>
    <key>ProgramArguments</key>
    <array><string>/opt/homebrew/bin/python3</string><!-- pyyaml/pymupdf 를
           설치한 인터프리터와 같아야 합니다(venv 경로도 가능) -->
           <string>/path/to/research-cards/skills/scholar-inbox-clip/run.py</string></array>
    <key>StartInterval</key><integer>10800</integer>
    <key>StandardOutPath</key><string>/tmp/scholar-clip.log</string>
  </dict></plist>
  ```

- **cron + codex** — 같은 스크립트를 config `"agent": "codex"`와 함께 쓰거나,
  아예 `codex exec` prompt를 routine 내용으로 삼습니다.

주의 사항:

- 무인 `osascript`는 **그것을 구동하는 바로 그 실행 파일**이 자동화 권한을 한 번
  받아 둔 상태여야 합니다 — 먼저 같은 인터프리터로 인터랙티브하게 한 번 돌려서
  Mail.app 권한 프롬프트를 승인해 두세요.
- 상태/중복 제거는 `~/.config/research-cards/scholar_inbox_state.json`에 저장됩니다.
  처리 완료된 메일의 재실행은 값싼 no-op라서 아무리 촘촘히 스케줄해도 안전합니다 —
  다만 **중복 제거 key는 다운스트림 단계가 실패해도 기록되므로**, 스케줄링 전에
  파이프라인 전체를 인터랙티브하게 한 번 통과시키세요; 그러지 않으면 실패한 첫
  실행이 메일을 처리 완료로 표시해 놓고 카드는 없는 상태가 됩니다.
- Digest 소스: **Scholar Inbox**(점수/링크 모두 파싱)와 **HuggingFace
  Daily Papers**(arxiv ID는 링크에서 바로 추출; 순위 리스트가 개인화되어 있지 않으므로,
  선정 전에 `email.hf_min_upvotes` 업보트 문턱값 + config `profile.field` 기준의
  분야 관련성 필터를 거칩니다 — agent가 전부 무관하다고 판단하면 그 메일은
  통째로 건너뜁니다)를 완전 지원합니다; 그 밖에 arxiv/alphaXiv 링크가 들어 있는
  어떤 digest에서도 추출할 수 있습니다. 여러 소스가 같은 메일함 폴더를 공유하며,
  메일별로 자동 분류됩니다.

## 통합(선택 사항)

**Academic Research Skills(ARS) + experiment-agent(연구 산출 라인)** —
research-cards는 **장기 지식 베이스**를 담당합니다; [Imbad0202](https://github.com/Imbad0202)의
[ARS](https://github.com/Imbad0202/academic-research-skills)(research →
write → review → revise의 단일 논문 pipeline,
[Codex 판](https://github.com/Imbad0202/academic-research-skills-codex)도 있음)와
[experiment-agent](https://github.com/Imbad0202/experiment-agent)(실험
실행 + 모니터링 + 통계 해석 + 재현 검증)는 **단일 원고와 단발 실험**을 담당합니다 — 이 둘은
서로 같은 저자에 서로 네이티브로 통합되어 있으며, 본 프로젝트와는 소속 관계가 없습니다.
셋은 서로 의존하지 않지만 깊게 혼용할 수 있습니다: 딥 리서치 결과를 카드 라이브러리로
clip해 오고, `bib-export`/오버뷰 카드/프로젝트 원장을 ARS 집필 라인에 먹이고,
experiment-agent의 validate를 campaign ledger의 두 번째 눈으로 삼는 식입니다.
역할 분담 매트릭스, 겹치는 곳에서의 선택법, 혼용 recipe 네 가지는 wiki 참고:
[Ecosystem Integration](https://github.com/SungFeng-Huang/research-cards/wiki/Ecosystem-Integration-ko).
(둘의 라이선스는 CC-BY-NC-4.0이며, 설치는 각자의 README를 따르세요.)

**alchemist-playbook(연금술식 하이퍼파라미터 튜닝 자문)** — `research-campaign`의 하이퍼파라미터
규율 파트너입니다: campaign 계약은 모든 하이퍼파라미터/schedule 결정이 출처 있는 권고를
인용할 것을 요구하는데(ledger의 `playbook_rules_cited` 필드), alchemist-playbook이
바로 그것을 위해 태어났습니다 — 공개 학습 기록(LLaMA/OLMo/DeepSeek-V3/Whisper/wav2vec 2.0/HuBERT…)에서
증류한 recipe 자문으로, 모든 숫자에 `[config]`/`[paper]`/`[reported]` 신뢰도가 표시됩니다.
나란히 설치합니다(skill은 repo의 하위 폴더):

```bash
git clone https://github.com/voidful/AlchemistPlaybook ~/AlchemistPlaybook
ln -s ~/AlchemistPlaybook/alchemist-playbook ~/.claude/skills/alchemist-playbook
# Codex 쪽도 마찬가지로 ~/.agents/skills/ 에 링크
```

미설치 → campaign은 평소대로 동작하고, 하이퍼파라미터 인용 규율은 "출처 있는 다른
권고"(직접 출처 표기)로 강등됩니다; MISSION 템플릿의 REQUIRED READING에는 이 항목을
상비해 두길 권합니다.

**hung-yi-lee teaching skill** — 본 plugin의 정신적 뿌리이며, 관계는 두 층입니다:

1. **스타일**: 가이드 서문/리라이트의 작문 규칙은 이미 각 SKILL.md에 내장되어
   있습니다 — 설치하지 않아도 완전한 티칭 스타일이 나옵니다.
2. **런타임**: `overview-graph`가 여러분의 오버뷰 카드를 external corpus로 내보내
   해당 skill의 지식 그래프에 먹일 수 있습니다(`export_hungyi_corpus.py` →
   `hungyi_kb.py graph build --external`) — "훙이 리 교수"의 Q&A가 여러분 자신의
   카드 라이브러리를 직접 인용하게 됩니다.

그 skill은 본 plugin에 내장하지 않습니다(자체 업스트림과 PR 절차가 있고, Codex의 정적
plugin cache는 중첩 repo를 로드하지 못합니다). 나란히 설치하되, **본 프로젝트 저자의
fork에 있는 `local/conda-env-integration` 브랜치를 설치하길 권합니다** — 런타임
통합에 필요한 확장(external corpus, 출처 표기 등)이 그 브랜치에 있고 아직 전부
업스트림에 들어가지 않았습니다; 본 plugin도 그것을 대상으로
테스트되었습니다:

```bash
git clone -b local/conda-env-integration \
  https://github.com/SungFeng-Huang/hung-yi-lee-skill ~/.claude/skills/hung-yi-lee
pip install -r ~/.claude/skills/hung-yi-lee/requirements.txt
```

(티칭 스타일만 원하고 내보내기 통합이 필요 없다면, 업스트림
`voidful/hung-yi-lee-skill`을 설치해도 됩니다 — MIT 라이선스이며, 해당 README 끝부분에 적혀 있습니다.)

그다음 config에서 가리키게 합니다:

```json
"integrations": { "hung_yi_lee": { "skill_path": "~/.claude/skills/hung-yi-lee" } }
```

미설치 → 내보내기 기능만 사용 불가; 나머지는 모두 평소대로입니다.

## 문제 해결

| 증상 | 원인 / 해결법 |
|---|---|
| heptabase 모드 명령이 특정 config key를 지목하며 종료함 | 그 id가 비어 있습니다 — 메시지가 정확한 key를 알려 줍니다; `heptabase tag list` / `heptabase tag properties <tagId>`로 조회하세요 |
| iCloud vault를 건드리면 `Operation not permitted`가 남 | 터미널(또는 스케줄러의 인터프리터)에 **전체 디스크 접근 권한**을 주세요 |
| 스케줄 실행이 Mail을 읽지 못함 | 자동화 권한은 "구동하는 실행 파일"을 따라갑니다 — 같은 인터프리터로 인터랙티브하게 한 번 돌리고 프롬프트를 승인하세요 |
| Codex가 옛 버전 plugin을 실행함 | 정적 cache 사본을 실행하기 때문입니다 — `codex plugin remove` + `add`로 갱신하고, `plugin_root`가 살아 있는 clone을 가리키는지 확인하세요 |
| `note-sync`가 heptabase 세그먼트를 건너뜀 | `backends: ["heptabase", "local"]` 이중 저장소에서만 적용됩니다 — 단일 저장소에는 미러링할 대상이 없습니다 |
| 동기화가 conflict를 보고함 | 버그가 아니라 의도된 동작입니다: 그 카드에 손실성 편집이 있거나 양쪽이 갈라졌습니다. 리포트/`Sync Conflicts.md`에서 해당 블록과 원인을 보고, 남기고 싶은 쪽을 고친 뒤 다시 돌리세요 |

## License

MIT — [LICENSE](LICENSE) 참고.
