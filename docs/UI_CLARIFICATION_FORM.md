# 確認質問（ask_user）専用回答フォーム — FR-39

- 版: v1.2（2026-07-18, Fable — 実装検収合格。§2 に API 境界の kind 正規化（実装時 Fable 裁定）を追記、
  §11 に検収記録を追加。実装: Codex／意匠: GPT-5.6 Sol／レビュー・検収: Fable）
- v1.1（2026-07-18, Fable — §6 に GPT-5.6 Sol デザインリードの確定意匠を転記。実装可能状態）
- v1.0（2026-07-18, Fable 起草 — 機能フレーム §1〜5・§7〜10 確定）
- 発端: 利用者指示（2026-07-18）「ask_user ツールでは、通常の入力フォームを使わずに、専用の入力フォームを用意する。
  デザインリードは GPT-5.6 Sol。AI が開発したようなデザインは禁止で、今の UI にふさわしい、かつおしゃれな UI にする」
- 関連: `docs/MAP_CARD.md` §11（ask_origin の composer ロック — 本 FR が踏襲する elicitation 文法の先例）、
  `docs/AGENT_REACT.md`（ask_user ツールの定義）、`docs/ARCHITECTURE.md` §3（SSE 契約）

## 1. 背景と方針

- エージェントの `ask_user`（確認質問・clarification）は現在、質問文が通常の assistant メッセージとして
  ストリーミングされ、来場者は**通常の composer** で回答している。フロントは clarification を特別扱いしておらず、
  「これはあなたへの質問です・ここに答えてください」という手がかりがない。
- 本 FR で、clarification 受信時に**質問メッセージ直下へ専用の回答フォーム（インラインカード）**を出し、
  その間**通常 composer はロック**する。ask_origin（FR-27, MAP_CARD.md §11）と同じ elicitation 文法
  （インラインの操作点＋composer ロック＋解除 3 条件）に揃え、UI の学習コストを 1 つにする。
- **エージェント側の契約は不変**: ask_user ツール入力は `{question: string}` のまま。回答は通常の user
  メッセージとして送る（`origin_node` のような専用リクエストフィールドは設けない）。既存の履歴サニタイズ
  （`（確認質問）` プレフィックス・`clarification_blocked`）がそのまま効く。
  FR-37/38 で安定させた decide プロンプトには一切手を入れない。
- 選択肢チップ（ask_user に options を持たせる案）は**本 FR のスコープ外**（将来拡張として §10 に記録）。

## 2. 契約変更（SSE — additive のみ）

- `done` イベントに optional フィールド `kind` を追加する:

  ```
  event: done
  data: {"thread_id": "...", "message_id": "...", "sources": [...],
         "kind": "clarification" | null}   // FR-39。省略/null = 通常回答
  ```

- backend: `DonePayload` に `kind: Literal["clarification"] | None = None` を追加し、
  `graph.py` の done 送出（`terminal_kind == "ask_user"` 判定の直後）で
  `kind="clarification"` を設定する。**それ以外の変更はなし**
  （`_ask_user` ノード・metadata 永続化・chat.py の履歴サニタイズは現行のまま）。
- `terminal_kind == "ask_origin"`（現在地未定の経路質問）は従来どおり `map.mode: "ask_origin"` で
  合図するため `kind` は付けない（null）。mock（`MockCampusAgent`）の通常回答も null（既定値）で不変。
- 後方互換: フィールド追加のみ。`kind` を知らないクライアントは無視して従来挙動。
- **API 境界の kind 正規化（実装時 Fable 裁定・採用）**: `chat.py` の done 処理で
  ①エージェント実装が `kind` を省略した場合は metadata（`kind: "clarification"`）から導出して
  `"clarification" | null` を必ず埋める ②`kind: "clarification"` なのに metadata 未提供なら
  metadata を合成して DB へ保存する。SSE の kind と DB metadata（次ターンの履歴サニタイズ・
  `clarification_blocked` の根拠）が実装によらず乖離しない単一の強制点。
  `_sanitize_agent_history` 本体は不変。
- FR-27 の「origin_node 省略時 SSE バイト同一」回帰テストは、done に `"kind":null` を含む形へ
  改名・更新（`test_omitting_origin_node_keeps_done_kind_null_in_sse_bytes`）。バイト同一の
  ピン留め自体は kind 込みで維持している（MAP_CARD.md §11-5-12 の additive 上書き）。

## 3. store の状態機械（`frontend/src/stores/chat.js`）

