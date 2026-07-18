# UI_PET.md — FR-41 隠し機能「キャンパスペット」仕様 v1.0

- 位置づけ: OpenAI Codex CLI の隠し機能「Codex Pets」の APU-Navi 翻案（利用者発案 2026-07-19）。
- 目的: 来場者（高校生・保護者）への**癒し**。回答待ち時間に寄り添う小さなコンパニオンであり、
  機能案内はしない（実用機能ではなく隠し演出）。
- 役割: 仕様 = Fable（本書）／意匠 = **Fable デザインリード**（利用者指示 2026-07-19。R1〜R4 は
  GPT-5.6 Sol リードだったが「愛着を持たれにくい」ため R5 で交代）／実装 = Codex／レビュー = Fable。
- 本機能は **FE 完結・backend 変更ゼロ**。SSE 契約・エージェント挙動・既存 UI 挙動は一切変えない（§10）。

## §1 概要

- 通常は存在を一切見せない**隠し機能**。2 つの経路（§3）で解禁すると、チャット画面の隅に
  小さなペットが**煙からドロンと出現**し、以後エージェントの状態に反応して動く（§5）。
- ペットは 6 フォーム（§4）。召喚のたびに抽選で 1 体が現れる（なまはげはレア枠）。
- 状態は端末ローカル（localStorage）にのみ保存（§7)。アカウント・スレッド・backend とは無関係。

## §2 用語

| 用語 | 意味 |
|---|---|
| 解禁 (unlock) | 隠し機能の存在が端末上で有効化されること。初回召喚と同時に起きる |
| 召喚 (summon) | 煙演出とともにペットが 1 体出現すること。交代も同じ演出 |
| フォーム | ペットの姿（6 種。§4） |
| ドロン | 合言葉（§3-1）かつ登場演出の擬音。機能全体のモチーフ |

## §3 解禁トリガー（2 経路・両方実装）

### §3-1 合言葉「ドロン」

- composer に合言葉を入力して送信すると、**FE が送信前に横取り**して召喚する。
  backend へは送らず、スレッド履歴にも残さない（ユーザーバブルも作らない）。
- 判定（決定的・LLM 不使用）: 送信テキストを `trim` → NFKC 正規化 → 末尾の `!`/`！`/`。` を除去し、
  **「ドロン」または「どろん」と完全一致**した場合のみ発火。
  - 部分一致は不可。「ドロンとは何ですか」等は通常どおり backend へ送る（誤爆ゼロを最優先）。
- 判定が働くのは「通常送信が可能な状態」のみ。composer ロック中（FR-27 origin / FR-39 clarification）・
  `isSending` 中は通常の抑止に従う（合言葉の特別扱いなし）。
- 既に召喚済みの状態で再度合言葉を送ると**交代召喚**（§4-2 の抽選をやり直す）。

### §3-2 案内板（About ダイアログ）内の隠しボタン

- 「このアプリについて」ダイアログ（FR-22、`ChatView.vue` の About）内に**小さく目立たない
  ペットボタン**を常設する（解禁前から存在するが、それと分からない控えめさ。意匠は Sol）。
- 押下でダイアログを閉じて召喚（解禁前なら解禁も兼ねる）。
- **解禁後**は About ダイアログに正式な「キャンパスペット」行が現れる:
  表示/非表示トグル ＋「ドロン（交代）」ボタン。非表示にしても解禁状態は保持。

## §4 フォーム（6 種）と抽選

### §4-1 フォーム一覧

| id | 名（仮） | モチーフ | 軸 | 枠 |
|---|---|---|---|---|
| `robo` | — | 利用者支給リファレンス `referenceUI/piko.png`（ローカル保持・コミット禁止）準拠。スクリーン顔＋耳フィン＋胸ランプの人形型ロボット | かわいい | 通常 |
| `sarutahiko` | — | 利用者支給リファレンス `referenceUI/sarutahiko.webp` 準拠。長鼻・白いたてがみ・冠・注連縄・尾を持つ獣神サルタヒコの子（**かっこいい**軸・経路案内アプリと符合） | かっこいい | 通常 |
| `akita` | — | 秋田犬の子犬 | かわいい | 通常 |
| `gotenmari` | — | 本荘ごてんまり（伝統工芸のまり）がまんまるに跳ねるペット | かわいい | 通常 |
| `namahage` | — | 利用者支給リファレンス `referenceUI/namahage.jpg` 準拠。青系の面・荒れたたてがみ・蓑・桶（刃物は不採用）の**かっこいい**軸 | かっこいい | **レア** |
| `yatagarasu` | 八咫烏 | 利用者支給リファレンス `referenceUI/yatagarasu.jpg`（墨絵）準拠。**日輪を背にした漆黒の三本足の烏** — 導きの神使（経路案内アプリの守護・**バチバチかっこいい**指定） | かっこいい | 通常 |

- 軸は利用者検収（2026-07-19）で確定: かわいい軸 3 体＋かっこいい軸 3 体。どちらの軸でも
  「いかにも AI が作ったような」キャラデザは禁止。リファレンス 3 体は**配色も参考画像に忠実**とし、
  キャラ本体に限り UI トークン外の専用色を許可（利用者指示 2026-07-19・§12-2 R7 パレット）。各フォームの名前は Sol が提案し
  利用者が確定する（確定後この表に記入）。

### §4-2 抽選規則（決定的に実装・単体テスト対象）

1. まず**レア判定**: 5% で `namahage`。
2. 外れたら通常 5 フォームから抽選。**未出現（`seenForms` 未登録）のフォームを優先**し、その中から均等。
   全て出現済みなら「現在のフォーム以外」から均等。
3. 召喚したフォームは `seenForms` に追記。

## §5 状態機械（エージェント連動 — 本機能の本質）

ペットはアクティブスレッドのストア状態（`stores/chat.js`）だけを購読する。信号は既存のもののみ:

| ペット状態 | 発火条件（既存シグナル） | ふるまいの意図 |
|---|---|---|
| `summoning` | 召喚操作 | 煙がぽんと湧き、晴れるとペットが現れる（§6-2） |
| `idle` | 下記のいずれでもない | 待機。瞬き・しっぽ・たまに寝る等の生存感 |
| `thinking` | `isSending === true` | そわそわ動き回る・地面をくんくん等「一緒に探している」 |
| `clarify` | clarification 受付中（`clarificationActive` / `isClarificationPending`） | 動きを止めてこちらをじっと見つめ、首をかしげる（Codex Pets の「入力待ちで止まって見つめる」の翻案・FR-40 の探索継続演出と共存） |
| `done` | `isSending` が true→false に遷移してから約 4 秒 | おすわりして小さく喜ぶ → `idle` へ |
| `hidden` | トグルで非表示 | DOM から演出を除去（解禁状態は保持） |

- 各状態の具体モーションは Sol 裁定（§9）。`thinking` 中に `statusStep`（search/get_docs 等）で
  仕草を変えるかは Sol の任意提案とし、必須要件にしない。
- エラーバナー表示時の専用仕草も任意（なくてよい）。

## §6 表示・操作

### §6-1 配置

- チャットシェル**内**のオーバーレイ。FR-23 の固定シェル配下のため **`fixed` 禁止・`absolute` 配置**
  （過去の教訓: 固定シェル内の fixed はビジュアルビューポートとずれる）。
- メッセージ本文・composer・確認フォーム・地図カードの操作を**一切遮らない**こと。
  想定は composer 上部の右隅・目安 44〜64px（最終配置・サイズは Sol）。
- ペット本体以外はポインターイベントを透過する。

### §6-2 煙（ドロン）演出

- 出現・交代・退場はすべて「煙がぽん → 晴れる」で統一。数百 ms・`transform`/`opacity` のみ。
- `prefers-reduced-motion` では煙・走り回り等の大きな動きを止め、フェードと静止ポーズに置換（NFR-5）。

### §6-3 タップ操作

- シングルタップ: その場のリアクション（喜ぶ・鳴く等。Sol 裁定のバリエーション）。
- ダブルタップ: 交代召喚（§4-2 の抽選）。
- 非表示化は About ダイアログのトグルからのみ（誤操作で消えない）。

## §7 永続化

- localStorage キー **`campus-guide-pet`**（JSON）:
  `{ unlocked: boolean, visible: boolean, currentForm: string|null, seenForms: string[] }`
- リロード後: `unlocked && visible && currentForm` なら煙演出なしで静かに復元（idle）。
- 認証（`campus-guide-token`）とは独立。ログアウトしても消さない（端末ローカルの楽しみ）。

## §8 アクセシビリティ・性能

- ペットは装飾: コンテナに `aria-hidden="true"`。スクリーンリーダー動線に入れない。
  About のトグルのみ通常のアクセシブルなコントロールとする。
- アニメーションは `transform`/`opacity` に限定。LoadingSpinnerV5（Aurora Ring）・文字ストリーミングと
  **同時稼働しても jank しない**こと（中級スマホで 60fps 目安）。
- 画像アセットは追加しない。キャラは**インライン SVG**（+CSS アニメーション）で描く。

## §9 意匠（Fable デザインリード — R5 以降）

- R1〜R4 は GPT-5.6 Sol リード。利用者評価「愛着を持たれにくい」により R5 から Fable が
  デザインリードを引き継いだ（利用者指示 2026-07-19）。
- 掟: 「AI が作ったような」デザイン禁止・現行 UI と一体に見えること・UI 側は
  **Campus Signal 既存トークンのみ**（キャラ本体のみ §12-1 R7 のとおりリファレンス準拠の
  専用色を許可）。
- 意匠成果物: ①6 フォームの SVG キャラ意匠（各状態のポーズ・モーション設計込み）
  ②煙演出 ③配置・サイズ ④タップリアクション ⑤About ダイアログ内の隠しボタン/解禁後行の意匠
  ⑥各フォームの名前案。
- 確定意匠は本書 §12（意匠確定録）が正。実装は §12 の SVG/CSS をそのまま用いる
  （`docs/pet-preview.html` と §12 は常に同一内容を保つ）。

## §10 不可侵（変更してはならないもの）

- backend・SSE スキーマ・エージェント挙動（本機能は FE 完結）。
- 既存 composer の送信/ロック挙動（合言葉横取りは「完全一致時に送信を差し替える」だけ。
  それ以外の入力の経路は 1 バイトも変えない）。
- LoadingSpinnerV5（FR-5/12/40 不可侵）・確認フォーム（FR-39/40)・地図カード・About の既存内容。
- 解禁前の画面に痕跡を出さない（§3-2 の控えめボタンを除く）。

## §11 テスト観点（Vitest・受け入れ基準）

1. 合言葉判定: 「ドロン」「どろん」「 ドロン！ 」→ 発火・送信されない／「ドロンとは」「ドロンって何」→
   発火せず通常送信（ストアの送信スパイで検証）。
2. 抽選: レア 5%・未出現優先・交代時は現フォーム除外（乱数注入で決定的にテスト）。
3. 状態遷移: `isSending`・clarification・done 4 秒の各遷移。
4. 永続化: 保存/復元/トグル/ログアウト非消去。
5. reduced-motion 分岐。
6. 既存テスト（Vitest 94・ChatView/composer 系）が無変更で緑のまま。

