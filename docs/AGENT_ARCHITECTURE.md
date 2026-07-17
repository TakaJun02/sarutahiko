# エージェント全体アーキテクチャ（ワークフローとツール）

- 版: v1.0（2026-07-17, Fable 起草 — 利用者指示 FR-27-4）
- 目的: AI エージェント（`backend/app/agent/graph.py` の `RealCampusAgent`）の**ワークフロー全体**と
  **各ノードで使用可能なツール**を一望できるようにする。
- 実装詳細（プロンプト全文・定数・検収履歴）は `docs/AGENT_HARNESS.md` が正。
  SSE イベントスキーマは `docs/ARCHITECTURE.md` §3。**graph.py の構造を変える変更は本文書の更新を伴うこと**。

## 1. システム全体の配置

```mermaid
flowchart LR
    subgraph client["ブラウザ（Vue 3 SPA）"]
        UI["ChatView / MapCard<br/>SSE 受信・なめらか文字送り（FR-25）"]
    end
    subgraph host["本機（RTX 3090 Ti）"]
        BE["FastAPI backend<br/>/api/chat ほか"]
        VLLM["vLLM 生成<br/>Gemma 4 12B (w4a16)"]
        QD[("Qdrant<br/>campus_knowledge<br/>784+ チャンク")]
        DB[("SQLite<br/>users / threads / messages")]
    end
    subgraph gouin["第2GPUサーバー gouin"]
        EMB["vLLM 埋め込み<br/>Qwen3-Embedding-8B"]
    end
    TAVILY["Tavily Web Search API<br/>（サーキットブレーカー付き・FR-18-1）"]

    UI -- "POST /api/chat（SSE）" --> BE
    BE -- "chat.completions<br/>（JSON 生成・ストリーミング）" --> VLLM
    BE -- "/v1/embeddings" --> EMB
    BE -- "ベクトル検索 / 字句スキャン" --> QD
    BE -- "httpx" --> TAVILY
    BE -- "永続化" --> DB
```

## 2. エージェントワークフロー（LangGraph）

1 リクエスト = 1 実行。ステップ遷移のたびに SSE `status` を送出する（FR-2）。
FR-26 の ask_origin 短絡だけは LangGraph に入る前にターンを終える。

```mermaid
flowchart TD
    Q["ユーザー質問<br/>（origin_node があれば backend が<br/>『現在地は〇〇です。＋質問』を内部合成・FR-27）"] --> AN

    AN["<b>analyze</b><br/>検索計画（retrieval_queries / keywords）<br/>＋ route 意図抽出（type / origin / destination）"]

    AN -->|"route 質問で destination 解決済み<br/>かつ origin 未解決（FR-26）"| ASK["<b>ask_origin 短絡</b><br/>定型短文 ＋ map(ask_origin) ＋ done<br/>（検索・生成なし。マップタップ待ちでターン終了）"]

    AN -->|通常| RT["<b>retrieve</b><br/>ベクトル検索"]
    RT --> SE["<b>search</b><br/>字句グレップ（レア語・部屋番号）"]
    SE --> EV{"<b>evaluate</b><br/>根拠は十分か？（LLM 判定）"}

    EV -->|"sufficient"| GE
    EV -->|"grep_keywords あり<br/>（上限 MAX_LOCAL_SEARCH_FOLLOWUPS 内）"| SE
    EV -->|"followup_retrieval_queries あり<br/>（上限内・未使用クエリあり）"| RTF["<b>retrieve_followup</b><br/>追加ベクトル検索"]
    RTF --> EV
    EV -->|"なお不足"| WS1["<b>web_search</b>（第1ラウンド）<br/>akita-pu.ac.jp ドメイン限定"]

    WS1 --> EVW{"<b>evaluate_after_web</b>"}
    EVW -->|"なお不足"| WS2["<b>web_search_second</b>（第2ラウンド）<br/>ドメイン制限なし"]
    EVW -->|"sufficient"| GE
    WS2 --> EVS["<b>evaluate_after_second</b>"]
    EVS --> GE["<b>generate</b><br/>コンテキスト組立→トークン予算検査→<br/>回答ストリーミング（token 逐次送出）"]

    GE --> MP{"route / place が<br/>解決済みか？"}
    MP -->|"yes"| MC["map イベント送出<br/>（Dijkstra 決定的計算・LLM 不関与）"]
    MP -->|"no"| DONE
    MC --> DONE["done<br/>（sources・スレッド永続化）"]
    ASK --> DONE2["done（sources 空）"]
```