ask_origin の `finalMapInteractive → mapInteractive` と完全に同型で実装する:

- `applyAssistantEvent` の `done` 分岐: `message.finalClarification = event.data.kind === 'clarification'`。
- `finalizeAssistantMessage`（FR-25 の文字送り完了時）: `message.clarificationActive =
  Boolean(message.finalClarification)` を設定し `finalClarification` を削除。
  → **フォームは質問文の文字送りが終わってから現れる**（map card と同じタイミング規律）。
- `error` イベント分岐・`sendMessage` の catch 節のクリーンアップに
  `finalClarification` / `clarificationActive` の削除を追加。
- getter `isClarificationPending`: `messages.some((m) => m.clarificationActive)`。
- `sendMessage` 冒頭ガードに `(this.isClarificationPending && !options.clarificationCardClientId)` を追加
  （ask_origin ガードと並列。専用フォーム経由以外の送信をブロック）。
- 送信開始時の全カード非活性化（現行 `deactivateMapCards()` 呼び出し箇所）で
  `clarificationActive` / `finalClarification` も全メッセージからクリアする。
- 新 action `submitClarificationAnswer(message, text)`:
  1. ガード: `isSending`・`!message.clarificationActive`・空文字 → no-op。
  2. `message.clarificationActive = false` にしてから
     `sendMessage(text, { clarificationCardClientId: message.clientId })`。
  3. 送信失敗時（`sendMessage` の catch 節）: `lastFailedRequest` に `clarificationCardClientId` を保持し、
     該当メッセージの `clarificationActive` を **true に戻す**（ask_origin の失敗時再活性と同型。
     ロック維持・フォームから再送できる）。`retryLast` も `clarificationCardClientId` を引き継ぐ。
- 新 action `cancelClarification(message)`: 活性中のみ。`clarificationActive = false`（送信なし）。
  このカードに紐づく失敗状態（`lastFailedRequest.clarificationCardClientId === message.clientId`）が
  あればエラーバナーごとクリアする（`cancelMapOrigin` と同型）。
- `openThread`（履歴復元）: 復元メッセージは**常に非活性**（`clarificationActive` を立てない）。
  MAP_CARD.md §7-2 の先例踏襲。リロード後は通常 composer で回答すればよい（backend は従来どおり処理できる）。

## 4. フォームの挙動仕様（`frontend/src/components/ClarificationCard.vue` 新設）

- 置き場所: assistant メッセージ描画内、`MarkdownRenderer`（質問文）の直後・MapCard スロットと同列。
  `v-if="message.clarificationActive"` — **活性中のみ存在**する（回答済み・キャンセル済み・履歴復元では
  描画しない。質問文自体は assistant メッセージとして残るため、解決後は Q→A が通常の会話として読める）。
- 構成要素:
  1. 見出し（このフォームが「あなたへの質問への回答欄」であることを一言で示す。文言は §6）
  2. 複数行テキスト入力（auto-grow。通常 composer と同じ入力規律 —
     Enter 送信 / Shift+Enter 改行 / `event.isComposing` 中の Enter は無視）
  3. 送信ボタン（空文字・`isSending` 中は disabled。タップターゲット 44px 以上）
  4. 控えめなキャンセル「この質問には答えずに続ける」（§6 で文言確定。タップでフォームを閉じ
     composer ロック解除・送信はしない）
- 自動フォーカスは**しない**（モバイルでのキーボード暴発防止を優先。来場者はスマホ主体 — NFR-3）。
- 活性化時にフォームが可視域へ入ること（既存の追従スクロール準拠。最新メッセージ末尾に出るため
  通常は自動で見えるが、Playwright で実証すること）。
- 送信すると回答は**通常の user バブル**として表示される（専用チップ等は作らない）。
- a11y: フォームに `aria-label`（例:「確認質問への回答」）・入力に `<label>`（視覚的には §6 の意匠に従う）・
  44px タップターゲット・フォーカスリングは既存の focus-visible 規律に従う。Esc キーへの割り当てはしない
  （ダイアログの Esc と競合させない。キャンセルはボタンのみ）。
- `prefers-reduced-motion`: 出現/退出のモーションは無効化（即時表示/非表示）。

## 5. 通常 composer のロック（`ChatView.vue`）

MAP_CARD.md §11-1 の origin ロックと同じ視覚言語・同じ配線で行う:

- `isClarificationPending` 中: textarea / 送信ボタン / Enter / `applySuggestion` を無効化し、
  composer-shell に locked 状態のスタイル（§6。`composer-shell--origin-locked` と同系）を適用。
  placeholder は「上のフォームからお答えください」（§6 で最終文言確定）。
- 解除条件は次の 3 つのみ（§11-1 と同型）:
  1. フォームから回答を送信し成功（失敗時はフォーム再活性・ロック維持）
  2. フォームのキャンセル
  3. スレッド切替・新規チャット・リロード（履歴復元は常に非活性 = ロックなし）
- `send()` / `onEnter()` に `isClarificationPending` の早期 return を追加（store ガードの二重防御）。

## 6. 意匠（GPT-5.6 Sol デザインリード確定 — 2026-07-18・v1.1 転記）

### 6-0. 制約（Sol への依頼に含めた・検収でも確認する）

- **Campus Signal デザインシステムに完全準拠**: 既存トークンのみ使用
  （ink/edge/fill/brand カラー・`--radius-*`・`--shadow-*`・`--motion-*`・`--ease-*`。
  新規の色・角丸・影・イージング値の発明は不可）。外部アセット・外部フォント禁止。
- **「AI が作ったような」デザインの禁止**（利用者指示）: 紫青グラデ・グラスモーフィズム盛り・
  絵文字見出し・過剰な角丸カード・意味のない装飾を排し、既存 UI（composer shell・
  current-location-chip・MapCard・dialog-panel）と並べて一つの製品に見えること。
- モバイル縦画面ファースト（NFR-3）・44px タップターゲット・コントラスト AA。

### 6-1. フォームの解剖（Sol 確定）

- 位置: assistant 質問文の直下、`MarkdownRenderer` の次。通常の会話バブルではなく、
  同じ中央カラム内のインライン操作カードとして出す。
- 外形: `w-full rounded-ui-lg border border-edge-strong bg-ink-raised`。影は `--shadow-hairline` と
  `--shadow-raised` を重ねる。グラスモーフィズム・グラデーション・発光は使わない。
- 誘目: 左端に `brand.signal` の細い **signal rail** を置き、見出し横に小さな `brand.signal` ドットを
  置く。装飾用 SVG アイコンは使わない。MapCard の live dot と同じ「問いかけ中」の語彙に接続する。
- 余白: モバイル基準で `p-4`、`sm:p-5`。内部は `gap-3`。カード直上は既存 `space-y-4` に任せ、
  追加の大きな余白を作らない。
- 見出し: `text-sm font-semibold leading-6 text-ink-paper`。本文より少しだけ強く、ヒーロー的な
  大きさにはしない。
- 入力面: `rounded-ui border border-edge bg-ink-surface`。textarea は `text-base leading-7
  text-ink-paper`、placeholder は `--color-text-dim`。auto-grow の上限は通常 composer と同じ `164px`。
- 操作列: モバイルでは送信・キャンセルの縦積み。`sm` 以上はキャンセル左・送信右の横並び。
  どちらも `min-h-11` 以上。
- 送信ボタン: 有効時は `bg-ink-paper` + `--color-paper-ink`。ラベル「回答する」（§6-4）に、
  既存 composer 流儀の上向き矢印線画 SVG（`fill="none"`・`stroke="currentColor"`・丸端丸結合）を
  添える（Fable 裁定: 6-1 と 6-5 の整合読み — ラベル主体＋小さな線画アイコン併記）。
- キャンセル: MapCard と同じ控えめなテキストボタン。underline を使い、面を強く持たせない。

### 6-2. 状態定義（Sol 確定）

- 出現: 質問文の文字送り完了後に `<Transition name="clarification-card">` で表示。enter は
  `opacity: 0`・`translate3d(0, 0.75rem, 0)`・`scale(0.985)` から開始し、
  `opacity var(--motion-base) ease-out`・`transform var(--motion-base) var(--ease-expressive)` で静定。
- アイドル: 外枠 `edge.strong`・背景 `ink.raised`・入力面 `ink.surface`。signal rail とドットだけを
  `brand.signal` にする。
- 入力フォーカス: 入力ラッパーを `border-brand-soft` にし、`:has(textarea:focus-visible)` で
  `outline: var(--composer-focus-ring-width) solid var(--color-signal-soft); outline-offset: 3px;`。
  composer の Aurora 色サイクルは使わない。
- 送信可: ボタンを `bg-ink-paper` に切替。hover は `duration-base ease-expressive` で軽く
  `-translate-y-0.5`、active は `scale-[0.94]`。reduced-motion では移動しない。