## §12 意匠確定録（Sol 確定後に転記）

### §12-1. 採用概念 — Campus Signal Companion（R5・Fable 意匠改訂）

R1〜R4（Sol リード）は造形の規律は保てたが「愛着」に届かなかった（利用者評価）。R5 で Fable が
デザインリードを引き継ぎ、**愛着の文法**を最優先に全面改稿した。方針:

1. **単一の餅型シルエット**。頭＋胴＋小物の「組み立て」をやめ、明るい紙色（paper）の
   ひとつの塊として描く。暗背景の UI では明るい塊だけが「生き物」として浮かぶ
   （R4 までの暗色胴が沈んで見えた反省）。
2. **目が主役**。全フォーム共通で大きな暗色の瞳（paper-ink）＋**白いハイライト光点**。
   愛着の大半は瞳のハイライトが作る。かわいい軸は縦長の大きな瞳、かっこいい軸は
   同じ瞳の上に**凛々しい吊り眉**を重ねて精悍さを出す（目を小さくして冷たくしない）。
3. **頬紅**（signal-soft の低不透明度楕円）を全フォームに。かっこいい軸は控えめに。
4. モチーフは塊の上の **1〜2 記号だけ**（スクリーン顔と耳フィン／たてがみと冠と光の長柄／巻き尾／刺繍と房／たてがみと角と桶）。
5. 「かっこいい」は怖さではなく**ちび武者のかっこよさ**（眉・所作・持ち物）で表現し、
   愛着ベースを壊さない。
6. **R7（確定方針）**: robo / sarutahiko / namahage は利用者支給のリファレンス画像
   （`referenceUI/piko.png`, `referenceUI/sarutahiko.webp`, `referenceUI/namahage.jpg`,
   `referenceUI/yatagarasu.jpg` —
   ローカル保持・コミット禁止）を**そのままペット化**する（利用者指示 2026-07-19）。
   造作・配色ともリファレンスに忠実とし、そのため**この 3 体のキャラ本体に限り
   Campus Signal トークン外の専用色を許可**する（§12-2 の R7 パレット。UI 側には一切使わない）。
   ビットマップの埋め込み・トレースはせず、当プロジェクトのベクター言語で忠実に再構成する。
   namahage の出刃包丁のみ §4-1 の方針どおり不採用（来場者配慮）とし、象徴は「桶」を採用。
   sarutahiko の武器は刃物ではなく参考絵の「光の穂先」として描く。
7. **R10 視線**: 視線は**正面で良い**（利用者裁定 2026-07-19。一度導入した R8 オフ軸規則は
   同日撤回）。gotenmari のみ、承認済み意匠として顔一式の +x オフセットを維持する。

共通造形言語:

- viewBox は全フォーム `0 0 64 64`。基準サイズは **56px**、最小 44px、最大 64px。
- 本体は明るい単一マス（paper）＋外周 stroke なし。内部の分割線は paper-ink の
  低不透明度（0.16〜0.3）の細線のみ。かっこいい軸の顔面は signal-soft の丸。
- 瞳: 楕円（かわいい軸 rx3.4〜3.7 / かっこいい軸 rx3.2〜3.4）＋ハイライト r1.4〜1.6
  （opacity 0.95 前後）。`pet-eye` は g 要素で、瞬き（scaleY）はグループごと縮む。
- 体の接地は y≈57 の小さな影で統一。影もインライン SVG の半透明楕円。
- 色は既存 Campus Signal トークンのみ: `ink`, `paper`, `text`, `edge`, `brand.signal`, `brand.soft`, `aurora` 3 色。新規色は作らない。
- アニメーションは **transform / opacity のみ**。stroke dash、filter、layout 値、色の常時アニメーションは使わない。
- 頭身 1.2〜1.45。細部は 56px 以上で見える密度に抑え、44px は「輪郭・瞳・1 記号」で読ませる。

### §12-2. 実装用トークン

CSS 側で以下を `CampusPet.vue` の root に定義する。値は `frontend/src/style.css` の既存トークンそのもの。

```css
.campus-pet-host {
  --pet-canvas: var(--color-canvas);
  --pet-surface: var(--color-panel);
  --pet-raised: var(--color-raised);
  --pet-high: var(--color-high);
  --pet-paper: var(--color-paper);
  --pet-paper-ink: var(--color-paper-ink);
  --pet-text: var(--color-text);
  --pet-muted: var(--color-text-muted);
  --pet-dim: var(--color-text-dim);
  --pet-edge: var(--color-edge-strong);
  --pet-signal: var(--color-signal);
  --pet-signal-soft: var(--color-signal-soft);
  --pet-aurora-warm: #ff8f70;
  --pet-aurora-bridge: #ffc46b;
  --pet-aurora-mint: #6fe8a8;
}
```

#### R7 キャラ専用色（リファレンス準拠・キャラ本体限定）

利用者指示によりこの 3 体は参考画像の配色へ忠実とする。以下はキャラ SVG 内に直接記す
（UI トークンへは追加しない・UI 側での使用禁止）:

| 用途 | 値 |
|---|---|
| robo: ブルー主/深/スクリーン/発光/発光淡 | `#a6c8f0` / `#6d9de3` / `#1c2233` / `#9ed6ff` `#c9ecff` / `#e9fbff` |
| sarutahiko: 面/鼻/冠金/紺(前立て・鎧・柄)/毛金/縄/光刃/頬 | `#e2543c` / `#c8432e` / `#eebb55` / `#2b3245` / `#e6cf9a` / `#d7ae74` / `#a8e6f5` `#e9fbff` `#63c7e8` / `#ffb3a0` |
| namahage: 面青/角/角縞・鼻/たてがみ/毛影/蓑/蓑影/紐・舌/桶 | `#6b91c2` / `#9db8dd` / `#33415c` / `#d8ad6e` / `#3b352c` / `#cfa468` / `#4a3d2c` / `#d8503a` / `#c39055` |
| yatagarasu: 烏黒/翼・尾/羽光/銀眼/嘴上/嘴下/脚・爪/朱（眉・稲妻） | `#1f2228` / `#2e333d` / `#8a919e` / `#e8eaef` / `#d9dde3` / `#9aa1ad` / `#c9ccd4` / `#d8503a`（日輪は `paper` の透過面） |

### §12-3. 共通 SVG/CSS モーション

状態は SVG 直下またはボタンに `data-state="idle|thinking|clarify|done|summoning"` を付けて切り替える。タップリアクションは 700ms だけ `data-reaction="spark|nod|peek"` を付け、終了時に属性を外す。

```css
.campus-pet {
  display: block;
  width: 100%;
  height: 100%;
  overflow: visible;
}

.campus-pet * {
  vector-effect: non-scaling-stroke;
}

.campus-pet .pet-rig,
.campus-pet .pet-head,
.campus-pet .pet-body,
.campus-pet .pet-tail,
.campus-pet .pet-prop,
.campus-pet .pet-reaction-marks,
.campus-pet .pet-eye,
.campus-pet .pet-accent,
.campus-pet .pet-sun,
.campus-pet .pet-wing-l,
.campus-pet .pet-wing-r {
  transform-box: fill-box;
  transform-origin: center;
}

.campus-pet .pet-shadow {
  opacity: 0.16;
  transform-box: fill-box;
  transform-origin: center;
}

.campus-pet .pet-reaction-marks {
  opacity: 0;
}

.campus-pet[data-state="idle"] .pet-rig {
  animation: campus_pet_idle_bob 4.8s var(--ease-standard) infinite;
}

.campus-pet[data-state="idle"] .pet-eye,
.campus-pet[data-state="thinking"] .pet-eye {
  animation: campus_pet_blink 5.6s steps(1, end) infinite;
}

.campus-pet[data-state="thinking"] .pet-rig {
  animation: campus_pet_thinking_scout 1.15s var(--ease-standard) infinite;
}

.campus-pet[data-state="clarify"] .pet-rig {
  transform: translate3d(0, -1px, 0);
}

.campus-pet[data-state="clarify"] .pet-head {
  transform: rotate(-7deg);
}

.campus-pet[data-state="clarify"] .pet-eye {
  animation: none;
  transform: scaleY(1.16);
}

.campus-pet[data-state="done"] .pet-rig {
  animation: campus_pet_done_pop 860ms var(--ease-expressive) both;
}

.campus-pet[data-state="done"] .pet-reaction-marks {
  animation: campus_pet_reaction_spark 860ms var(--ease-expressive) both;
}

.campus-pet[data-state="summoning"] .pet-rig {
  animation: campus_pet_materialize 640ms var(--ease-expressive) both;
}

.campus-pet[data-reaction="spark"] .pet-reaction-marks {
  animation: campus_pet_reaction_spark 720ms var(--ease-expressive) both;
}

.campus-pet[data-reaction="nod"] .pet-head {
  animation: campus_pet_reaction_nod 620ms var(--ease-expressive) both;
}

.campus-pet[data-reaction="peek"] .pet-rig {
  animation: campus_pet_reaction_peek 720ms var(--ease-expressive) both;
}

@keyframes campus_pet_idle_bob {
  0%, 100% { transform: translate3d(0, 0, 0); }
  50% { transform: translate3d(0, -1.6px, 0); }
}

@keyframes campus_pet_blink {
  0%, 90%, 100% { transform: scaleY(1); }
  92%, 94% { transform: scaleY(0.14); }
}

@keyframes campus_pet_thinking_scout {
  0%, 100% { transform: translate3d(-1.8px, 0, 0) rotate(-1.5deg); }
  50% { transform: translate3d(2px, -1px, 0) rotate(1.5deg); }
}

@keyframes campus_pet_done_pop {
  0% { transform: translate3d(0, 0, 0) scale(1); }
  28% { transform: translate3d(0, -5px, 0) scale(1.07); }
  58% { transform: translate3d(0, 1px, 0) scale(0.98); }
  100% { transform: translate3d(0, 0, 0) scale(1); }
}

@keyframes campus_pet_materialize {
  0% { opacity: 0; transform: translate3d(0, 8px, 0) scale(0.72); }
  54% { opacity: 0; transform: translate3d(0, 5px, 0) scale(0.82); }
  100% { opacity: 1; transform: translate3d(0, 0, 0) scale(1); }
}

@keyframes campus_pet_reaction_spark {
  0% { opacity: 0; transform: translate3d(0, 3px, 0) scale(0.7); }
  35% { opacity: 1; transform: translate3d(0, -2px, 0) scale(1); }
  100% { opacity: 0; transform: translate3d(0, -8px, 0) scale(0.92); }
}

@keyframes campus_pet_reaction_nod {
  0%, 100% { transform: rotate(0deg); }
  34% { transform: rotate(9deg); }
  68% { transform: rotate(-5deg); }
}

@keyframes campus_pet_reaction_peek {
  0%, 100% { transform: translate3d(0, 0, 0) scale(1); }
  40% { transform: translate3d(0, -3px, 0) scale(1.04); }
}

@media (prefers-reduced-motion: reduce) {
  .campus-pet .pet-rig,
  .campus-pet .pet-head,
  .campus-pet .pet-body,
  .campus-pet .pet-tail,
  .campus-pet .pet-prop,
  .campus-pet .pet-eye,
  .campus-pet .pet-reaction-marks {
    animation: none !important;
    transition: none !important;
  }

  .campus-pet[data-state="thinking"] .pet-rig,
  .campus-pet[data-state="done"] .pet-rig {
    transform: translate3d(0, -1px, 0);
  }

  .campus-pet[data-state="clarify"] .pet-head {
    transform: rotate(-5deg);
  }

  .campus-pet[data-state="summoning"] .pet-rig {
    opacity: 1;
    transform: none;
  }

  .campus-pet[data-reaction] .pet-reaction-marks {
    opacity: 1;
    transform: translate3d(0, -5px, 0);
  }
}
```

