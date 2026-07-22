# 確認質問（ask_user）専用回答フォーム — FR-39

- 版: v2.2（2026-07-19, Fable — FR-40 実装検収合格。§11 に R2 検収記録を追記。実装: Codex／
  意匠: GPT-5.6 Sol（R2）／レビュー・検収: Fable）
- v2.1（2026-07-18, Fable — §6-2 に Sol R2 確定意匠「inline handoff composer」を転記。実装可能状態）
- v2.0（2026-07-18, Fable — **FR-40 是正 R2**。利用者評価「デザインが全然だめ」により §6 R1 意匠を
  廃止し Sol が全面再設計（§6 を R2 へ差し替え）。あわせて利用者指示「ask_user 受付中は出力待ち演出を
  止めない」を §5-2 探索継続演出として新設 — LoadingSpinnerV5 に `elicit` モード追加・
  status step `clarify` を additive 追加）
- v1.2（2026-07-18, Fable — 実装検収合格（R1）。§2 に API 境界の kind 正規化（実装時 Fable 裁定）を追記、
  §11 に検収記録を追加。実装: Codex／意匠: GPT-5.6 Sol／レビュー・検収: Fable）
- v1.1（2026-07-18, Fable — §6 に GPT-5.6 Sol デザインリードの R1 意匠を転記）
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

## 5-2. 探索継続演出 — ask_user 中はクルクルを止めない（FR-40・利用者指示）

> 利用者指示原文: 「ask_user ツールで聞いている間は、アイコンのクルクルは止めないでください
> （回答が 1 ターン完了したような UX になってしまうため。あくまで回答を生成するための流れの一部なので、
> 出力待ちの演出は止めないでください。）」

確認質問ターンでは Aurora Ring（LoadingSpinnerV5）を **settled にしない**。elicitation が解消するまで
リングは回り続け、「まだ回答の途中」を伝える。

### 5-2-1. backend（additive のみ）

- `_ask_user` は token 配信の**直前**に `status` イベント `{step: "clarify", text: <§6 R2 の確定文言>}` を
  1 回送出する（現行の `step: "generate"` 送出を置換）。`StatusPayload.step` の Literal に `clarify` を追加。
- mock の「確認テスト」経路も同じく status(clarify) を token 前に送出する（§7 改訂）。
- これ以外の backend 変更はなし（done の `kind`・metadata は R1 のまま）。

### 5-2-2. LoadingSpinnerV5 — 第 3 モード `elicit`

- mode `elicit` を追加: **リング（外周アーク・内周カウンター回転）とアイコンの kurun 回転は
  pending と同一のまま継続**し、本文スロットは settled と同様に表示する。ジオメトリは settled と同じ
  （stage 24px・flex-start — 本文の読みやすさを優先し、リングの生存だけを残す）。
  pending の実況テキスト行は elicit では表示しない（本文=質問文が実況の代わり）。
- **不可侵の維持**: リング SVG 構造・アニメーション値（2s/1.5s/3s/4s）・STEP_THEMES・shimmer・
  pending→settled morph のタイミングは一切変更しない。elicit は既存アニメーションの「継続表示」のみで
  構成する（新規アニメーション値の発明不可）。
- 遷移: pending→elicit は既存の stage 縮小（300ms）どおり・ただしリングの fade を伴わない。
  elicit→settled は残り半分（リング fade 300ms）のみ。reduced-motion では既存規則
  （静止アーク・transition 抑制）に従い、elicit 中は静止アークが出続ける。

### 5-2-3. store / ChatView の状態機械

- `applyAssistantEvent` の status 分岐: `step === "clarify"` を受けたら
  `message.clarificationExpected = true`（実況テキスト処理は既存どおり — pending 中は clarify の
  文言がそのまま実況表示される）。
- ChatView の mode 決定: `pending ? 'pending' : (message.clarificationExpected ? 'elicit' : 'settled')`。
  → 最初の token で pending が落ちても、expected が立っていれば **一度も settle せず** elicit へ。