- Tavily がクォータ超過等（401/403/429/432/433）のとき、Web 2 ラウンドはスキップされ
  ナレッジのみで generate へ進む（FR-18-1 サーキットブレーカー）。
- generate はトークン予算超過時に縮小コンテキストで 1 回だけ再構築・リトライする。

## 3. 各ノードの役割と使用ツール

| ノード | 役割 | 使用ツール / 外部リソース | LLM |
|---|---|---|---|
| analyze | 検索計画（クエリ 2〜3 本・keywords ≤6 語）と route 意図（type/origin/destination）の JSON 抽出。直近 4 ターン履歴（FR-18-5）を参照 | 生成 vLLM（JSON 応答）、campus_map リゾルバ（`resolve_location`: NFKC 正規化辞書引き — LLM 不使用） | ✔ |
| ask_origin 短絡 | 出発地不明の経路質問でターンを終端し、マップタップカードを提示（FR-26） | campus_map（`ask_origin_map_payload`）。検索・生成は実行しない | — |
| retrieve / retrieve_followup | 意味ベクトル検索。followup は evaluate が提案した未使用クエリのみ実行 | 埋め込み vLLM（Qwen3-Embedding-8B・gouin）＋ Qdrant 類似検索 | — |
| search | レアトークン（部屋番号 GI512 等・固有名詞）の決定的字句グレップ。表記ゆれはバリアント展開 | Qdrant スキャン＋コード内正規化（`app/rag/lexical.py`）。LLM・埋め込み不使用 | — |
| evaluate（3 種） | 集めた根拠の充足判定と不足時の追加手段提案（grep_keywords / followup_retrieval_queries / web_queries） | 生成 vLLM（JSON 応答） | ✔ |
| web_search（第1） | 公式サイト限定の Web 検索と本文取得 | Tavily API（`include_domains: akita-pu.ac.jp`、raw_content、サーキットブレーカー） | — |
| web_search_second（第2） | ドメイン制限なしの追加 Web 検索 | Tavily API（制限なし） | — |
| generate | 根拠を組み立てて回答を生成・ストリーミング。出典 dedupe。履歴由来の出発地は冒頭で明示（FR-26 §7-4） | 生成 vLLM（ストリーミング）。トークン予算検査・縮小リトライはコード | ✔ |
| map 送出（generate 後） | 経路/場所カードのペイロード計算 | campus_map（Dijkstra・並行エッジの階選択・ステップ文テンプレート — **LLM に空間推論をさせない**、FR-11/26 原則） | — |

## 4. FR-26/27 マップタップの会話フロー（ターン境界）

mid-run interrupt は不採用（裁定: `docs/MAP_CARD.md` §2-1）。エリシテーションはターン終端で行う。

```mermaid
sequenceDiagram
    participant U as 来場者
    participant F as フロント（MapCard）
    participant B as backend
    participant A as エージェント

    U->>B: POST /api/chat「D404に行きたい」
    B->>A: 実行
    A-->>F: status(analyze) → status(generate)
    A-->>F: token「マップでタップして…」＋ map(ask_origin) ＋ done
    Note over F: composer ロック（FR-27-1）<br/>タップ or キャンセルのみ受付
    U->>F: ノードをタップ（例: カフェテリア）
    F->>B: POST /api/chat {message: 元質問, origin_node: "cafeteria"}
    Note over B: 「現在地はカフェテリア（食堂）です。<br/>D404に行きたい」を内部合成（FR-27-2）<br/>user メッセージに origin_select メタ保存
    B->>A: 実行（通常フロー）
    A-->>F: status × n → token 逐次 → map(route) → done
    Note over F: user 側は現在地チップ表示<br/>assistant 側は経路カード＋ステップ
```

## 5. SSE イベント（要約）

`status`（各ステップ開始時・FR-2）→ `token`（回答本文の逐次配信・FR-3/25）→
`map`（route / place / ask_origin。token 完了後・done 直前に最大 1 回・FR-26）→
`done`（thread_id / message_id / sources）。エラー時は `error`。
詳細スキーマは `docs/ARCHITECTURE.md` §3。