### §12-4. フォーム別のインライン SVG

#### `robo` — 名前案: 「ぴこ」

リファレンス（piko.png）をそのままペット化した白×ブルーのロボット。丸角の白ヘッドに**紺のスクリーン顔**、中に**淡シアンに発光する大きな瞳**と**ビューファインダーの四隅括弧**、小さな口。頭側面に**青い耳パック＋傾いた青フィン**（`pet-accent` — idle で明滅・thinking でスキャン）。胴は白ポッドに**青のスカラップベスト**と**発光する胸サークル**、白い腕＋青の肩キャップ。足は付けず**接地影から浮くホバー**で参考絵の浮遊感を出す。

```html
<svg class="campus-pet campus-pet--robo" data-state="idle" viewBox="0 0 64 64" aria-hidden="true">
  <g class="pet-shadow">
    <ellipse cx="32" cy="57" rx="15" ry="3.4" fill="var(--pet-text)" />
  </g>
  <g class="pet-rig">
    <g class="pet-body">
      <path d="M20.6 45.4c0-5.2 5-8.6 11.4-8.6s11.4 3.4 11.4 8.6c0 5-4.6 8.4-11.4 8.4s-11.4-3.4-11.4-8.4z" fill="#f0efe9" />
      <path d="M20.7 44.8c.3-4.4 5.1-7.4 11.3-7.4s11 3 11.3 7.4c-1.9 0-2.8 1.9-3.8 1.9s-1.9-1.9-3.8-1.9-2.7 1.9-3.7 1.9-1.8-1.9-3.7-1.9-2.7 1.9-3.7 1.9-1.9-1.9-3.9-1.9z" fill="#a6c8f0" />
      <circle cx="32" cy="48.2" r="4" fill="none" stroke="#a6c8f0" stroke-width="1.2" opacity="0.6" />
      <circle cx="32" cy="48.2" r="2.7" fill="#9ed6ff" />
      <circle cx="32" cy="48.2" r="1.2" fill="#e9fbff" />
      <ellipse cx="17.4" cy="43.4" rx="2.7" ry="4.4" transform="rotate(26 17.4 43.4)" fill="#f0efe9" />
      <ellipse cx="17" cy="40.6" rx="1.9" ry="2.1" transform="rotate(26 17 40.6)" fill="#a6c8f0" />
      <ellipse cx="46.6" cy="44.2" rx="2.7" ry="4.4" transform="rotate(-18 46.6 44.2)" fill="#f0efe9" />
      <ellipse cx="46.9" cy="41.4" rx="1.9" ry="2.1" transform="rotate(-18 46.9 41.4)" fill="#a6c8f0" />
    </g>
    <g class="pet-head">
      <g class="pet-prop pet-accent">
        <ellipse cx="13.6" cy="14.6" rx="2.4" ry="5.6" transform="rotate(-32 13.6 14.6)" fill="#a6c8f0" />
        <ellipse cx="13.9" cy="15.4" rx="1.1" ry="3.2" transform="rotate(-32 13.9 15.4)" fill="#6d9de3" />
        <ellipse cx="50.4" cy="14.6" rx="2.4" ry="5.6" transform="rotate(32 50.4 14.6)" fill="#a6c8f0" />
        <ellipse cx="50.1" cy="15.4" rx="1.1" ry="3.2" transform="rotate(32 50.1 15.4)" fill="#6d9de3" />
      </g>
      <circle cx="15.9" cy="24.5" r="3" fill="#a6c8f0" />
      <circle cx="15.9" cy="24.5" r="1.3" fill="#6d9de3" />
      <circle cx="48.1" cy="24.5" r="3" fill="#a6c8f0" />
      <circle cx="48.1" cy="24.5" r="1.3" fill="#6d9de3" />
      <path d="M26 12h12c5.5 0 10 4.5 10 10v6.4c0 5.5-4.5 10-10 10H26c-5.5 0-10-4.5-10-10V22c0-5.5 4.5-10 10-10z" fill="#f0efe9" />
      <path d="M26.6 17h10.8c3.4 0 6.1 2.7 6.1 6.1v4.2c0 3.4-2.7 6.1-6.1 6.1H26.6c-3.4 0-6.1-2.7-6.1-6.1v-4.2c0-3.4 2.7-6.1 6.1-6.1z" fill="#1c2233" />
      <path d="M26 19.8h-2.7v2.7M38 19.8h2.7v2.7M26 30.6h-2.7v-2.7M38 30.6h2.7v-2.7" fill="none" stroke="#9ed6ff" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" opacity="0.8" />
      <g class="pet-eye">
        <ellipse cx="26.9" cy="25" rx="4.1" ry="5" fill="#9ed6ff" opacity="0.2" />
        <ellipse cx="26.9" cy="25" rx="3.2" ry="4.1" fill="#c9ecff" />
        <circle cx="25.7" cy="23.2" r="1.35" fill="#ffffff" opacity="0.95" />
      </g>
      <g class="pet-eye">
        <ellipse cx="37.1" cy="25" rx="4.1" ry="5" fill="#9ed6ff" opacity="0.2" />
        <ellipse cx="37.1" cy="25" rx="3.2" ry="4.1" fill="#c9ecff" />
        <circle cx="35.9" cy="23.2" r="1.35" fill="#ffffff" opacity="0.95" />
      </g>
      <path d="M30.3 30.9q1.7 1.5 3.4 0" fill="none" stroke="#9ed6ff" stroke-width="1.3" stroke-linecap="round" opacity="0.8" />
      <ellipse cx="18.5" cy="33" rx="1.9" ry="1.25" fill="var(--pet-signal-soft)" opacity="0.4" />
      <ellipse cx="45.5" cy="33" rx="1.9" ry="1.25" fill="var(--pet-signal-soft)" opacity="0.4" />
    </g>
    <g class="pet-reaction-marks">
      <circle cx="50" cy="9.5" r="2" fill="#9ed6ff" />
      <circle cx="53.5" cy="15.5" r="1.4" fill="var(--pet-aurora-mint)" />
      <path d="M46 14.6l2.2 2.2" fill="none" stroke="var(--pet-aurora-bridge)" stroke-width="2.2" stroke-linecap="round" />
    </g>
  </g>
</svg>
```

フォーム固有モーション:

```css
.campus-pet--robo[data-state="idle"] .pet-accent {
  animation: campus_pet_robo_ping 2.8s var(--ease-standard) infinite;
}

.campus-pet--robo[data-state="thinking"] .pet-accent {
  animation: campus_pet_robo_scan 760ms var(--ease-standard) infinite;
}

.campus-pet--robo[data-state="done"] .pet-accent,
.campus-pet--robo[data-reaction="spark"] .pet-accent {
  animation: campus_pet_robo_ping 620ms var(--ease-expressive) 2;
}

@keyframes campus_pet_robo_ping {
  0%, 100% { opacity: 0.7; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.18); }
}

@keyframes campus_pet_robo_scan {
  0%, 100% { transform: translate3d(-1px, 0, 0); }
  50% { transform: translate3d(1px, -1px, 0); }
}
```

#### `sarutahiko` — 名前案: 「みちかぜ」

リファレンス（sarutahiko.webp・獣神サルタヒコ）をそのままペット化。**赤い面と長く堂々と伸びる天狗鼻**、**金の冠帯＋紺の前立て三本**、顔を囲む**白い荒々しいたてがみ**と右上へなびく**淡金の毛房**、胸に**紺の鎧当て（金の縁＋シアンの光筋）**、腰に**注連縄と紙垂 2 枚**、左下に**淡金のふさふさの尾**、対角に構えた**光の穂先の長柄**（刃物ではなく発光体。クラス名は互換のため `pet-guide-spear`）。凛々しい直線眉＋ハイライト入りの大きな瞳は愛着文法のまま。