- `clarificationExpected` の解除（= elicit → settled）:
  1. フォーム送信成功（`submitClarificationAnswer` 経由の send 開始時の全非活性化で落とす —
     直後に次ターンの pending スピナーが下に現れ、「作業中」の合図が引き継がれる）
  2. キャンセル（`cancelClarification`）
  3. `error` イベント・`sendMessage` catch のクリーンアップ
  4. done が `kind: "clarification"` **でない**のに expected が立っている場合（安全弁: finalize 時に落とす）
  5. `openThread` 復元では立てない（復元は常に settled — §3 の既定どおり）
- 送信失敗でフォームを再活性する際は `clarificationExpected` も **true に戻す**（elicitation 継続中のため。
  リングは回り続ける）。
- 通常ターン（clarify を受けない）は expected が立たず、挙動は従来と完全同一。

## 6. 意匠 R2（GPT-5.6 Sol デザインリード — FR-40 再設計。R1 は利用者評価により廃止）

### 6-0. 制約（Sol への依頼に含めた・検収でも確認する）

- **Campus Signal デザインシステムに完全準拠**: 既存トークンのみ使用
  （ink/edge/fill/brand カラー・`--radius-*`・`--shadow-*`・`--motion-*`・`--ease-*`。
  新規の色・角丸・影・イージング値の発明は不可）。外部アセット・外部フォント禁止。
- **「AI が作ったような」デザインの禁止**（利用者指示）: 紫青グラデ・グラスモーフィズム盛り・
  絵文字見出し・過剰な角丸カード・意味のない装飾を排し、既存 UI（composer shell・
  current-location-chip・MapCard・dialog-panel）と並べて一つの製品に見えること。
- モバイル縦画面ファースト（NFR-3）・44px タップターゲット・コントラスト AA。

### 6-1. R1 意匠の廃止記録

- R1（v1.1 転記・fc9916a で実装）は 2026-07-18 利用者評価「デザインが全然だめ」により**廃止**。
  全文は git 履歴（fc9916a 時点の本ファイル）を参照。
- Fable の敗因分析（R2 ブリーフに使用）: カード内カード（外枠 > 入力箱 > ボタン列）の入れ子で
  「管理画面のアンケートフォーム」の趣になった・空の大型 textarea（min-h-24）が威圧的・
  下線テキストのキャンセルが古風・会話の流れ（静かなドキュメント面）とも composer ピル
  （このアプリの入力言語）とも接続しない異物スラブになった。

### 6-2. R2 確定意匠（GPT-5.6 Sol 確定 — 2026-07-18 転記）

#### 6-2-1. 設計コンセプト

R2 は「回答カード」ではなく、質問文の直下に一時的に差し込まれる **inline handoff composer** とする。  
R1 の外枠カード・大型 textarea・下線キャンセルは廃止し、画面下 composer のピル形状、右端の円形送信、控えめなロック文法をそのまま会話内へ移植する。  
Aurora Ring は elicit 中も質問文の左で回り続けるため、フォームは「完了した回答に付いた入力欄」ではなく「進行中の案内から一瞬だけマイクを渡された場所」に見せる。  
入力は「機械工学科」「はい」など 1〜2 語を主ケースとし、最小 1 行から始める。空の大面積は作らない。

#### 6-2-2. status step `clarify` の実況文言

```text
案内に必要なことを少しだけ確認します。
```

#### 6-2-3. 回答導線の解剖

