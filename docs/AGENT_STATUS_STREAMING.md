# FR-36: 探索思考のライブステータス（decide ストリーミング表示）

- 版: **v1.0**（2026-07-18, Fable 確定 — §1 の本番実測と §1-3 のストリーミング検証プローブ合格を受けて確定。
  実装（Codex）に入ってよい）
- 位置づけ: ハーネス v6（FR-34 ReAct、`docs/AGENT_REACT.md`）への**表示系追補**。decide ループの LLM 判断を
  ストリーミングし、生成途中の `thought` を status イベントとして逐次配信することで、
  「今何をしているか」の粒度を確定仕様 2（推論ステップ実況）の水準まで引き上げる。
- 関連文書: `ARCHITECTURE.md` §3（SSE 契約 — 本 FR で **additive 変更**: `status.partial`）、
  `AGENT_ARCHITECTURE.md` §5（SSE 要約 — 追記）、`MAP_CARD.md`（不変）、`AGENT_HARNESS.md`（プロンプト不変）。

## 0. 決定ログ（2026-07-18, Fable）

| # | 論点 | 裁定 |
|---|---|---|
| 1 | 待ち時間の主因 | **decide の LLM 呼び出し**（§1 実測: 1 回 3.3〜5.1 秒・1 質問で最大 12 回）。ツール実行自体は 0.1〜0.3 秒であり、ステータスがノード境界でしか変わらないことが「分析しています…が長い」の正体 |
| 2 | 改善方式 | **decide 出力のストリーミング＋thought の逐次表示**を採用。guided JSON はスキーマ宣言順に生成され `thought` が先頭に来ることを本番 31B で実測確認済み（§1-3）。回転メッセージ等の「偽の進捗」は不採用（確定仕様 2 は実況であり演出ではない） |
| 3 | SSE 契約 | `status` に **`partial: boolean` を追加**（常に付与・既定 false）。イベント種別・step 語彙は不変。旧フロントは未知キーを無視できるため互換 |
| 4 | decide 開始時の静的ステータス | 2 周目以降は**追加しない**。直前ツールの status を prefill（〜1.5 秒）の間残すことで、ツール文言の可読時間を確保する（追加すると 0.3 秒でフラッシュして読めなくなる） |
| 5 | `_sanitize_thought` の長文規則 | 120 字超過は**全置換 → 先頭 120 字＋「…」の切り詰め**に変更。本番 trace で長文 thought が頻出しており、汎用文言への置換は情報を捨てている。マーカー混入・空文字の全置換は不変 |
| 6 | navigator | **同一機構を適用**（内部 decide も 3〜4 秒 × 最大 3 回）。fast_path は LLM を呼ばないため対象外 |
| 7 | フロントのフェード | LoadingSpinnerV5 の `<Transition mode="out-in">` は text 変化ごとに 250ms+250ms のフェードが走るため、**部分更新はフェード対象から除外**（§4 の runId 方式）。放置するとストリーミングが常時フェードで判読不能になる |

## 1. 診断（2026-07-18 本番実測）

### 1-1. 時間の内訳

本番 backend の agent.trace（docker logs -t、trace_id 8b097e0a / e60a1416）より:

- decide 1 回 = **3.3〜5.1 秒**（プロンプト実測 約 2,800 トークン・出力 100〜150 トークン）。
- retrieve = 0.1〜0.3 秒、search = 数 ms。**体感待ちのほぼ全部が decide**。
- 探索の深い質問では decide が 1 質問で 12 回 → decide 合計 約 45 秒。
- status はノード境界でのみ更新: 初回 decide 中は「ご質問をじっくり読み解いています…」が
  3.5〜5 秒固定。2 周目以降は**直前ツールの status が次の decide 中ずっと表示**され、
  thought は decide 完了後にまとめて 1 回出るだけ。
- 追記: 長い thought（120 字超）は `_sanitize_thought` が汎用文言
  「集めた情報をチェックしています…」へ全置換しており、実況の情報量をさらに落としている。

### 1-2. フロントの表示経路

`stores/chat.js` が status イベントで `message.statusText / statusStep` を置換 →
`LoadingSpinnerV5.vue` が表示。text 変化のたび `<Transition mode="out-in">`（`:key="displayText"`）で
250ms フェードアウト＋250ms フェードインが走る（現状は数秒に 1 回なので成立している）。

### 1-3. ストリーミング成立性の実測（プローブ）

本番 31B PP=2 エンドポイント（`google/gemma-4-31B-it-qat-w4a16-ct`）へ
`stream: true` ＋ `response_format: json_schema`（decide と同一スキーマ）で実測:

- チャンクは**逐次到着**する（54 チャンク・中央値間隔 25ms ≒ 40 チャンク/秒）。
- 出力はスキーマ宣言順で `{\n  "thought": "…` から始まる（**thought 先頭を確認**）。
- 先頭チャンクは 0.2 秒（短プロンプト時。本番 2.8k トークンでは prefill 約 1〜1.5 秒を見込む）。

## 2. SSE 契約の追補（`ARCHITECTURE.md` §3 に反映済み）

```
event: status
data: {"step": "analyze" | ... | "generate", "text": "…", "partial": true | false}
```

- `partial: true` = 「現在進行中の思考の**伸長中の断片**。フロントはフェードなしで
  その場の文字列を書き換えてよい」。同一 step のまま text が単調に伸びる系列で届く。
- `partial: false` = 従来どおりの確定ステータス。**既存の全 status は `partial: false` を常に付与**
  （キー省略ではなく明示。スキーマを一様にし、テストの期待値も全箇所更新する —
  これは意図した外形変更である）。
- イベント種別・step 語彙・他イベント（token / map / done / error）は不変。

## 3. backend 仕様

### 3-1. VLLMClient（`backend/app/llm/client.py`）

- `decide_stream(messages, schema) -> AsyncIterator[str]` を新設。リクエストは既存 `decide` と
  同一（temperature 0.2 / max_tokens 300 / response_format json_schema）で `stream: true` のみ違う。
  delta の content 断片をそのまま yield する。
- 既存 `decide` は呼び出し側互換のため残す（内部を decide_stream の集約で書き換えるのは可）。

### 3-2. thought 逐次抽出器（純粋コンポーネント・単体テスト必須）

生 JSON 断片を受け取り、トップレベル `"thought"` 文字列値の**累積デコード結果**を返す
インクリメンタル抽出器を新設する（例: `ThoughtStreamExtractor`。配置は agent 配下）。

- `{` 前後・`"thought"`・`:` 周辺の任意の空白・改行を許容する（実測で `{\n  "thought": "` 形式）。
- JSON 文字列エスケープを逐次デコードする: `\"` `\\` `\/` `\n`→空白 `\t`→空白 `\uXXXX`
  （サロゲートペア含む）。**チャンク境界がエスケープ途中でも壊れない**こと（未完エスケープは
  完成までバッファ）。
- 連続空白は 1 個に畳む（status は 1 行表示）。
- thought 値の閉じ引用符で抽出終了（以降の action / action_input は抽出対象外）。
- 表示上限: 累積 120 字（`_sanitize_thought` と同一上限）。超過後の断片は表示に反映しない。
- マーカーガード: 累積文字列に既存マーカー（`{` `}` バッククォート 3 連・`action_input`・
  `システムプロンプト`）が現れたら、その decide の partial 配信を**以後停止**する
  （最終 status は §3-4 の sanitize 結果に従う）。

### 3-3. `_decide` への統合（`backend/app/agent/graph.py`）

- `llm_client.decide` 呼び出しを decide_stream ＋抽出器に置き換える。生出力は全量蓄積し、
  完了後のパース・バリデーション・fallback・trace は**現行ロジックそのまま**。
- step の割当: 初回 decide（decision_count == 0）= `analyze`、2 周目以降 = `evaluate`。
- 初回 decide 開始時の静的 status（analyze「ご質問をじっくり読み解いています…」）は現状維持
  （prefill の間これが表示される）。**2 周目以降の decide 開始時に新規 status は出さない**（裁定 #4）。
- partial 配信: 抽出器の累積が伸びるたび
  `status {step, text: 累積 + "…", partial: true}` を送出。80〜150ms への間引きは可、
  300ms を超える保留は不可。
- 最終配信: パース完了後、`status {step, text: sanitize 済み thought, partial: false}` を送出。
  現行の「decision_count > 0 のときだけ事後に evaluate を送る」ブロックはこれに**置換**する
  （初回 decide の thought も表示されるようになる — 意図した改善）。バリデーションエラー・
  transport 失敗の fallback 時も同様に最終配信する（fallback thought が表示される）。
- ストリーミング途中の transport 失敗は既存 except 経路に合流（送出済み partial は次の status が
  上書きするまで画面に残ってよい）。

### 3-4. `_sanitize_thought` の変更