```html
<svg class="campus-pet campus-pet--sarutahiko" data-state="idle" viewBox="0 0 64 64" aria-hidden="true">
  <g class="pet-shadow">
    <ellipse cx="32" cy="57" rx="15" ry="3.5" fill="var(--pet-text)" />
  </g>
  <g class="pet-rig">
    <g class="pet-prop pet-tail-fluff">
      <path d="M17.8 52.6c-8.3-.2-13-5.4-11.9-12.1l4.7 1.6-.5-4.6c5.5 1.8 8.6 6.1 8.3 11.5z" fill="#e6cf9a" />
      <path d="M9.6 43.6c2.9 1.5 4.9 4 5.6 7.3" fill="none" stroke="#3b352c" stroke-width="1.1" stroke-linecap="round" opacity="0.3" />
    </g>
    <g class="pet-prop pet-guide-spear">
      <path d="M44.6 51.6L55.2 19.4" fill="none" stroke="#2b3245" stroke-width="2.4" stroke-linecap="round" />
      <g transform="rotate(18 55.2 19.4)">
        <ellipse cx="55.4" cy="12.8" rx="4.6" ry="7" fill="#a8e6f5" opacity="0.22" />
        <path d="M55.3 6.8c2.4 3.4 3 7.4 1.7 11.3-1.3.9-2.5.9-3.6 0-1.3-3.9-.7-7.9 1.9-11.3z" fill="#a8e6f5" />
        <path d="M55.3 9.2c1.3 2.3 1.6 4.9.9 7.4-.6.4-1.2.4-1.8 0-.7-2.5-.4-5.1.9-7.4z" fill="#e9fbff" />
      </g>
    </g>
    <g class="pet-body">
      <path d="M32 16.4c8.8 0 14.8 5.5 14.8 13.7 0 3.3-.4 6.6-1.3 9.9-1.9 8-6.1 12.9-13.5 12.9s-11.6-4.9-13.5-12.9c-.9-3.3-1.3-6.6-1.3-9.9 0-8.2 6-13.7 14.8-13.7z" fill="var(--pet-paper)" />
      <path d="M26 40.6h12c1.8 0 3 1.4 2.7 3.2l-.9 5c-2.4 1.6-4.9 2.4-7.8 2.4s-5.4-.8-7.8-2.4l-.9-5c-.3-1.8.9-3.2 2.7-3.2z" fill="#2b3245" />
      <path d="M26.2 40.9h11.6" fill="none" stroke="#eebb55" stroke-width="1.2" stroke-linecap="round" opacity="0.85" />
      <path d="M28.4 43.4c2.4 2.2 4.8 2.2 7.2 0" fill="none" stroke="#63c7e8" stroke-width="1.4" stroke-linecap="round" opacity="0.9" />
      <path d="M21.2 48.1c7.4 2.9 14.2 2.9 21.6 0" fill="none" stroke="#d7ae74" stroke-width="3.1" stroke-linecap="round" />
      <path d="M24 48.2l-.9 1.8M27.9 49.3l-.8 1.9M32 49.7l-.3 2M36.1 49.3l.6 1.9M40 48.2l.8 1.8" fill="none" stroke="#3b352c" stroke-width="1" stroke-linecap="round" opacity="0.35" />
      <path d="M27.2 50.5l2 .3-1.4 1.8 1.2 1.9-2 .3zM36.8 50.5l-2 .3 1.4 1.8-1.2 1.9 2 .3z" fill="var(--pet-paper)" />
    </g>
    <g class="pet-head">
      <path d="M32 11.4l2.5 3.9 4.1-2.7-.3 4.7 4.7-.8-2 4.1 4.5 1.1-3.6 3 3.6 3.1-4.5 1 2 4.2-4.7-.9.3 4.8-4.1-2.7-2.5 3.8-2.5-3.8-4.1 2.7.3-4.8-4.7.9 2-4.2-4.5-1 3.6-3.1-3.6-3 4.5-1.1-2-4.1 4.7.8-.3-4.7 4.1 2.7z" fill="var(--pet-paper)" />
      <path d="M39.6 13.6c5.9-4.9 12-3.6 15 1.5-2.6 3-6.6 3.8-11 2.3l-3.6-2z" fill="#e6cf9a" />
      <path d="M42.3 15.2c3.1-2 6.4-2 9-.4" fill="none" stroke="#3b352c" stroke-width="1" stroke-linecap="round" opacity="0.25" />
      <circle cx="32" cy="27.5" r="11.8" fill="#e2543c" />
      <path d="M26.4 18.4l1.4-5 1.4 4.6zM30.6 17.6l1.4-5.4 1.4 5.2zM34.9 18.1l1.4-4.9 1.4 4.7z" fill="#2b3245" />
      <path d="M22.7 20.9c5.9-2.5 12.7-2.5 18.6 0" fill="none" stroke="#eebb55" stroke-width="2.6" stroke-linecap="round" />
      <path d="M23.5 23.2l5.9-1.4M40.5 23.2l-5.9-1.4" fill="none" stroke="var(--pet-paper-ink)" stroke-width="2.3" stroke-linecap="round" />
      <g class="pet-eye">
        <ellipse cx="25.3" cy="27.9" rx="3.1" ry="3.7" fill="var(--pet-paper-ink)" />
        <circle cx="24.1" cy="26.3" r="1.35" fill="#ffffff" opacity="0.96" />
      </g>
      <g class="pet-eye">
        <ellipse cx="38.7" cy="27.9" rx="3.1" ry="3.7" fill="var(--pet-paper-ink)" />
        <circle cx="37.5" cy="26.3" r="1.35" fill="#ffffff" opacity="0.96" />
      </g>
      <path d="M32 25.6c-1.5 0-2.4.9-2.4 2.1 0 3.3.9 6.7 2.4 9.4 1.5-2.7 2.4-6.1 2.4-9.4 0-1.2-.9-2.1-2.4-2.1z" fill="#c8432e" />
      <circle cx="31.3" cy="34.6" r="0.7" fill="#ffffff" opacity="0.5" />
      <path d="M30.3 38.6h3.4" fill="none" stroke="var(--pet-paper-ink)" stroke-width="1.6" stroke-linecap="round" opacity="0.66" />
      <ellipse cx="21.4" cy="31.4" rx="2" ry="1.3" fill="#ffb3a0" opacity="0.45" />
      <ellipse cx="42.6" cy="31.4" rx="2" ry="1.3" fill="#ffb3a0" opacity="0.45" />
    </g>
    <g class="pet-reaction-marks">
      <path d="M12.5 19q4.5.5 7 3.5M10.5 25.5q4 0 6.5 2" fill="none" stroke="var(--pet-signal)" stroke-width="2" stroke-linecap="round" />
    </g>
  </g>
</svg>
```

フォーム固有モーション:

```css
.campus-pet--sarutahiko[data-state="idle"] .pet-guide-spear {
  animation: campus_pet_spear_rest 4.8s var(--ease-standard) infinite;
}

.campus-pet--sarutahiko[data-state="thinking"] .pet-guide-spear {
  animation: campus_pet_spear_point 900ms var(--ease-standard) infinite;
}

.campus-pet--sarutahiko[data-state="done"] .pet-guide-spear,
.campus-pet--sarutahiko[data-reaction="spark"] .pet-guide-spear {
  animation: campus_pet_spear_cheer 760ms var(--ease-expressive) both;
}

.campus-pet--sarutahiko[data-state="clarify"] .pet-head {
  transform: translate3d(0, 1px, 0) scaleY(0.98);
}

.campus-pet--sarutahiko[data-state="clarify"] .pet-eye {
  transform: scaleY(0.78);
}

@keyframes campus_pet_spear_rest {
  0%, 100% { transform: rotate(0deg); }
  50% { transform: rotate(2deg); }
}

@keyframes campus_pet_spear_point {
  0%, 100% { transform: translate3d(0, 0, 0) rotate(-2deg); }
  50% { transform: translate3d(1.5px, -1px, 0) rotate(4deg); }
}

@keyframes campus_pet_spear_cheer {
  0%, 100% { transform: rotate(0deg); }
  45% { transform: rotate(-12deg) translate3d(-1px, -2px, 0); }
}
```

#### `akita` — 名前案: 「こまち」

秋田犬は白い子犬として、小さく丸めた三角耳・丸い額・腰の上に乗る巻き尾で読む。内耳の薄い影で猫耳との差をつけ、赤い首輪だけを Signal Coral にして、本体は `paper` と `ink` の二値に近づける。R5 で瞳をハイライト入りの大きな楕円に拡大し、頬紅を追加（シルエット・耳・尾・首輪は R3 承認時のまま不変）。

```html
<svg class="campus-pet campus-pet--akita" data-state="idle" viewBox="0 0 64 64" aria-hidden="true">
  <g class="pet-shadow">
    <ellipse cx="33" cy="57" rx="17" ry="3.8" fill="var(--pet-text)" />
  </g>
  <g class="pet-rig">
    <g class="pet-body">
      <path d="M19.5 38.4c4-5.3 20.3-5.3 24.8 0.2 3.3 4 3 11.2-0.9 14.4-4 3.3-18.6 3.3-22.8 0-4.1-3.2-4.5-10.7-1.1-14.6z" fill="var(--pet-paper)" stroke="var(--pet-edge)" stroke-width="2.2" />
      <path d="M25.5 45.6h13" fill="none" stroke="var(--pet-signal)" stroke-width="2.5" stroke-linecap="round" />
      <path d="M24.3 54v-4.1M39.8 54v-4.1" fill="none" stroke="var(--pet-paper-ink)" stroke-width="2.2" stroke-linecap="round" opacity="0.58" />
    </g>
    <g class="pet-tail">
      <path d="M42.7 43c1.4-1.2 1.1-3.1 1.6-4.7 0.9-3.3 3.8-5.2 6.9-4.6 3.2 0.7 5 3.7 4.4 6.9-0.7 3.3-3.9 5.2-7.1 4.4-2-0.5-3.3-1.9-5.8-2z" fill="var(--pet-paper)" />
      <path d="M44.3 38.3c0.9-3.3 3.8-5.2 6.9-4.6 3.2 0.7 5 3.7 4.4 6.9-0.7 3.3-3.9 5.2-7.1 4.4-1.8-0.4-3.1-1.6-4.1-2.8" fill="none" stroke="var(--pet-edge)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
      <path d="M49.6 40c0.7-0.7 1.9-0.2 1.9 0.8 0 1.3-1.4 2.1-2.6 1.6-1.7-0.7-2-3-0.6-4.2 1.8-1.5 4.6-0.4 5.1 1.8" fill="none" stroke="var(--pet-paper-ink)" stroke-width="1.25" stroke-linecap="round" opacity="0.48" />
    </g>
    <g class="pet-head">
      <path d="M20.8 22.2c-0.8-3.2-2.7-6.3-3.9-8 4.4 0.3 7.5 2.3 9.1 5.8z" fill="var(--pet-paper)" stroke="var(--pet-edge)" stroke-width="2.1" stroke-linejoin="round" />
      <path d="M43.2 22.2c0.8-3.2 2.7-6.3 3.9-8-4.4 0.3-7.5 2.3-9.1 5.8z" fill="var(--pet-paper)" stroke="var(--pet-edge)" stroke-width="2.1" stroke-linejoin="round" />
      <path d="M21.3 19.5c-0.5-1.3-1.3-2.5-2.1-3.4 1.8 0.5 3.2 1.4 4.2 2.8z" fill="var(--pet-signal-soft)" opacity="0.38" />
      <path d="M42.7 19.5c0.5-1.3 1.3-2.5 2.1-3.4-1.8 0.5-3.2 1.4-4.2 2.8z" fill="var(--pet-signal-soft)" opacity="0.38" />
      <path d="M17.8 29.8c0-8.1 6.4-14.3 14.2-14.3s14.2 6.2 14.2 14.3v1.9c0 8.1-6.4 14.3-14.2 14.3s-14.2-6.2-14.2-14.3v-1.9z" fill="var(--pet-paper)" stroke="var(--pet-edge)" stroke-width="2.2" />
      <path d="M26.8 32.2c1.4 2.4 8.9 2.4 10.4 0 0.2 4.6-2.1 7.3-5.2 7.3s-5.4-2.7-5.2-7.3z" fill="var(--pet-text)" opacity="0.18" />
      <g class="pet-eye">
        <ellipse cx="26.85" cy="29.4" rx="2.5" ry="3.1" fill="var(--pet-paper-ink)" />
        <circle cx="25.9" cy="28" r="1.15" fill="var(--pet-paper)" opacity="0.95" />
      </g>
      <g class="pet-eye">
        <ellipse cx="37.15" cy="29.4" rx="2.5" ry="3.1" fill="var(--pet-paper-ink)" />
        <circle cx="36.2" cy="28" r="1.15" fill="var(--pet-paper)" opacity="0.95" />
      </g>
      <path d="M31.9 33.2l-1.7 1.4h3.6l-1.9-1.4z" fill="var(--pet-paper-ink)" opacity="0.82" />
      <path d="M29 37.5c1.5 1.1 4.6 1.1 6 0" fill="none" stroke="var(--pet-paper-ink)" stroke-width="1.8" stroke-linecap="round" opacity="0.52" />
      <ellipse cx="21.6" cy="33.8" rx="2.3" ry="1.5" fill="var(--pet-signal-soft)" opacity="0.5" />
      <ellipse cx="42.4" cy="33.8" rx="2.3" ry="1.5" fill="var(--pet-signal-soft)" opacity="0.5" />
    </g>
    <g class="pet-reaction-marks">
      <path d="M13.5 36.5c-2.6 0-4.5 1.4-4.5 3.2 0 2.5 3.5 2.8 4.5 0.8 1 2 4.5 1.7 4.5-0.8 0-1.8-1.9-3.2-4.5-3.2z" fill="var(--pet-signal-soft)" />
    </g>
  </g>
</svg>
```