- 配置: `LoadingSpinnerV5` の body slot 内で、`MarkdownRenderer` の直後に置く。左端は assistant 本文と揃え、Aurora Ring の下へ回り込ませない。リングは 24px elicit ジオメトリのまま本文左で回転し、フォームはその右の本文カラム内にだけ存在する。
- 外形: root はカード化しない。`bg`・`border`・`shadow` を root に持たせず、`w-full sm:max-w-xl` の軽い form ラッパーにする。デスクトップでも横幅を広げすぎず、質問の補助操作に見せる。
- 見出し相当: 入力ピルの上に小さな cue row を置く。`brand-signal` の小ドット + `ひとことだけ教えてください`。文字は `var(--color-text-muted)`、本文より弱く、操作点であることだけ示す。
- 入力本体: 画面下 composer と同一語彙の shell。`composer-shell flex items-end gap-2 rounded-[1.6rem] p-2` を再利用し、`border-edge-strong`・`bg-ink-raised`・`shadow-soft` は既存 composer と揃える。
- textarea: `rows="1"`、`min-h-11`、`max-h-[164px]`、`resize-none`、`px-3 py-2.5`、`text-base leading-6`。初期高さは 44px に留め、入力が長い時だけ auto-grow。
- 送信: 右端は composer と同じ `h-11 w-11 rounded-full` の円形 icon button。空文字では disabled、送信可で `bg-ink-paper text-[var(--color-paper-ink)]`。表示テキストは置かず、矢印 icon + aria-label にする。
- キャンセル: 入力ピル下に ghost chip として置く。下線リンク禁止。`inline-flex min-h-11 items-center rounded-full px-3`、通常は `var(--color-text-muted)`、hover/focus で `bg-fill-hover` と `var(--color-text)`。

#### 6-2-4. 全状態

- 出現: 質問文の文字送り完了後にだけ mount。`opacity` と `translate-y-2` で、`var(--motion-base)` / `var(--ease-expressive)`。自動フォーカスなし。
- アイドル: cue row + 空の 1 行 composer。送信ボタン disabled。placeholder は短答前提の例を出す。
- フォーカス: 既存 composer と同じ focus ring。`--composer-focus-ring-width`、`var(--color-signal-soft)`、必要なら既存 `composer_focus_aurora` のみ使用。新規 glow は作らない。
- 送信可: trim 後に円形送信が active。hover は既存 composer と同じ `hover:-translate-y-0.5`、active は `active:scale-[0.94]`。
- 送信中: submit 直後に `aria-busy="true"`、入力と送信を disabled。フォームは `var(--motion-fast)` / `var(--ease-standard)` で退出し、下の次ターン pending に作業中の合図を渡す。
- 失敗→再活性: draft を保持して同じ位置に再 mount。見た目は通常 idle/sendable に戻し、失敗表示は既存の `chat.error` バナーに任せる。新規 error 色は作らない。
- キャンセル: ghost chip 押下でフォームを閉じ、`clarificationExpected` を落として ring は §5-2 の elicit→settled fade に移る。回答は送らない。
- 退出: 回答送信またはキャンセルで `opacity` + `translate-y-1`、`var(--motion-fast)` / `var(--ease-standard)`。scale は使わず、カードが畳まれる印象を避ける。
- reduced-motion: form transition / hover transform / focus animation は無効。表示・非表示は即時。Ring は §5-2 の reduced-motion 規則に従う。

#### 6-2-5. キャンセル導線

文言は `答えずに続ける`。  
これはリンクではなく副操作 chip として扱う。入力ピルの下、本文カラム左寄せに置き、通常時は目立たせないが 44px タップターゲットを確保する。hover/focus で `bg-fill-hover` を出し、押せることだけを静かに示す。

#### 6-2-6. locked composer

通常 composer は ask_origin と同じ `composer-shell--origin-locked` を使う。新規 locked class は作らない。  
placeholder は次に差し替える:

```text
質問の下の回答欄でお答えください
```

textarea・送信ボタン・Enter・suggestion-card は従来どおり無効化。解除条件は §5 の 3 条件のみ。

#### 6-2-7. マイクロコピー一式