- 送信中: `aria-busy="true"`。textarea とボタンを disabled、ボタン文言は「送信中…」。
  カード全体へのローディング演出・追加発光は足さない。
- 送信失敗→再活性: フォームは通常の活性状態へ戻す。赤い枠は付けず、失敗表示は既存エラーバナーに
  一本化する。再活性時の自動フォーカスはしない。
- キャンセル hover/active: hover は `bg-fill-hover` と `--color-text`、active は `scale-[0.97]`。
  `duration-fast ease-standard`。
- 退出: 回答送信開始またはキャンセル時、leave は `opacity var(--motion-fast) ease-out`・
  `transform var(--motion-fast) var(--ease-standard)` で `opacity: 0`・`translate3d(0, -0.25rem, 0)` へ。
- `prefers-reduced-motion`: 出現・退出・hover/active の transform を無効化し、即時表示/非表示。
  focus outline は残す。

### 6-3. locked composer（Sol 確定）

- ask_origin と同じ elicitation のため、視覚は `composer-shell--origin-locked` と**同一**にする。
  差別化は placeholder 文言のみ。
- 実装: `chat.isOriginSelectionPending || chat.isClarificationPending` で同じ locked class を付ける
  （class 名を `composer-shell--elicitation-locked` 等へ整理してもよいが、宣言内容は既存
  `composer-shell--origin-locked` と同一にする — どちらの方式でも可・完了報告に選択を記す）。
- 追加の opacity 低下・overlay は不要。textarea / 送信ボタン / suggestion は既存 disabled 表現に従う。
- placeholder 分岐: origin 判定を先に評価し既存文言を退行させない（両立は実運用上起きない）。

### 6-4. マイクロコピー（Sol 確定・最終文言）

| 箇所 | 文言 |
|---|---|
| フォーム見出し | こちらにお答えください |
| 入力 placeholder | わかる範囲で入力してください |
| 送信ボタン表示 | 回答する（送信中は「送信中…」） |
| 送信ボタン aria-label | 確認質問への回答を送信 |
| キャンセル | この質問には答えずに続ける |
| フォーム aria-label | 確認質問への回答 |
| locked composer placeholder | 上のフォームからお答えください |

### 6-5. 実装指定（Sol 確定 — スタイル骨子）

- `ClarificationCard.vue` root: `clarification-card relative w-full overflow-hidden rounded-ui-lg
  border border-edge-strong bg-ink-raised p-4 sm:p-5`。影と signal rail は scoped CSS で既存トークン指定。
- header: `flex items-center gap-2.5`、dot は `bg-brand-signal`、見出しは `<label>` と兼用して
  textarea に `aria-labelledby` で接続。
- input wrapper: `mt-3 rounded-ui border border-edge bg-ink-surface px-3 py-2.5 transition
  duration-base ease-standard focus-within:border-brand-soft`。
- textarea: `min-h-24 max-h-[164px] w-full resize-none bg-transparent text-base leading-7
  text-ink-paper outline-none placeholder:text-[var(--color-text-dim)] disabled:cursor-not-allowed`。
- actions: `mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between`。
- primary button: `min-h-11 min-w-28 rounded-ui-sm px-4 py-2 text-sm font-semibold transition
  duration-base ease-expressive enabled:bg-ink-paper enabled:text-[var(--color-paper-ink)]
  disabled:cursor-not-allowed disabled:bg-fill-hover disabled:text-[var(--color-text-dim)]`。
- cancel button: `min-h-11 rounded-ui-sm px-3 py-2 text-sm text-[var(--color-text-dim)] underline
  underline-offset-4 transition duration-fast ease-standard hover:bg-fill-hover
  hover:text-[var(--color-text)]`。
- ChatView では `MarkdownRenderer` の直後に `Transition name="clarification-card"` で差し込み、
  MapCard と同じ `space-y-4` の流れに置く。

## 7. 検証用モック拡張（`backend/app/agent/mock.py`）

GPU なしで UI を E2E 検証できるよう、mock に clarification 経路を足す（FR-36 の検証手法の踏襲）:

- 質問文字列が「確認テスト」を含む場合: 短い status 2 件 → 確認質問文（例:
  「どの学科についてお調べしましょうか？ 気になっている学科名を教えてください。」）を token 配信 →
  `done` に `kind: "clarification"`・sources は空。
- それ以外は現行どおり（`kind` は既定 null）。
- あくまで開発検証用。本番エージェント経路には影響しない。