フォーム固有モーション:

```css
.campus-pet--akita[data-state="idle"] .pet-tail,
.campus-pet--akita[data-state="thinking"] .pet-tail {
  transform-origin: 10% 88%;
  animation: campus_pet_tail_wag 820ms var(--ease-standard) infinite;
}

.campus-pet--akita[data-state="thinking"] .pet-head {
  animation: campus_pet_akita_sniff 1.15s var(--ease-standard) infinite;
}

.campus-pet--akita[data-state="clarify"] .pet-tail {
  animation: none;
}

.campus-pet--akita[data-state="done"] .pet-tail,
.campus-pet--akita[data-reaction="spark"] .pet-tail {
  transform-origin: 10% 88%;
  animation: campus_pet_tail_wag 260ms var(--ease-standard) 5;
}

@keyframes campus_pet_tail_wag {
  0%, 100% { transform: rotate(-8deg); }
  50% { transform: rotate(10deg); }
}

@keyframes campus_pet_akita_sniff {
  0%, 100% { transform: translate3d(0, 0, 0) rotate(0deg); }
  50% { transform: translate3d(0, 2px, 0) rotate(-3deg); }
}
```

#### `gotenmari` — 名前案: 「てまりん」

本荘ごてんまりは「吊るし飾りの明るい手まり」として扱う。`paper` の球面に、左上へ寄せた菊花様の放射刺繍を置き、水平対称の円弧は使わない。顔は刺繍から離した下半分に `paper-ink` で明快に置き、上の吊るし紐と下の房を 44px でも残る固有記号にする。R5 で瞳をハイライト入りの大きな楕円に拡大し、頬紅を追加（球面・刺繍・紐・房は R2 承認時のまま不変）。

```html
<svg class="campus-pet campus-pet--gotenmari" data-state="idle" viewBox="0 0 64 64" aria-hidden="true">
  <g class="pet-shadow">
    <ellipse cx="32" cy="58.5" rx="13.5" ry="3.2" fill="var(--pet-text)" />
  </g>
  <g class="pet-rig">
    <g class="pet-prop pet-hanger">
      <path d="M32 3.5v10.8" fill="none" stroke="var(--pet-muted)" stroke-width="1.9" stroke-linecap="round" />
      <path d="M28.4 12.7c1.5-1.5 5.7-1.5 7.2 0" fill="none" stroke="var(--pet-signal)" stroke-width="2" stroke-linecap="round" />
    </g>
    <g class="pet-body pet-ball">
      <circle cx="32" cy="31.5" r="18" fill="var(--pet-paper)" stroke="var(--pet-muted)" stroke-width="1.6" opacity="0.98" />
      <g class="pet-stitch">
        <path d="M23.5 23.8c-2.8-3.5-2.1-6.6 0-9.1 2.1 2.5 2.8 5.6 0 9.1z" fill="var(--pet-signal)" opacity="0.78" />
        <path d="M24.4 23.2c0.6-4.1 3.3-6.2 6.7-7.2-0.3 3.6-2.3 6.2-6.7 7.2z" fill="var(--pet-aurora-bridge)" opacity="0.88" />
        <path d="M24.6 24c3.7-2.1 7.1-1.5 9.7 0-2.6 1.7-6 2.2-9.7 0z" fill="var(--pet-signal-soft)" opacity="0.8" />
        <path d="M24.4 24.8c4.2 0.8 6.2 3.5 6.9 6.8-3.5-0.5-6.1-2.6-6.9-6.8z" fill="var(--pet-aurora-mint)" opacity="0.78" />
        <path d="M23.5 25c2.7 3.5 2.1 6.6 0 9.2-2.1-2.6-2.7-5.7 0-9.2z" fill="var(--pet-aurora-bridge)" opacity="0.82" />
        <path d="M22.6 24.8c-0.8 4.2-3.4 6.3-6.8 7 0.5-3.5 2.6-6.1 6.8-7z" fill="var(--pet-signal-soft)" opacity="0.68" />
        <path d="M22.4 24c-3.7 2.1-7.1 1.5-9.6-0.1 2.6-1.6 5.9-2.1 9.6 0.1z" fill="var(--pet-aurora-mint)" opacity="0.72" />
        <circle cx="23.5" cy="24.1" r="1.8" fill="var(--pet-paper-ink)" opacity="0.78" />
      </g>
      <g class="pet-face">
        <g class="pet-eye">
          <ellipse cx="30.2" cy="36.6" rx="2.2" ry="2.8" fill="var(--pet-paper-ink)" />
          <circle cx="29.4" cy="35.4" r="1.05" fill="var(--pet-paper)" opacity="0.95" />
        </g>
        <g class="pet-eye">
          <ellipse cx="37.5" cy="36.6" rx="2.2" ry="2.8" fill="var(--pet-paper-ink)" />
          <circle cx="36.7" cy="35.4" r="1.05" fill="var(--pet-paper)" opacity="0.95" />
        </g>
        <path d="M31.2 41.4c1.5 1.1 3.9 1.1 5.4 0" fill="none" stroke="var(--pet-paper-ink)" stroke-width="1.8" stroke-linecap="round" opacity="0.72" />
        <ellipse cx="26.6" cy="40.2" rx="2" ry="1.3" fill="var(--pet-signal-soft)" opacity="0.5" />
        <ellipse cx="41" cy="40.2" rx="2" ry="1.3" fill="var(--pet-signal-soft)" opacity="0.5" />
      </g>
      <g class="pet-prop pet-tassel">
        <path d="M29.3 48.6h5.4l-1.2 3h-3z" fill="var(--pet-signal)" />
        <path d="M30.2 51.1l-1.8 5.2M32 51.3v5.6M33.8 51.1l1.8 5.2" fill="none" stroke="var(--pet-signal-soft)" stroke-width="1.6" stroke-linecap="round" />
      </g>
    </g>
    <g class="pet-reaction-marks">
      <path d="M47.5 18.5l1.5-3 1.5 3 3 1.5-3 1.5-1.5 3-1.5-3-3-1.5 3-1.5z" fill="var(--pet-aurora-bridge)" />
      <circle cx="16.5" cy="23.5" r="1.8" fill="var(--pet-signal-soft)" />
    </g>
  </g>
</svg>
```

フォーム固有モーション:

```css
.campus-pet--gotenmari[data-state="idle"] .pet-ball {
  animation: campus_pet_temari_sway 4.2s var(--ease-standard) infinite;
}

.campus-pet--gotenmari[data-state="thinking"] .pet-ball {
  animation: campus_pet_temari_hop 780ms var(--ease-expressive) infinite;
}

.campus-pet--gotenmari[data-state="done"] .pet-ball,
.campus-pet--gotenmari[data-reaction="spark"] .pet-ball {
  animation: campus_pet_temari_done 820ms var(--ease-expressive) both;
}

@keyframes campus_pet_temari_sway {
  0%, 100% { transform: rotate(-2deg); }
  50% { transform: rotate(2deg); }
}

@keyframes campus_pet_temari_hop {
  0%, 100% { transform: translate3d(0, 0, 0) rotate(-4deg); }
  45% { transform: translate3d(0, -5px, 0) rotate(5deg); }
}

@keyframes campus_pet_temari_done {
  0%, 100% { transform: translate3d(0, 0, 0) scale(1); }
  40% { transform: translate3d(0, -6px, 0) scale(1.04); }
  65% { transform: translate3d(0, 1px, 0) scale(0.98); }
}
```

#### `namahage` — 名前案: 「ガオウ」

レア枠。リファレンス（namahage.jpg・伝統なまはげ絵）をそのままペット化。**青い面**・**藁色に黒筋の走る荒れた大きなたてがみ**・**青灰に紺縞の大角**・太い吊り眉・ハイライト入りの大きな瞳・**歯列と上向きの牙が覗く大きな口＋赤い舌**。体は**藁色の蓑（裾ギザギザ・黒筋）に赤い紐 2 本**、右手に**木桶**（出刃包丁は §4-1 の方針どおり不採用）。rare mark がレア出現の高揚を担う。