| 用途 | 文言 |
| --- | --- |
| status `clarify` | 案内に必要なことを少しだけ確認します。 |
| 見出し相当 | ひとことだけ教えてください |
| placeholder | 例：機械工学科、はい |
| 送信 aria-label | 確認質問への回答を送信 |
| 送信中 aria-label | 回答を送信中 |
| キャンセル | 答えずに続ける |
| locked composer placeholder | 質問の下の回答欄でお答えください |

#### 6-2-8. 実装指定

ClarificationCard.vue は既存名のまま、見た目は card ではなく inline composer として組む。

```vue
<form
  class="clarification-card w-full sm:max-w-xl"
  aria-label="確認質問への回答"
  :aria-busy="isSending"
>
  <div class="mb-2 flex items-center gap-2 px-1">
    <span class="h-1.5 w-1.5 rounded-full bg-brand-signal" aria-hidden="true"></span>
    <label class="text-sm font-medium leading-6 text-[var(--color-text-muted)]">
      ひとことだけ教えてください
    </label>
  </div>

  <div class="clarification-card__composer composer-shell flex items-end gap-2 rounded-[1.6rem] p-2">
    <textarea
      rows="1"
      class="max-h-[164px] min-h-11 flex-1 resize-none bg-transparent px-3 py-2.5 text-base leading-6 text-[var(--color-text)] outline-none placeholder:text-[var(--color-text-dim)] focus-visible:outline-none"
      placeholder="例：機械工学科、はい"
    />
    <button
      type="submit"
      class="grid h-11 w-11 shrink-0 place-items-center rounded-full transition duration-base ease-expressive enabled:bg-ink-paper enabled:text-[var(--color-paper-ink)] enabled:hover:-translate-y-0.5 enabled:active:scale-[0.94] disabled:cursor-not-allowed disabled:bg-fill-hover disabled:text-[var(--color-text-dim)] motion-reduce:transform-none motion-reduce:transition-none"
      aria-label="確認質問への回答を送信"
    />
  </div>

  <button
    type="button"
    class="mt-1 inline-flex min-h-11 items-center rounded-full px-3 text-sm text-[var(--color-text-muted)] transition duration-fast ease-standard hover:bg-fill-hover hover:text-[var(--color-text)] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-55 motion-reduce:transform-none motion-reduce:transition-none"
  >
    答えずに続ける
  </button>
</form>
```

CSS は transition だけ追加する。色・角丸・影・duration・easing は上記既存 token / 既存 composer class のみを使い、R1 の `rounded-ui-lg border bg-ink-raised shadow` root、`min-h-24` textarea、左 rail、下線キャンセルは削除する。

#### 6-2-9. Fable 整合注記（転記時）

- cue row の `<label>` は textarea へ `for`/`aria-labelledby` で必ず関連付ける（§4 の a11y 要件維持）。
- 送信ボタンの中身はメイン composer と同一の上向き矢印線画 SVG（`h-5 w-5`・stroke currentColor）。
- 失敗→再活性の draft 保持は R1 の `clarificationDraft` 機構を継続使用。
- Enter 送信 / Shift+Enter 改行 / `isComposing` 無視・自動フォーカスなし等の入力規律は §4 のまま
  （R2 は見た目の再設計であり機能フレームは不変）。
- インライン `composer-shell` class 再利用は、画面下 composer と視覚同一性を保証する狙い。
  streaming/origin-locked 等の modifier は付けない素の shell として使う（focus ring は既存
  `:has(textarea:focus-visible)` 規則がそのまま効く）。


## 7. 検証用モック拡張（`backend/app/agent/mock.py`）

GPU なしで UI を E2E 検証できるよう、mock に clarification 経路を足す（FR-36 の検証手法の踏襲）:

- 質問文字列が「確認テスト」を含む場合: 短い status → **status(step: "clarify", text: §6-2-2 の文言)** →
  確認質問文（例:「どの学科についてお調べしましょうか？ 気になっている学科名を教えてください。」）を
  token 配信 → `done` に `kind: "clarification"`・sources は空（FR-40 改訂: clarify status は token 直前）。