## 8. テスト要件

- backend（pytest・既存 164 に追加）:
  - ask_user 終端の done payload に `kind: "clarification"` が載る／通常 finish・ask_origin 終端では
    `kind` が null。
  - mock のトリガー経路（「確認テスト」→ kind 付き done、通常質問 → null）。
- frontend（Vitest・既存 94 に追加）:
  - store: done(kind) → `finalClarification` → finalize で `clarificationActive`／
    `isClarificationPending` getter／通常 `sendMessage` ブロック／`submitClarificationAnswer` 成功で
    非活性＋送信／失敗で再活性＋`lastFailedRequest` 保持／`retryLast` 引き継ぎ／
    `cancelClarification` の解除と失敗状態クリア／`openThread` 復元は常に非活性／
    error イベントで `finalClarification` がクリーンアップされる。
  - ChatView: 活性中に composer が disabled・placeholder 切替・フォーム描画／Enter・isComposing・
    Shift+Enter の入力規律／キャンセルでロック解除。
- Playwright（mock 起動・手動検収）: 「確認テスト」送信 → 文字送り完了後にフォーム出現 →
  composer ロック確認 → フォームから回答 → 通常回答が返る、の一連。キャンセル経路・リロード経路も確認。

## 9. 検収基準

1. 「確認テスト」で専用フォームが質問文の文字送り完了後に出現し、composer がロックされる。
2. フォームから送信した回答が通常の user バブルとして表示され、会話が継続する。
3. キャンセルでフォームが閉じ、composer が即時使用可能になる。
4. 送信失敗でフォームが再活性し、そのまま再送できる。エラーバナーの再試行からも同経路で成功する。
5. リロード・スレッド切替でロックが残留しない（復元は常に非活性）。
6. 意匠が §6 の Sol 確定仕様どおりで、既存 UI と並べて違和感がない（Fable 目視 + スクリーンショット検収）。
7. pytest / Vitest / `npm run build` 全緑。既存テストの回帰なし。
8. reduced-motion でモーションが無効化される。

## 10. 将来拡張（スコープ外メモ）

- ask_user ツール入力への `options: string[]` 追加（タップ選択チップ）。decide プロンプト変更を伴うため、
  FR-37/38 の安定を崩さないよう別 FR で判断する。
- デスクトップ（pointer: fine）限定の自動フォーカス。

## 11. 検収記録（2026-07-18, Fable）

- 自動テスト（Fable 手元実行）: pytest **165 passed**（+1 mock トリガー・既存 assert の additive 更新は
  §2/§8 の認可範囲内）／Vitest **104 passed**（+10）／`npm run build` 成功。
- Playwright 実機（mock スタック: backend 8081 `AGENT_MODE=mock`・frontend 5174、390×844 / 1280×900）:
  1. 「確認テスト」→ 文字送り完了後にフォーム出現・composer ロック
     （textarea disabled・送信 disabled・`composer-shell--origin-locked`・`aria-disabled`・
     placeholder「上のフォームからお答えください」を機械確認）— §9-1 合格。
  2. フォームから回答送信 → 通常の user バブル表示・通常回答ストリーム・フォーム消滅・
     composer 即時解除 — §9-2 合格。
  3. キャンセル → フォーム消滅・composer 解除＋フォーカス復帰 — §9-3 合格。
  4. フォーム活性中にリロード → 復元は非活性・ロック残留なし — §9-5 合格。
  5. DB 永続化: clarification メッセージの `metadata_json = {"kind":"clarification"}` を実 DB で確認
     （次ターンの履歴サニタイズ・`clarification_blocked` の根拠が mock 経路でも成立）。
  6. 意匠: §6 の Sol 確定仕様どおり（signal rail 3px・ドット見出し・ink-raised 面・下線キャンセル・
     モバイル縦積み/デスクトップ横並び）を 390/1280 スクリーンショットで確認 — §9-6 合格。
  ※ §9-4（送信失敗→再活性・再送）は Vitest（store 2 件）でカバー。reduced-motion（§9-8）は
  実装 CSS（transition none・transform 無効）のコードレビューで確認。
- 実装時の採用裁定 2 点（いずれもレビューで採用・§2 追記済み）:
  ①API 境界の kind 正規化（chat.py）②失敗再活性時の入力復元 `clarificationDraft`
  （§9-4「そのまま再送できる」に資する。成功時は通常 user バブルのみで UI 残留なし）。