```html
<svg class="campus-pet campus-pet--namahage" data-state="idle" viewBox="0 0 64 64" aria-hidden="true">
  <g class="pet-shadow">
    <ellipse cx="32" cy="57.2" rx="16.5" ry="3.6" fill="var(--pet-text)" />
  </g>
  <g class="pet-rig">
    <g class="pet-body">
      <path d="M21.6 40h20.8l3.8 12.6l-4.2-1.2-2 2.4-3-2-2.2 2.2-2.8-2.2-2.8 2.2-2.2-2.2-3 2-2-2.4-4.2 1.2z" fill="#cfa468" />
      <path d="M23 43l-1.7 8.6M27.4 42l-0.9 10.2M32 41.8v10.8M36.6 42l0.9 10.2M41 43l1.7 8.6" fill="none" stroke="#4a3d2c" stroke-width="1.4" stroke-linecap="round" opacity="0.5" />
      <path d="M20.2 40.6l-3.4 3.6 4.4 1.2M43.8 40.6l3.4 3.6-4.4 1.2" fill="#cfa468" stroke="#4a3d2c" stroke-width="1.1" stroke-linejoin="round" stroke-opacity="0.45" />
      <rect x="24.4" y="40.2" width="15.2" height="3" rx="1.5" fill="#d8503a" />
      <path d="M25.4 46.9c4.6 1.4 8.6 1.4 13.2 0" fill="none" stroke="#d8503a" stroke-width="1.2" stroke-linecap="round" opacity="0.7" />
    </g>
    <g class="pet-prop pet-bucket">
      <ellipse cx="46.8" cy="45" rx="2.1" ry="2.9" transform="rotate(24 46.8 45)" fill="#cfa468" />
      <path d="M48.7 43.9c1.8-2.5 5.2-2.5 6.9 0" fill="none" stroke="#3b352c" stroke-width="1.3" stroke-linecap="round" opacity="0.6" />
      <path d="M48 44.3h8.3l-1 9.2c-2 .5-4.2 .5-6.3 0z" fill="#c39055" />
      <path d="M48.3 46.9h7.7M48.6 50.3h7.1" fill="none" stroke="#3b352c" stroke-width="1.1" stroke-linecap="round" opacity="0.5" />
    </g>
    <g class="pet-head">
      <path d="M32 9.6l2.9 4.6 4.6-3.2-.4 5.4 5.3-1-2.3 4.8 5.1 1.2-4 3.5 4 3.6-5.1 1.2 2.3 4.9-5.3-1.1.4 5.5-4.6-3.2-2.9 4.5-2.9-4.5-4.6 3.2.4-5.5-5.3 1.1 2.3-4.9-5.1-1.2 4-3.6-4-3.5 5.1-1.2-2.3-4.8 5.3 1-.4-5.4 4.6 3.2z" fill="#d8ad6e" />
      <path d="M20.5 17.5l3.4 4.4M43.5 17.5l-3.4 4.4M17 26.5l4.6 1.8M47 26.5l-4.6 1.8M19.5 35.5l4.2-1.2M44.5 35.5l-4.2-1.2M26.5 12.5l1.8 4.2M37.5 12.5l-1.8 4.2" fill="none" stroke="#3b352c" stroke-width="1.3" stroke-linecap="round" opacity="0.55" />
      <path d="M25.1 13.5c-1.8-3.5-1.4-6.8 1-9.7 1.8 2.6 2.1 5.6.9 8.9z" fill="#9db8dd" />
      <path d="M25 8.2l2.4 1M25.6 11l2.1.9" fill="none" stroke="#33415c" stroke-width="1" stroke-linecap="round" opacity="0.7" />
      <path d="M38.9 13.5c1.8-3.5 1.4-6.8-1-9.7-1.8 2.6-2.1 5.6-.9 8.9z" fill="#9db8dd" />
      <path d="M39 8.2l-2.4 1M38.4 11l-2.1.9" fill="none" stroke="#33415c" stroke-width="1" stroke-linecap="round" opacity="0.7" />
      <circle cx="32" cy="27" r="12.6" fill="#6b91c2" />
      <path d="M23.2 20.4l6.6 2M40.8 20.4l-6.6 2" fill="none" stroke="var(--pet-paper-ink)" stroke-width="2.8" stroke-linecap="round" />
      <g class="pet-eye">
        <ellipse cx="25.6" cy="26.4" rx="3.3" ry="3.9" fill="var(--pet-paper-ink)" />
        <circle cx="24.3" cy="24.7" r="1.45" fill="#ffffff" opacity="0.96" />
      </g>
      <g class="pet-eye">
        <ellipse cx="38.4" cy="26.4" rx="3.3" ry="3.9" fill="var(--pet-paper-ink)" />
        <circle cx="37.1" cy="24.7" r="1.45" fill="#ffffff" opacity="0.96" />
      </g>
      <path d="M32 29.4l-1.6 1.9h3.2z" fill="#33415c" opacity="0.9" />
      <path d="M25.8 32.2c4.1 3 8.3 3 12.4 0 .5 3.6-2.3 6.1-6.2 6.1s-6.7-2.5-6.2-6.1z" fill="var(--pet-paper-ink)" opacity="0.92" />
      <path d="M26.8 33.4q5.2 2.6 10.4 0v1.5q-5.2 2.2-10.4 0z" fill="#ffffff" />
      <path d="M25.9 33.2l1.3-2.9 1.5 2.5zM38.1 33.2l-1.3-2.9-1.5 2.5z" fill="#ffffff" />
      <ellipse cx="32" cy="36.9" rx="2.3" ry="1.2" fill="#d8503a" opacity="0.95" />
      <ellipse cx="20.9" cy="30.4" rx="2.2" ry="1.4" fill="#d8503a" opacity="0.35" />
      <ellipse cx="43.1" cy="30.4" rx="2.2" ry="1.4" fill="#d8503a" opacity="0.35" />
    </g>
    <g class="pet-prop pet-rare-mark">
      <path d="M52.6 12.6l1.3-2.8 1.3 2.8 2.8 1.3-2.8 1.3-1.3 2.8-1.3-2.8-2.8-1.3 2.8-1.3z" fill="var(--pet-aurora-bridge)" />
    </g>
    <g class="pet-reaction-marks">
      <path d="M10.5 18L7 15.6M9.5 24H5M11 30l-3.4 2.7" fill="none" stroke="var(--pet-signal)" stroke-width="2.4" stroke-linecap="round" />
      <path d="M54.5 27h4.2M53.5 32.5l3 2.4" fill="none" stroke="var(--pet-signal)" stroke-width="2.4" stroke-linecap="round" />
    </g>
  </g>
</svg>
```

フォーム固有モーション:

```css
.campus-pet--namahage[data-state="idle"] .pet-head {
  animation: campus_pet_namahage_breathe 3.8s var(--ease-standard) infinite;
}

.campus-pet--namahage[data-state="thinking"] .pet-rig {
  animation: campus_pet_namahage_stomp 680ms var(--ease-standard) infinite;
}

.campus-pet--namahage[data-state="done"] .pet-rare-mark,
.campus-pet--namahage[data-reaction="spark"] .pet-rare-mark {
  animation: campus_pet_rare_flash 620ms var(--ease-expressive) 2;
}

.campus-pet--namahage[data-state="clarify"] .pet-head {
  transform: translate3d(0, 1px, 0) scaleY(0.98);
}

.campus-pet--namahage[data-state="clarify"] .pet-eye {
  transform: scaleY(0.78);
}

@keyframes campus_pet_namahage_breathe {
  0%, 100% { transform: translate3d(0, 0, 0); }
  50% { transform: translate3d(0, -1px, 0); }
}

@keyframes campus_pet_namahage_stomp {
  0%, 100% { transform: translate3d(-1px, 0, 0) rotate(-1deg); }
  50% { transform: translate3d(1px, -2px, 0) rotate(1deg); }
}

@keyframes campus_pet_rare_flash {
  0%, 100% { opacity: 0.7; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.28); }
}
```

#### `yatagarasu` — 名前: 「八咫烏」

利用者支給リファレンス（yatagarasu.jpg・墨絵の八咫烏）をそのままペット化。構図の要は
**明るい日輪を背にした漆黒の烏のシルエット**で、暗背景の UI では日輪（`paper` の透過面＋朱の内輪＋
ひび割れ状の稲妻光線 = 参考絵の墨線・「バチバチ」の記号）が黒い体を逆光で立たせる。
**R11（利用者指示 2026-07-19）: この体は「バチバチかっこいい」を家族文法より優先**し、
丸い大瞳を**鋭い切れ長の銀眼（楔形＋小さな墨の瞳孔）**に置き換える（意図的逸脱。頬紅もなし）。
大きくギザギザに広げた両翼・逆立つ頭頂の羽根・体側の羽毛の逆立ち・鋼色の鋭い鉤嘴・**朱の太い吊り眉**・
朱の稲妻 3 条・尾羽の扇・そして**三叉の鉤爪を持つ三本足**（八咫烏の証・銀灰）。視線・嘴は正面（R10）。

```html
<svg class="campus-pet campus-pet--yatagarasu" data-state="idle" viewBox="0 0 64 64" aria-hidden="true">
  <g class="pet-shadow">
    <ellipse cx="32" cy="57" rx="13.5" ry="3.2" fill="var(--pet-text)" />
  </g>
  <g class="pet-rig">
    <g class="pet-prop pet-sun">
      <circle cx="32" cy="23.5" r="18" fill="none" stroke="var(--pet-paper)" stroke-width="1.6" opacity="0.18" />
      <circle cx="32" cy="23.5" r="16.5" fill="var(--pet-paper)" opacity="0.8" />
      <circle cx="32" cy="23.5" r="13.6" fill="none" stroke="#d8503a" stroke-width="1" opacity="0.5" />
      <path d="M32 2.6l1.6 3-2.2 2 1.2 2.4M46.8 5.9l-.6 3.2-2.8.9 1 2.6M56.4 16.6l-3 1.3.4 2.8-2.7.6M17.2 5.9l.6 3.2 2.8.9-1 2.6M7.6 16.6l3 1.3-.4 2.8 2.7.6M9.6 34.8l2.8-1.7 2 1.9M54.4 34.8l-2.8-1.7-2 1.9" fill="none" stroke="var(--pet-paper)" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round" opacity="0.5" />
    </g>
    <g class="pet-prop pet-wing-l">
      <path d="M25.5 31.5C18 30.5 12 26 10.2 18.5l4.2 2.2-.6-5.6 4.4 2.6.2-5.4 3.8 3.4 1.4-4.6 2.6 4.4c1.6 6-.4 12.4-5.9 16z" fill="#2e333d" stroke="#8a919e" stroke-width="0.7" stroke-opacity="0.5" />
      <path d="M14.8 16.9c1.9 4 2.1 8.1.7 12M19.6 14.6c1.7 4.6 1.7 9.2 0 13.4" fill="none" stroke="#8a919e" stroke-width="1" stroke-linecap="round" opacity="0.55" />
    </g>
    <g class="pet-prop pet-wing-r">
      <path d="M38.5 31.5c7.5-1 13.5-5.5 15.3-13l-4.2 2.2.6-5.6-4.4 2.6-.2-5.4-3.8 3.4-1.4-4.6-2.6 4.4c-1.6 6 .4 12.4 5.9 16z" fill="#2e333d" stroke="#8a919e" stroke-width="0.7" stroke-opacity="0.5" />
      <path d="M49.2 16.9c-1.9 4-2.1 8.1-.7 12M44.4 14.6c-1.7 4.6-1.7 9.2 0 13.4" fill="none" stroke="#8a919e" stroke-width="1" stroke-linecap="round" opacity="0.55" />
    </g>
    <g class="pet-body">
      <path d="M26.2 18.6l1-4.6 2 3.2 1.6-4.8 1.9 3.4 2-4 1.4 3.7 2.6-2.6-.6 4.4z" fill="#1f2228" />
      <path d="M32 17.8c6 0 10 3.9 10 9.8 0 2.5-.3 5-.9 7.5-1.3 5.9-4.2 9.6-9.1 9.6s-7.8-3.7-9.1-9.6c-.6-2.5-.9-5-.9-7.5 0-5.9 4-9.8 10-9.8z" fill="#1f2228" stroke="#8a919e" stroke-width="0.8" stroke-opacity="0.3" />
      <path d="M22.8 33l-3 1.8 2.5 1.2-2 2 3 .8z" fill="#1f2228" />
      <path d="M41.2 33l3 1.8-2.5 1.2 2 2-3 .8z" fill="#1f2228" />
      <path d="M25.4 22.4c1.6-2 3.8-3.1 6.4-3.1" fill="none" stroke="#8a919e" stroke-width="1.2" stroke-linecap="round" opacity="0.5" />
      <path d="M28.8 40l1.1 1.5 1.1-1.5M33.2 42.2l1 1.4 1-1.4M29.6 44.5l.9 1.3.9-1.3" fill="none" stroke="#8a919e" stroke-width="1" stroke-linecap="round" stroke-linejoin="round" opacity="0.5" />
      <path d="M39.5 43.8l8.6 1.6-5.2 2.6 4.4 3.2-6.2.8 2 3.8c-3.9-.6-6.9-3-8.2-6.6z" fill="#2e333d" stroke="#8a919e" stroke-width="0.7" stroke-opacity="0.4" />
      <path d="M41.2 45.9c2.1 1.3 3.7 3.1 4.6 5.4" fill="none" stroke="#8a919e" stroke-width="1" stroke-linecap="round" opacity="0.5" />
    </g>
    <g class="pet-head">
      <path d="M20.6 21.4l7.4 1.9M43.4 21.4l-7.4 1.9" fill="none" stroke="#d8503a" stroke-width="2.6" stroke-linecap="round" />
      <g class="pet-eye">
        <path d="M22 25.9l7.2-3.1c.7 1.1.9 2.4.5 3.7l-6.5 2.1c-.8-.7-1.2-1.6-1.2-2.7z" fill="#e8eaef" />
        <circle cx="27.1" cy="25.6" r="1.2" fill="var(--pet-paper-ink)" />
        <circle cx="26.3" cy="24.6" r="0.6" fill="#ffffff" opacity="0.95" />
      </g>
      <g class="pet-eye">
        <path d="M42 25.9l-7.2-3.1c-.7 1.1-.9 2.4-.5 3.7l6.5 2.1c.8-.7 1.2-1.6 1.2-2.7z" fill="#e8eaef" />
        <circle cx="36.9" cy="25.6" r="1.2" fill="var(--pet-paper-ink)" />
        <circle cx="36.1" cy="24.6" r="0.6" fill="#ffffff" opacity="0.95" />
      </g>
      <path d="M32 28l-3.2 1.5c-.3 1.6.2 3.4 1.4 5.1l1.8 2.4 1.8-2.4c1.2-1.7 1.7-3.5 1.4-5.1z" fill="#cfd4db" />
      <path d="M32 30.3v4.5" fill="none" stroke="#9aa1ad" stroke-width="0.9" stroke-linecap="round" opacity="0.7" />
      <path d="M30.3 34.6l1.7 2.4 1.7-2.4" fill="none" stroke="#9aa1ad" stroke-width="0.9" stroke-linecap="round" stroke-linejoin="round" opacity="0.8" />
    </g>
    <g class="pet-spark">
      <path d="M6.4 7.4l4.6-1.6-1.9 3.7 4-1-5.4 4.7 1.3-3.4-4 1z" fill="#d8503a" opacity="0.92" />
      <path d="M57.6 9.6l-4-1.4 1.7 3.2-3.5-.9 4.7 4.1-1.1-3 3.5.9z" fill="#d8503a" opacity="0.8" />
      <path d="M8.6 39.2l3.2-1.1-1.3 2.6 2.8-.7-3.8 3.3.9-2.4-2.8.7z" fill="#d8503a" opacity="0.7" />
    </g>
    <g class="pet-legs">
      <path d="M26 47.8l-1.8 4.6M32 48.6v4.8M38 47.8l1.8 4.6" fill="none" stroke="#c9ccd4" stroke-width="2.2" stroke-linecap="round" />
      <path d="M24.2 52.4l-2 1.5M24.2 52.4l.2 2.2M24.2 52.4l2 1M32 53.4l-1.9 1.4M32 53.4v2.2M32 53.4l1.9 1.4M39.8 52.4l-2 1M39.8 52.4l-.2 2.2M39.8 52.4l2 1.5" fill="none" stroke="#c9ccd4" stroke-width="1.5" stroke-linecap="round" />
    </g>
    <g class="pet-reaction-marks">
      <path d="M9 24.5l4.2-1.4-1.7 3.3 3.6-.9-4.9 4.2 1.2-3-3.6.9z" fill="#d8503a" />
      <circle cx="55.5" cy="24" r="1.6" fill="var(--pet-paper)" opacity="0.9" />
    </g>
  </g>
</svg>
```