- 120 字超過: 先頭 120 字＋「…」へ**切り詰め**（従来の汎用文言への全置換をやめる）。
- 空文字・マーカー混入: 従来どおり汎用文言（STATUS_TEXTS["evaluate"]）へ置換。
- 切り詰め後の値は actions_log（decide プロンプトへ再投入）にも従来どおり載る（短くなる方向のみ）。

### 3-5. navigator（`backend/app/agent/navigator.py`）

- 内部ループの `llm_client.decide` も decide_stream ＋抽出器へ置き換える。
- `status_callback` を `(text: str, partial: bool)` に拡張し（呼び出し側 `_campus_navigator` の
  ラッパも同時更新）、partial は step=`analyze` で配信する。
- 既存の静的文言（「キャンパスマップで経路を調べています…」「キャンパスマップで候補を
  確認しています…」）は `partial: false` のまま存続。navigator では最終 thought の確定配信は不要
  （次の静的 status か結果が直後に上書きするため）。fast_path は不変。

### 3-6. mock エージェント（`backend/app/agent/mock.py`）

- GPU なし環境でフロントを開発・検証できるよう、mock も回答前に**partial: true の status を
  2〜3 発（伸長系列）**送出すること（SHOULD）。

### 3-7. 付随の小型最適化（P2・任意だが推奨）

`_decide` は 1 周で `_measure_context_usage` を 2 回呼び、evidence テキストと generate ベースの
/tokenize を計 6 回叩く。同一周回内で knowledge/web/history は不変なので、**2 回目は evidence・
ベースのトークン数を 1 回目から再利用し、decide プロンプト本文だけ再計測**する
（/tokenize 2 回分の削減。予算判定の数値・ロジックは不変であること）。

## 4. frontend 仕様

### 4-1. `stores/chat.js`

- status イベントの `partial`（欠落時 false）を `message.statusPartial` として保持。
- `message.statusRunId`（整数・初期 0）を新設。status 受信時、
  **「incoming.text（末尾「…」を除く）が現在の statusText（末尾「…」を除く）の拡張
  （startsWith）であり、かつ step が同一」でなければ +1** する。
  partial の伸長系列と「最後の partial → 確定 thought」は拡張に当たるため増えない。
  ツール status への切替・別 step への遷移は増える（＝フェード 1 回）。

### 4-2. `LoadingSpinnerV5.vue`

- `<Transition>` 内の `:key` を `displayText` から **`statusRunId`**（新 prop）へ変更。
  同一 runId 中の text 変化はキー不変＝フェードなしのその場書き換え（打鍵風の伸長表示）、
  runId が変わったときだけ従来の 250ms フェード。
- 視覚仕様の追加変更なし（シマー・色テーマ・reduced-motion は現状維持。partial 中の
  末尾「…」は backend が text に含めて送る）。
- `ChatView.vue` は `statusRunId` を渡す配線のみ。スクロール watch（statusText 依存）は
  現状のままで可（token ストリーミングと同頻度）。

## 5. 検収基準

1. **単体（pytest）**: 抽出器 — チャンク境界を全位置で割ったケース・`\uXXXX`／サロゲートペア・
   マーカーガード・120 字上限・空白畳み込み。graph — 初回/2 周目以降の step 割当、partial 系列＋
   確定配信、バリデーションエラー/transport 失敗時の最終配信、`partial:false` が全既存 status に
   付くこと。sanitize — 切り詰め/置換の分岐。client — decide_stream のリクエスト形。
2. **frontend（Vitest）**: store の runId 増加規則（伸長で不変・切替で +1・step 変化で +1）、
   partial 透過。コンポーネントのキー変更。
3. **実 LLM E2E（必須・31B PP=2 現物）**: 探索が複数周回する質問と経路質問（navigator 経由）の
   2 系統以上で SSE を採取し、(a) decide 中に text が単調伸長する partial 系列が届く
   (b) 確定 thought が partial:false で届く (c) partial にマーカー・JSON 断片が漏れない
   (d) 旧イベント語彙・順序の互換が保たれる、を確認。初回 partial 到達は質問送信から
   2.5 秒以内を目安（非規範・warm 時）。
4. **回帰**: pytest / Vitest / build 全緑。`docs/EVAL_QUESTIONS.md` 系の応答品質に影響しないこと
   （プロンプト・判断ロジックは不変のため、thought 切り詰め以外の挙動差はない想定）。

## 6. スコープ外

- decide 反復回数そのものの削減（探索効率チューニングは別 FR）。
- generate 開始時の prefill 待ち演出の追加。
- 回転メッセージ等の非実況演出（不採用・裁定 #2）。