- それ以外は現行どおり（`kind` は既定 null・clarify status なし）。
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
- FR-40 追加分:
  - backend: ask_user 経路の SSE 順序が status(clarify) → token → done(kind) であること／
    通常経路・ask_origin 経路に clarify status が混入しないこと（既存の順序・バイト同一系テスト更新可）。
  - store: status(clarify) → `clarificationExpected` が立つ／解除 5 条件（§5-2-3: 送信時全非活性化・
    キャンセル・error/catch クリーンアップ・kind なし finalize の安全弁・復元では立たない）／
    失敗再活性で expected も復帰。
  - LoadingSpinnerV5: mode validator に `elicit`／elicit で本文スロットが描画され実況テキストが
    出ない／settled でリング fade・elicit ではリングが残る（class/DOM レベルの検証）。
  - ChatView: mode 決定式（pending / clarificationExpected → elicit / settled）と
    R2 マイクロコピー（placeholder「質問の下の回答欄でお答えください」等）。

## 9. 検収基準

1. 「確認テスト」で専用フォームが質問文の文字送り完了後に出現し、composer がロックされる。
2. フォームから送信した回答が通常の user バブルとして表示され、会話が継続する。
3. キャンセルでフォームが閉じ、composer が即時使用可能になる。
4. 送信失敗でフォームが再活性し、そのまま再送できる。エラーバナーの再試行からも同経路で成功する。
5. リロード・スレッド切替でロックが残留しない（復元は常に非活性）。
6. 意匠が §6-2 の Sol R2 確定仕様どおりで、既存 UI と並べて違和感がない（Fable 目視 + スクリーンショット検収）。
7. pytest / Vitest / `npm run build` 全緑。既存テストの回帰なし。
8. reduced-motion でモーションが無効化される。
9. **（FR-40）確認質問ターン中、Aurora Ring が一度も settle しない**: 質問文ストリーミング中・
   文字送り中・フォーム受付中を通してリングが回り続ける（`aurora-ring-v5--elicit` 活性を機械確認＋
   スクリーンショット）。回答送信で次ターンの pending スピナーへ引き継がれ、キャンセルで settled へ
   fade する。通常回答ターンの演出は従来と完全同一。

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

### 11-2. FR-40（R2）検収記録（2026-07-19, Fable）

- 自動テスト: pytest **165 passed**／Vitest **113 passed**（+9: clarify status・expected 状態機械・
  elicit モード・R2 意匠/文言・R1 意匠不在）／`npm run build` 成功。
- Playwright 実機（mock 8081・390×844 / 1280×900）:
  1. **リング継続の遷移列を機械実証**（送信＋60ms サンプリングを単一 evaluate で実行 —
     ツール往復レイテンシでは過渡を捕捉できないため）: pending（分析→確認→**clarify 文言**）→
     **elicit**（リング opacity 1 のまま）→ フォーム開（elicit 維持）。**settled を一度も経由しない**
     — §9-9 合格。
  2. 回答送信の引き継ぎ: 送信 80ms 後に質問メッセージ settled・次ターン pending スピナー出現・
     フォーム消滅 — 「作業中」合図の連続性を確認。
  3. キャンセル: settled へ遷移しリング fade（opacity 0）を確認。
  4. locked composer: フッター側 textarea disabled・locked class・placeholder
     「質問の下の回答欄でお答えください」（**注意**: R2 はフォームも `composer-shell` class を再利用
     するため、検証セレクタは `form.composer-dock .composer-shell` でフッター側を特定すること）。
  5. R2 意匠: §6-2 どおり（cue row・インラインピル・円形矢印送信・ghost chip キャンセル・
     カード枠なし）を 390/1280 スクリーンショットで確認。
- reduced-motion（§9-8）は実装 CSS（elicit は settled の ring fade / kurun 停止セレクタに
  マッチしない・transition 抑制は既存規則）のコードレビューで確認。