フォーム固有モーション:

```css
.campus-pet--yatagarasu[data-state="idle"] .pet-sun {
  animation: campus_pet_yata_sun 4.6s var(--ease-standard) infinite;
}

.campus-pet--yatagarasu[data-state="thinking"] .pet-wing-l {
  transform-origin: 88% 92%;
  animation: campus_pet_yata_flap_l 620ms var(--ease-standard) infinite;
}

.campus-pet--yatagarasu[data-state="thinking"] .pet-wing-r {
  transform-origin: 12% 92%;
  animation: campus_pet_yata_flap_r 620ms var(--ease-standard) infinite;
}

.campus-pet--yatagarasu[data-state="done"] .pet-sun,
.campus-pet--yatagarasu[data-reaction="spark"] .pet-sun {
  animation: campus_pet_yata_sun 620ms var(--ease-expressive) 2;
}

.campus-pet--yatagarasu[data-state="clarify"] .pet-head {
  transform: translate3d(0, 1px, 0) scaleY(0.98);
}

.campus-pet--yatagarasu[data-state="clarify"] .pet-eye {
  transform: scaleY(0.78);
}

@keyframes campus_pet_yata_sun {
  0%, 100% { opacity: 0.8; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.04); }
}

@keyframes campus_pet_yata_flap_l {
  0%, 100% { transform: rotate(2deg); }
  50% { transform: rotate(-9deg); }
}

@keyframes campus_pet_yata_flap_r {
  0%, 100% { transform: rotate(-2deg); }
  50% { transform: rotate(9deg); }
}
```

### §12-5. 状態別ポーズの確定

| 状態 | 共通ポーズ | フォーム差分 |
|---|---|---|
| `summoning` | 煙が先に 0〜640ms 再生。ペット本体は 54% まで不可視、下から 8px・scale 0.72 で現れ、最後に等倍へ戻る。 | `namahage` は rare mark だけ 1 回点く。reduced-motion は煙と本体を 220ms opacity fade のみにする。 |
| `idle` | 4.8s の 1.6px bob と瞬き。会話の邪魔をしない生存感。 | robo は耳フィンがゆっくり明滅、sarutahiko は光の長柄が 2deg 揺れる、akita は尻尾、gotenmari は球体が 2deg 揺れる、namahage は頭だけ 1px 呼吸、yatagarasu は日輪がゆっくり明滅。 |
| `thinking` | 1.15s の左右 2px scout。アプリと一緒に探している感じ。 | robo は耳フィン scan、sarutahiko は光の長柄で道を示す、akita は鼻先を下げてくんくん、gotenmari は小さく跳ねる、namahage は小さな足踏み、yatagarasu は両翼を小刻みに羽ばたかせる。 |
| `clarify` | 動きを止めてユーザーをじっと見る。かわいい軸は `pet-head` を -7deg 傾け、目をやや縦長にする。 | sarutahiko / namahage は首を傾けず、頭を 1px 下げて `scaleY(0.98)`、目を `scaleY(0.78)` にし、小さく顎を引いて見据える。gotenmari は球体全体を -5deg にする。 |
| `done` | 860ms の小さな喜び bounce。その後ストア側で約 4 秒後 `idle` へ戻す。 | akita は尻尾を短く連続 wag、gotenmari は 1 回高く跳ねる、sarutahiko は光の長柄を掲げる、robo は耳フィン ping、namahage は rare mark が 2 回点く、yatagarasu は日輪が 2 回強く明滅。 |
| `hidden` | DOM ごと外す。復帰時に召喚演出はしない。 | なし。 |

`statusStep` 差分は必須実装にしない。将来入れる場合は `data-step="web_search|get_docs"` を付け、`thinking` の中で props の向きだけ変える。新規アニメーションは増やさず既存 `thinking` を再利用する。

### §12-6. 煙（ドロン）演出

煙はフォーム非依存。出現・交代・退場に同じ SVG を重ねる。色は `paper` / `text-muted` の半透明だけを使い、雲や粒子を増やしすぎない。実装では `.campus-pet-smoke` をペット SVG の前面に 720ms mount し、ペット本体の `data-state="summoning"` と同時に再生する。

```html
<svg class="campus-pet-smoke" viewBox="0 0 72 72" aria-hidden="true">
  <g class="smoke-ring">
    <ellipse cx="36" cy="51" rx="18" ry="5.2" fill="var(--pet-paper)" opacity="0.1" />
  </g>
  <circle class="smoke-puff smoke-puff--a" cx="25" cy="42" r="8.5" fill="var(--pet-paper)" />
  <circle class="smoke-puff smoke-puff--b" cx="38" cy="37" r="10" fill="var(--pet-paper)" />
  <circle class="smoke-puff smoke-puff--c" cx="49" cy="44" r="7.5" fill="var(--pet-muted)" />
  <circle class="smoke-puff smoke-puff--d" cx="31" cy="51" r="6" fill="var(--pet-muted)" />
  <circle class="smoke-dot smoke-dot--a" cx="18" cy="36" r="2.2" fill="var(--pet-paper)" />
  <circle class="smoke-dot smoke-dot--b" cx="55" cy="35" r="2" fill="var(--pet-paper)" />
</svg>
```

```css
.campus-pet-smoke {
  position: absolute;
  inset: -8px;
  width: calc(100% + 16px);
  height: calc(100% + 16px);
  pointer-events: none;
  overflow: visible;
}

.campus-pet-smoke .smoke-puff,
.campus-pet-smoke .smoke-dot,
.campus-pet-smoke .smoke-ring {
  transform-box: fill-box;
  transform-origin: center;
}

.campus-pet-smoke .smoke-ring {
  animation: campus_pet_smoke_ring 680ms var(--ease-expressive) both;
}

.campus-pet-smoke .smoke-puff--a {
  animation: campus_pet_smoke_a 680ms var(--ease-expressive) both;
}

.campus-pet-smoke .smoke-puff--b {
  animation: campus_pet_smoke_b 720ms var(--ease-expressive) both;
}

.campus-pet-smoke .smoke-puff--c {
  animation: campus_pet_smoke_c 680ms var(--ease-expressive) both;
}

.campus-pet-smoke .smoke-puff--d {
  animation: campus_pet_smoke_d 620ms var(--ease-expressive) both;
}

.campus-pet-smoke .smoke-dot--a {
  animation: campus_pet_smoke_dot_a 620ms var(--ease-expressive) both;
}

.campus-pet-smoke .smoke-dot--b {
  animation: campus_pet_smoke_dot_b 620ms var(--ease-expressive) both;
}

@keyframes campus_pet_smoke_ring {
  0% { opacity: 0; transform: translate3d(0, 4px, 0) scale(0.62); }
  38% { opacity: 0.28; transform: translate3d(0, 0, 0) scale(1); }
  100% { opacity: 0; transform: translate3d(0, -1px, 0) scale(1.18); }
}

@keyframes campus_pet_smoke_a {
  0% { opacity: 0; transform: translate3d(6px, 9px, 0) scale(0.38); }
  34% { opacity: 0.34; transform: translate3d(0, 0, 0) scale(1); }
  100% { opacity: 0; transform: translate3d(-11px, -10px, 0) scale(1.26); }
}

@keyframes campus_pet_smoke_b {
  0% { opacity: 0; transform: translate3d(0, 10px, 0) scale(0.42); }
  32% { opacity: 0.38; transform: translate3d(0, 0, 0) scale(1); }
  100% { opacity: 0; transform: translate3d(0, -13px, 0) scale(1.34); }
}

@keyframes campus_pet_smoke_c {
  0% { opacity: 0; transform: translate3d(-5px, 8px, 0) scale(0.38); }
  34% { opacity: 0.28; transform: translate3d(0, 0, 0) scale(1); }
  100% { opacity: 0; transform: translate3d(12px, -9px, 0) scale(1.24); }
}

@keyframes campus_pet_smoke_d {
  0% { opacity: 0; transform: translate3d(0, 6px, 0) scale(0.36); }
  42% { opacity: 0.22; transform: translate3d(0, 0, 0) scale(1); }
  100% { opacity: 0; transform: translate3d(-2px, -7px, 0) scale(1.16); }
}

@keyframes campus_pet_smoke_dot_a {
  0% { opacity: 0; transform: translate3d(7px, 7px, 0) scale(0.3); }
  38% { opacity: 0.42; transform: translate3d(0, 0, 0) scale(1); }
  100% { opacity: 0; transform: translate3d(-9px, -8px, 0) scale(0.72); }
}

@keyframes campus_pet_smoke_dot_b {
  0% { opacity: 0; transform: translate3d(-6px, 7px, 0) scale(0.3); }
  38% { opacity: 0.4; transform: translate3d(0, 0, 0) scale(1); }
  100% { opacity: 0; transform: translate3d(8px, -9px, 0) scale(0.72); }
}

@media (prefers-reduced-motion: reduce) {
  .campus-pet-smoke .smoke-ring,
  .campus-pet-smoke .smoke-puff,
  .campus-pet-smoke .smoke-dot {
    animation: campus_pet_smoke_reduce 220ms ease-out both !important;
  }

  @keyframes campus_pet_smoke_reduce {
    from { opacity: 0; transform: none; }
    to { opacity: 0.18; transform: none; }
  }
}
```

### §12-7. 配置・サイズ

配置はチャットシェル内 `absolute`。`fixed` は禁止。実装時は `ChatView.vue` の `.chat-shell` 直下に、サイドバーを避ける overlay layer を置く。

確定値:

```css
.campus-pet-layer {
  position: absolute;
  inset: 0;
  z-index: 30;
  pointer-events: none;
}

@media (min-width: 1024px) {
  .campus-pet-layer {
    left: 17.5rem;
  }
}

.campus-pet-button {
  position: absolute;
  right: max(1rem, calc((100% - min(48rem, calc(100% - 2rem))) / 2 + 0.25rem));
  bottom: calc(var(--pet-composer-clearance, 6.25rem) + env(safe-area-inset-bottom));
  display: grid;
  width: 3.5rem;
  height: 3.5rem;
  padding: 0;
  place-items: center;
  border: 0;
  background: transparent;
  color: var(--pet-text);
  pointer-events: auto;
  touch-action: manipulation;
}

@media (max-width: 420px) {
  .campus-pet-button {
    right: 0.875rem;
    bottom: calc(var(--pet-composer-clearance, 5.875rem) + env(safe-area-inset-bottom));
    width: 3.25rem;
    height: 3.25rem;
  }
}

.campus-pet-layer--protect-controls .campus-pet-button {
  width: 2.75rem;
  height: 2.75rem;
  bottom: calc(var(--pet-composer-clearance, 6.25rem) + 4.25rem + env(safe-area-inset-bottom));
  opacity: 0.74;
  pointer-events: none;
}
```

運用ルール:

- 通常は 56px。390px 幅以下は 52px。`protect-controls` 時だけ 44px。
- `--pet-composer-clearance` は composer 実高 + 12px を入れる。未計測時は 100px 相当で破綻しない。
- composer 上部右隅に置くが、composer 本体には 12px 以上重ねない。
- `clarificationActive` または `mapInteractive` が true の間は `.campus-pet-layer--protect-controls` を付ける。確認フォーム・地図カード操作を絶対に遮らないため、この間だけペットのタップ/ダブルタップは無効にする。
- ペット本体以外の layer / smoke は常に `pointer-events: none`。

### §12-8. シングルタップのリアクション

シングルタップは 3 種からランダム。音は出さない。

| reaction | 見た目 | 実装 |
|---|---|---|
| `spark` | 右上または周囲の小さな点・星がふわっと出る。 | `data-reaction="spark"` を 720ms 付与。全フォームの `.pet-reaction-marks` が発火。 |
| `nod` | こちらに軽く会釈する。 | `data-reaction="nod"` を 620ms 付与。`.pet-head` が 9deg → -5deg。 |
| `peek` | 少し上に伸びて戻る。 | `data-reaction="peek"` を 720ms 付与。`.pet-rig` が -3px / scale 1.04。 |

フォーム固有の推奨比率:

- robo: `spark` 50%、`nod` 30%、`peek` 20%。
- sarutahiko: `nod` 45%、`spark` 35%、`peek` 20%。
- akita: `peek` 45%、`spark` 35%、`nod` 20%。
- gotenmari: `spark` 45%、`peek` 40%、`nod` 15%。
- namahage: `spark` 55%、`peek` 30%、`nod` 15%。
- yatagarasu: `spark` 55%、`peek` 25%、`nod` 20%。

### §12-9. About ダイアログ内の意匠

#### 解禁前の隠しボタン

About ダイアログの最下部、閉じるボタン行の左端に 28px の小さな煙印だけを置く。説明文は出さない。存在は分かりにくいが、ボタンとしての a11y は保つ。

```html
<button type="button" class="about-pet-secret" aria-label="小さなおまけを開く">
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M7.4 14.2c-1.8 0-3.1-1-3.1-2.4 0-1.5 1.4-2.5 3.2-2.5 0.4-2.3 2.4-3.8 5-3.8 2.8 0 4.8 1.8 5 4.3 1.4 0.2 2.4 1.1 2.4 2.3 0 1.4-1.3 2.2-3 2.2H7.4z" fill="currentColor" opacity="0.42" />
    <path d="M8 17.2h7.8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" opacity="0.42" />
  </svg>
</button>
```

```css
.about-pet-secret {
  display: grid;
  width: 2.75rem;
  min-width: 2.75rem;
  height: 2.75rem;
  place-items: center;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-dim);
  opacity: 0.55;
  transition:
    opacity var(--motion-fast) var(--ease-standard),
    background-color var(--motion-fast) var(--ease-standard),
    color var(--motion-fast) var(--ease-standard),
    transform var(--motion-fast) var(--ease-standard);
}

.about-pet-secret svg {
  width: 1rem;
  height: 1rem;
}

.about-pet-secret:hover,
.about-pet-secret:focus-visible {
  background: var(--fill-hover, rgba(244, 243, 237, 0.055));
  color: var(--color-text-muted);
  opacity: 1;
}

.about-pet-secret:active {
  transform: scale(0.97);
}
```

#### 解禁後の「キャンパスペット」行

About 本文と QR の後、閉じるボタン行の前に 1 行だけ追加する。カードにはせず、既存の研究室リンクや QR セクションと同じ「境界線 + 行」扱いにする。

```html
<section class="about-pet-row" aria-label="キャンパスペット">
  <div class="about-pet-row__copy">
    <span class="about-pet-row__mark" aria-hidden="true">
      <svg viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="7.2" fill="currentColor" opacity="0.22" />
        <path d="M8.2 12.8c1.9 1.7 5.7 1.7 7.6 0" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
        <path d="M9 9.3h0.1M15 9.3h0.1" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" />
      </svg>
    </span>
    <span>
      <span class="about-pet-row__title">キャンパスペット</span>
      <span class="about-pet-row__meta">チャットの隅で待っています</span>
    </span>
  </div>
  <div class="about-pet-row__actions">
    <button type="button" class="about-pet-toggle" role="switch" aria-checked="true">
      <span class="about-pet-toggle__knob"></span>
    </button>
    <button type="button" class="about-pet-doron">ドロン</button>
  </div>
</section>
```

```css
.about-pet-row {
  display: flex;
  min-height: 3.25rem;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-top: 1.25rem;
  padding-top: 1rem;
  border-top: 1px solid var(--color-edge);
}

.about-pet-row__copy {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.625rem;
}

.about-pet-row__mark {
  display: grid;
  width: 2rem;
  height: 2rem;
  flex: 0 0 2rem;
  place-items: center;
  border: 1px solid var(--color-edge);
  border-radius: var(--radius-sm);
  color: var(--color-signal-soft);
}

.about-pet-row__mark svg {
  width: 1.25rem;
  height: 1.25rem;
}

.about-pet-row__title,
.about-pet-row__meta {
  display: block;
}

.about-pet-row__title {
  color: var(--color-text);
  font-size: 0.875rem;
  font-weight: 650;
  line-height: 1.4;
}

.about-pet-row__meta {
  color: var(--color-text-dim);
  font-size: 0.75rem;
  line-height: 1.45;
}

.about-pet-row__actions {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 0.5rem;
}

.about-pet-toggle {
  position: relative;
  width: 3.25rem;
  min-width: 3.25rem;
  height: 2.75rem;
  border: 0;
  border-radius: 9999px;
  background: transparent;
}

.about-pet-toggle::before {
  position: absolute;
  inset: 0.45rem 0.25rem;
  border: 1px solid var(--color-edge-strong);
  border-radius: 9999px;
  background: var(--color-panel);
  content: "";
}

.about-pet-toggle[aria-checked="true"]::before {
  border-color: rgba(255, 118, 87, 0.34);
  background: color-mix(in srgb, var(--color-raised) 88%, var(--color-signal) 12%);
}

.about-pet-toggle__knob {
  position: absolute;
  top: 0.71rem;
  left: 0.52rem;
  width: 1.32rem;
  height: 1.32rem;
  border-radius: 9999px;
  background: var(--color-text-muted);
  transition: transform var(--motion-base) var(--ease-expressive);
}

.about-pet-toggle[aria-checked="true"] .about-pet-toggle__knob {
  background: var(--color-signal);
  transform: translate3d(1.35rem, 0, 0);
}

.about-pet-doron {
  min-height: 2.75rem;
  border: 1px solid var(--color-edge);
  border-radius: 9999px;
  background: transparent;
  padding: 0 0.82rem;
  color: var(--color-text-muted);
  font-size: 0.8125rem;
  font-weight: 620;
  transition:
    background-color var(--motion-fast) var(--ease-standard),
    border-color var(--motion-fast) var(--ease-standard),
    color var(--motion-fast) var(--ease-standard),
    transform var(--motion-fast) var(--ease-standard);
}

.about-pet-doron:hover,
.about-pet-doron:focus-visible {
  border-color: var(--color-edge-strong);
  background: var(--fill-hover, rgba(244, 243, 237, 0.055));
  color: var(--color-text);
}

.about-pet-doron:active {
  transform: scale(0.97);
}

@media (prefers-reduced-motion: reduce) {
  .about-pet-secret,
  .about-pet-toggle__knob,
  .about-pet-doron {
    transition: none !important;
  }

  .about-pet-secret:active,
  .about-pet-doron:active {
    transform: none;
  }
}
```

### §12-10. 名前案

| id | 名前案 | 口頭での呼び方 |
|---|---|---|
| `robo` | ぴこ | 「ぴこ」 |
| `sarutahiko` | みちかぜ | 「みちかぜ」 |
| `akita` | こまち | 「こまち」 |
| `gotenmari` | てまりん | 「てまりん」 |
| `namahage` | ガオウ | 「ガオウ」 |
| `yatagarasu` | 八咫烏 | 「やたがらす」 |

名称は利用者が最終確定する。実装時は `formNames` の初期値としてこの案を入れ、後から文言だけ差し替えられる構造にする。
