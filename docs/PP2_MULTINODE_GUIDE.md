# PP=2 マルチノード vLLM 技術解説と構築手順（ibera + nubia）

- 版: v2.0（2026-07-18, Fable 改稿 — 利用者の学習用に全面的に噛み砕いた版。実測値・コマンド・構成は v1.0 から変更なし）
  - v1.0（2026-07-18, Fable 執筆。FR-34 PoC 全合格の実測に基づく）
- 対象読者: 本プロジェクトの利用者。**「Ray は初めて聞いた」「vLLM は Ollama より速くて同時リクエストに強い、くらいの理解」「KV キャッシュの理解は浅い」**という前提で、後から見返して自力で再現・復旧できることを目的とする
- 関連: `infra/pp2/README.md`(コマンドと全引数の正)、`docs/AGENT_REACT.md` §0-2/§1/§6-2(裁定と実測値)

**この文書の読み方**

- 第 I 部(仕組み編・§1〜§7): ibera と nubia の間で技術的に何が起きているのかを、前提知識ゼロから積み上げて説明する
- 第 II 部(構築編・§8〜§12): **§8 が「構築を始める前にあるべき状態と、その作り方」**、**§9 が「その状態の上での構築手順と、各手順で何が起きているか」**
- 障害対応で急いでいるときは §10(本番運用)と §11(トラブルシュート)へ直行してよい

---

# 第 I 部: 仕組み編

## 1. まず全体像 — 何を作ったのか

一言でいうと:

> **1 台の GPU には収まらない大きなモデル(Gemma 4 31B)を、家庭用 LAN でつないだ 2 台の GPU マシンに「前半の層・後半の層」で分担させ、外からは今までどおり 1 台のサーバーに見せる**構成。

```
来場者のブラウザ
   │ 質問
   ▼
backend（campus-guide-agent）
   │ http://127.0.0.1:8000/v1 …… 外から見える生成サーバーはこれ 1 つだけ
   ▼
[ibera] RTX 3090 Ti 24GB
   ├─ APIServer  … 受付。リクエストを受けて SSE で答えを返す
   ├─ EngineCore … 司令塔。どのリクエストをいつ・どこまで計算するか決める
   └─ rank0      … モデル「前半の層」の GPU 計算
   │
   │  家庭用 LAN（1GbE）…… ここを渡るのは 1 トークンあたり約 10KB だけ
   ▼
[nubia] RTX 3090 24GB
   └─ rank1      … モデル「後半の層」の GPU 計算 → 次の 1 トークンが決まる
```

最低限の用語をここで押さえておく:

- **トークン**: LLM が文章を扱う最小単位。日本語だとおおむね 1〜2 文字で 1 トークン。LLM の仕事は「次の 1 トークンを予想する」ことの繰り返し。
- **層(レイヤー)**: モデルの中身は同じ形の計算ブロックが数十段積み重なったもの。文章は 1 層目から最終層まで順に通り抜けて、最後に「次のトークン」が決まる。**順に通り抜ける**という性質が、後述の「前半・後半に分ける」作戦を可能にする。
- **31B**: パラメータ(モデルの重み)が約 310 億個あるという意味。**w4a16** は重みを 4bit 整数に圧縮(量子化)して持つ形式で、それでも重みだけで約 17GB ある。

---

## 2. なぜ 1 台では動かないのか — VRAM の算数

すべての出発点は **24GB という VRAM の壁**にある。

### 2-1. GPU で LLM を動かすとき、VRAM は 3 つに分かれる

| 用途 | 内容 | Gemma 4 31B (w4a16) の場合 |
|---|---|---|
| モデル重み | パラメータ本体。固定費 | 約 17GB |
| **KV キャッシュ** | 会話の長さに比例して増える作業領域(次項) | 残り VRAM 次第 |
| その他 | 計算途中のデータ・CUDA のバッファ類 | 1〜2GB |

重みは載せた瞬間に決まる固定費なので、勝負を分けるのは 2 行目の **KV キャッシュ**である。

### 2-2. KV キャッシュを噛み砕く

LLM が「次の 1 トークン」を予想するとき、モデル内部では**それまでの全トークンを毎回見返す**処理(attention)が全層で走る。見返すために、各トークンは層ごとに

- **K (Key)**: 検索用の索引
- **V (Value)**: 索引が当たったときに取り出す中身

という 2 つの数値ベクトルに変換される。この変換結果は同じトークン・同じ層なら何度計算しても同じ。それなのに 1 トークン生成するたびに全部作り直すのは無駄なので、**一度計算した K と V を VRAM に貯めておく**。これが KV キャッシュである。

> たとえ: 本を読みながら「要点メモ」を貯めていくイメージ。次のページを理解するのに毎回 1 ページ目から読み直さずに済むのはメモがあるから。そして**メモ棚の大きさ(空き VRAM)が、一度に扱える本の厚さ(コンテキスト窓)を決める**。

ここから 3 つの帰結が出る:

1. KV キャッシュは**会話コンテキストの長さに比例して線形に増える**(1 トークンあたり、ざっくり「層数 × 2(KとV) × 隠れ次元 × データ型のバイト数」。式の細部より「トークン数に比例」が重要)。
2. コンテキスト窓を広く取りたければ、**KV 用の空き VRAM がそれだけ必要**。
3. 生成が速いのはキャッシュがあるから。逆に言うとキャッシュを捨てると読み直し(再計算)になる(§6-1 の prefix caching に効いてくる)。

### 2-3. 単カードで実際に起きたこと — 「2816 問題」

31B を ibera(24GB)1 枚に載せると、重み 17GB を引いた残りは 5GB 程度。ここに張れた KV キャッシュは **`max-model-len 2816`(約 2,800 トークン)が限界**だった(2026-07-12 実測。`ARCHITECTURE.md` v0.3 の撤去記録)。

2,800 トークンでは「システムプロンプト＋会話履歴＋検索結果＋回答」がまともに入らない。とりわけ FR-34 の ReAct ハーネスは観測を蓄積しながら探索する(＝プロンプトがどんどん伸びる)ため、この窓では成立しない。これが一時 12B へ後退した理由であり、2 台目(nubia)を使う動機になった。

### 2-4. 2 台に分けるとどうなるか

モデルの層を半分ずつ 2 枚のカードに置くと、各カードの重み負担は約 8.5GB に半減し、**各カードに 13GB 級の KV 領域が生まれる**。これで `max-model-len 16384`(16k トークン、単カード比 5.8 倍)が張れた。

実測(2026-07-18 PoC): 両カードとも VRAM 使用 23.2GB / 24.5GB で綺麗に均等。15,009 トークンの実プロンプトを受け付けることを確認済み。

---

## 3. 2 台で 1 つのモデルを動かす 3 つの方式

複数 GPU で 1 モデルを動かす方式は大きく 3 つあり、**どれが使えるかは GPU 間をつなぐ配線の速さで決まる**。

ibera–nubia 間は 1GbE の家庭用 LAN(実効 ~110MB/s)。データセンターで使われる NVLink(数百 GB/s)の **3〜4 桁下**である。この制約がすべてを決めた。

### 3-1. データ並列(DP) — 前提を満たせず不可

モデルの**完全なコピー**を各 GPU に置き、リクエストを振り分ける方式(レジを 2 台に増やすイメージ)。処理量は増えるが「カード 1 枚にモデル全体が載る」ことが前提。31B は 24GB に載らないので不可。

### 3-2. テンソル並列(TP) — LAN では不成立

**1 つの層の中の巨大な行列計算**を 2 枚で半分ずつ担当する方式。1 枚あたりの重みは半分になるが、半分ずつの計算結果は不完全なので、**全層で・毎トークン、部分結果の答え合わせ(all-reduce という集団通信)が必要**になる。

> たとえ: 2 人で 1 枚の計算用紙を左右半分ずつ埋めるやり方。1 行終わるたびに相手と突き合わせが要る。同じ部屋(NVLink)なら囁けば済むが、電話回線(LAN)越しだと突き合わせのたびに待ちが発生する。

31B は層が数十段あるので、突き合わせは「層数 × トークン数」回。NVLink や同一マザーボード上の PCIe を前提にした方式で、1GbE 越しでは通信が支配的になり実用にならない。

### 3-3. パイプライン並列(PP) — 採用

層の積み重なりを「前半グループ／後半グループ」に**層の境界でスパッと**切り、前半を ibera、後半を nubia に置く方式。工場の 2 工程ラインと同じ。

```
リクエスト → [ibera: 層 1〜N/2] ─(LAN: activation 転送)→ [nubia: 層 N/2+1〜N] → 次トークン
```

境界をまたぐデータは **activation** だけ。activation とは層と層の間を流れる中間データで、「ここまでの文章をモデルなりに理解した状態」を表す数千個の数値の束(ベクトル)。1 トークンあたり約 10KB しかない。

算数で確かめる: 生成速度 37.9 トークン/秒 × 10KB ≒ **0.4MB/s**。1GbE の実効 110MB/s の 0.4% であり、まったく問題にならない。これが「LAN 越しでも PP なら成立する」理由である。TP との違いは「毎層答え合わせ」か「境界 1 回の受け渡し」かの違い、と覚えればよい。

### 3-4. PP の代償 — バブルとレイテンシ

PP はタダではない。1 トークン作るのに必ず「ibera で計算 → LAN 転送 → nubia で計算」という直列の旅程を通るため、**1 リクエスト単発の応答速度は単カードよりやや悪化**する。また 1 個流しだと、片方が計算している間もう片方は暇になる(**パイプラインバブル**)。

vLLM は複数リクエストを交互に流し込む(マイクロバッチ)ことで、両工程を同時に働かせてバブルを埋める。実測がその効果を示している:

- 1 並列デコード **37.9 tok/s**(読み上げ速度としては十分速い)
- 4 並列合算 **67.8 tok/s**(1.79 倍 — バブルが埋まり、並列でちゃんとスケールする)
- TTFT(最初のトークンが出るまでの時間)2.0 秒 @2k プロンプト

---

## 4. 登場ソフトウェアの役割 — vLLM・Ray・Docker・通信ライブラリ

### 4-1. vLLM — 推論サーバー本体(なぜ Ollama より速いのか)

「Ollama より速くて同時リクエストに強い」という理解は正しい。その中身は主に 2 つ:

1. **PagedAttention**: KV キャッシュ(§2-2)を OS のメモリ管理のように**固定サイズのブロック(ページ)単位**で貸し出す。会話ごとに大きな連続領域を予約する方式だと隙間だらけになるが、ページ方式なら詰めて使える。→ 同じ VRAM でより多くの会話を同時に抱えられる。
2. **continuous batching**: 誰かの生成が終わるのを待ってから次を始めるのではなく、**トークン 1 個を作るステップ単位で相席**させる。途中参加・途中離脱が自由な乗り合いバス。

この構成での vLLM の役割は「受付(APIServer)・司令塔(EngineCore)・GPU 計算(rank0/rank1)」の全部。**2 台への分散配置だけを次項の Ray に頼む**。さらに本プロジェクトでは prefix caching と guided JSON(§6)が決定的に効いている。

### 4-2. Ray — 「2 台を 1 台に見せる」土台(初めての人向け)

Ray は Python 向けの分散処理フレームワークで、本来は機械学習の学習ジョブや大規模データ処理を多数のマシンに広げるためのもの。**今回の使い方はその最小限**で、「2 台のマシンを 1 台の大きなコンピュータに見せかける」ことだけを担う。

登場する概念は 3 つだけ:

| 概念 | 動く場所 | 役割 |
|---|---|---|
| **head** | ibera | クラスタの**台帳**(GCS = Global Control Store)を持つ。「どのマシンに GPU が何枚あるか」「どのプロセスがどこで生きているか」を一元管理 |
| **worker** | nubia | 常駐の現場係(**raylet**)が head に「うちには GPU 1 枚あります」と自己申告して参加し、head から頼まれたプロセスを自ノードで起動する |
| **アクタ** | 両方 | Ray がどこかのノードに配置した常駐プロセスの呼び名 |

vLLM から見た Ray は「**GPU 1 枚つきの働き手を 2 人ください、と頼むと、台帳を見て適切なマシンに配置してくれる派遣元**」である。vLLM 自身は ibera と nubia の区別を知らないし、知る必要がない。

- 「1 台に見えている」ことの確認 = ibera で `ray status` を実行して **2 nodes / GPU 2.0** と出ること。
- **重要な注意**: Ray の台帳にある GPU 数は worker が**参加時に自己申告した値**で、いま現在 GPU が健康かどうかは保証しない。この性質が §7 罠#3(NVML 剥がれ)を厄介にしている。

### 4-3. Docker と `--network host`

両ノードのプロセスはすべて Docker コンテナの中で動くが、通常のコンテナはホストと別の仮想ネットワークに入り、NAT(番号変換)を挟んで外と話す。マンションの内線番号のようなもので、外から直接はかけられない。

Ray や後述の NCCL は「**自分の IP:ポートを相手に教えて、直接つなぎに来させる**」動きを多用するため、内線番号(コンテナ内 IP)を教えてしまうと相手が到達できず破綻する。そこで両ノードとも **`--network host`**(コンテナがホストの LAN IP をそのまま使う設定)で動かし、2 台のホスト同士の素の TCP 通信にしている。

### 4-4. 通信の 3 層 — c10d・NCCL・Gloo(宅配業者の使い分け)

rank0(ibera)と rank1(nubia)が協調するために、性格の違う 3 種類の通信が使われる:

| 名前 | 役割 | たとえ |
|---|---|---|
| **c10d TCPStore** | 起動時の**待ち合わせ**(ランデブー)。rank0 が待ち合わせ場所となる TCP サーバーを開き、全 rank がそこに集合して互いの所在(IP:ポート)を交換する | 集合場所の掲示板 |
| **NCCL** | **GPU データ便**。activation の転送を担う NVIDIA 純正ライブラリ。NVLink がある環境ではそれを使い、無ければ TCP ソケットに自動フォールバック(今回は TCP) | 大口の宅配便 |
| **Gloo** | CPU 側の**事務連絡便**。制御メッセージ・メタデータ交換 | 事務連絡のメール |

起動スクリプトは `NCCL_SOCKET_IFNAME` / `GLOO_SOCKET_IFNAME` で**使う NIC を LAN 側に固定**している(Docker が作る仮想 NIC を誤って選ぶ事故の予防)。また、この「待ち合わせ」の段階こそが §7 罠#2「ポート 100 事件」の現場である。

### 4-5. serve 後に生きているプロセス一覧

ibera で `vllm serve --distributed-executor-backend ray --pipeline-parallel-size 2` を実行すると、次のプロセス群が生まれる(**rank** = 分散処理におけるプロセスの背番号):

| プロセス | 場所 | 役割 |
|---|---|---|
| APIServer | ibera | OpenAI 互換 HTTP(:8000)。受付・SSE 返却 |
| EngineCore | ibera | 司令塔。バッチ編成・KV ブロック管理・各 rank への指示 |
| RayWorkerProc rank0 | ibera(Ray アクタ) | 層前半の GPU 計算 |
| RayWorkerProc rank1 | nubia(Ray アクタ) | 層後半の GPU 計算 |

バックエンド(campus-guide-agent)から見えるのは `ibera:8000` の 1 エンドポイントだけで、背後に 2 台いることは完全に隠蔽される。`VLLM_BASE_URL` の差し替えだけで 12B⇄31B を移行できるのはこのため。

---

## 5. リクエストの一生 — 1 トークンの旅

`POST /v1/chat/completions` が届いてから答えが流れてくるまで:

1. **受付**: APIServer がプロンプトを**トークナイズ**(文章→トークン ID 列に変換)し、EngineCore へ渡す。
2. **スケジューリング**: EngineCore が KV キャッシュのブロック(ページ)を割り当て、今ステップで計算するリクエスト群(バッチ)を決める。
3. **prefill(プロンプト読み込み)**: プロンプトの全トークンを**一括で**前半層(ibera)に流し、境界 activation を LAN 転送、後半層(nubia)が処理して**最初の 1 トークン**が出る。全トークンを並列に処理できるので GPU 向きだが、プロンプトが長いほど時間はかかる。**これが TTFT の正体**(実測: 2k プロンプトで 2.0 秒、8k で 5.9 秒 — ほぼ長さに比例)。
4. **decode(逐次生成)**: 以降は 1 ステップ 1 トークン。ポイントは **KV キャッシュが「各カードの自分の担当層のぶん」だけ手元に残る**こと。だから LAN を流れるのは毎ステップ境界 activation(約 10KB)と、決まったトークン ID などの小さな戻りだけ。
5. **ストリーム返却**: トークンが出るたび APIServer が SSE で返す。

補足 — **logits**: 最終層の出力から作られる「全語彙それぞれの、次に来そう度の点数表」。ここから 1 トークンを選ぶ(サンプリング)。§6-2 の guided JSON はこの点数表に細工をする機構である。

---

## 6. この構成を実用にしている 2 つの vLLM 機能

### 6-1. prefix caching — ReAct ループの生命線

vLLM は KV キャッシュのブロックをハッシュで管理し、**プロンプトの先頭一致部分(prefix)の KV ブロックをリクエスト間で共有・再利用**する。2 回目以降のリクエストで先頭が同じなら、その部分の prefill 計算(§5 手順 3)を丸ごとスキップできる。§2-2 の言葉でいえば「前に取ったメモをそのまま使い回す」。

実測: 8k トークンの同一 prefix を再送すると TTFT **5.89 秒 → 0.07 秒(98.8% 短縮)**。

FR-34 の ReAct ハーネスは「システムプロンプト＋質問＋増えていく観測」を毎ターン再送する構造、つまり**毎回プロンプトの先頭が同じ**なので、この機構と相性が最高に良い。これがないと毎ターン数秒の prefill を払い直すことになる。PP=2 でも prefix caching が効くことは P1 ゲートの必須確認項目だった(合格)。

### 6-2. guided JSON — 出力形式の構造的保証

decide コンポーネントは `response_format: {type: "json_schema", ...}` を付けて呼ぶ。vLLM はスキーマから**文法オートマトン**(「いまこの位置で文法的に許される次のトークンは何か」を判定する関所)を構築し、デコードの毎ステップで**文法違反トークンの確率を 0 にするフィルタ**を logits(§5 補足)に掛ける。

つまりモデルがどう間違えようとしても、**スキーマ違反の JSON は物理的に出力できない**。

実測(P2): スキーマ準拠 20/20(100%)vs 制約なし 0/20。しかも制約ありの方が **10.9% 速い** — 余計な前置きや markdown のコードフェンスを「出せない」ため、出力が短くなるから。

---

## 7. 実際に踏んだ罠と教訓(2026-07-18 の実話)

構築当日に起きた問題は、そのまま将来の再現時のチェックリストになる。

| # | 事象 | 原因 | 対処(再発時もこれ) |
|---|---|---|---|
| 1 | コンテナ内で `ray: not found` | 公式 `vllm/vllm-openai:v0.25.0` イメージは ray を同梱しない | 派生イメージ `pp2-vllm:v0.25.0-ray` を両ホストでビルド(`infra/pp2/Dockerfile.ray`、ray==2.56.0 固定) |
| 2 | serve が起動途中で 10 分固まって死ぬ(`DistNetworkError ... (172.28.208.109, 100)`) | c10d ランデブーがポート **100** を選び、FW の開放リストに無かった | ibera で `sudo ufw allow from <nubia IP>`(**ホスト単位**。ポート列挙は不十分) |
| 3 | `Failed to initialize NVML: Unknown Error` / `RuntimeError: Failed to infer device type` | 長時間稼働のコンテナが GPU アクセス権を失う(下記) | ホストの `nvidia-smi` が正常なら**コンテナ再作成**で復旧(数分)。serve 前に両ノードでコンテナ内 `nvidia-smi` を確認する習慣にする |
| 4 | 計測スクリプトの `/v1/tokenize` が 404 | vLLM の `/tokenize` はサーバー**ルート**に生える(`/v1` 配下ではない) | ルートを叩く(バックエンド実装 `client.py` は当初から正しい) |
| 5 | スループット計測値が異常に低い | モデルが数トークンで自発停止し、計測の分母が壊れた | ベンチでは `ignore_eos: true` で規定トークン数を強制生成 |

**罠#2「ポート 100 事件」の顛末**(§4-4 の待ち合わせで起きた):

vLLM が c10d の待ち合わせポートを「DP マスターポート(既定 0)+ 100」という内部計算で決めた結果、**ポート 100 番**になった。1024 未満の特権ポートだが、コンテナが root で動くため bind 自体は成功してしまう。ところが ibera のファイアウォールは「開けたポートのリスト」方式だったため nubia からの接続が黙って落とされ、rank1 が待ち合わせ場所に到達できず 10 分タイムアウトした。

教訓(裁定 §0-2 #13): **ポート番号の列挙で守ろうとしない**。c10d はこのような想定外のポートを選び得るし、その後に張られる NCCL/Gloo の接続も動的な高位ポートを両方向で使う。**相手ホスト単位の許可**(`sudo ufw allow from <相手 IP>`)が正解。なお現在の `serve-31b.sh` はランデブーポートを 29500 に固定してもいるが、これは保険であり、本命はホスト単位許可である。

**罠#3「NVML 剥がれ」の仕組み**:

- **NVML** = `nvidia-smi` が内部で使う GPU 管理ライブラリ。「NVML 初期化失敗」=「このプロセスから GPU が見えなくなった」という意味。
- **cgroup** = Linux が「このプロセス群はどのデバイス・資源に触ってよいか」を管理する仕組み。Docker は GPU コンテナに cgroup 経由で GPU アクセス許可を与える。
- ホスト側で systemd の daemon-reload 等が走るとこの許可設定が再構築され、**既に動いているコンテナの GPU 許可が剥がれる**ことがある(既知の Docker+cgroup 問題。head/worker 両方で実発生)。
- 厄介なのは、コンテナ自体は生きているため **Ray の台帳上は正常に見え続ける**こと(§4-2 の注意: GPU 数は参加時の自己申告値)。だから serve 前に必ずコンテナ内 `nvidia-smi` で実物を確認する。
- worker は再 join ループを持つため、head を作り直しても約 20 秒で自動復帰する。

---

**第 I 部の要点(3 行)**

1. 24GB 1 枚では 31B の KV キャッシュが張れない(2816 問題)→ 層を 2 台に分割(PP)すると各カードに 13GB 級の KV 領域 → 16k 窓が張れた。
2. PP の通信は境界 activation 約 10KB/トークンだけ → 1GbE の家庭 LAN でも余裕(TP は毎層答え合わせが要るので LAN では不成立)。
3. Ray が 2 台を 1 台に見せ、その上で vLLM が受付・司令塔・計算の全部をやる。外から見えるのは `ibera:8000` の 1 サーバーだけ。

---

# 第 II 部: 構築編

## 8. 構築前チェックリスト — スタートラインの状態と作り方

§9 の構築手順は、**この節の項目がすべて YES であること**を前提にする。まず一覧、続いて各項目の「あるべき状態・確認方法・そうでない場合の作り方」を示す。

| # | 項目 | あるべき状態 | 詳細 |
|---|---|---|---|
| 1 | ハードとネットワーク | 2 台が同一 LAN にいて互いに届く | §8-1 |
| 2 | NVIDIA ドライバー | 両ホストで `nvidia-smi` が GPU を表示 | §8-2 |
| 3 | Docker | 両ホストで動作 | §8-3 |
| 4 | NVIDIA Container Toolkit | 両ホストで「コンテナから GPU が見える」 | §8-4 |
| 5 | リポジトリと `.env` | 両ホストに clone と `.env`(`Inference_sever=`) | §8-5 |
| 6 | モデル重み | 両ホストの HF キャッシュに**同一 revision** の 31B | §8-6 |
| 7 | Docker イメージ | 両ホストに派生イメージ `pp2-vllm:v0.25.0-ray` | §8-7 |
| 8 | ファイアウォール | ibera が **nubia からの全通信を許可**(ホスト単位) | §8-8 |
| 9 | GPU の先客 | nubia で GPU を掴む他サービスが停止済み | §8-9 |

> 以下、`<nubia IP>` はプロジェクトルート `.env` の `Inference_sever` の値。ibera の LAN IP は `172.28.208.109`。

### 8-1. ハードウェアとネットワーク

- **あるべき状態**: ibera(RTX 3090 Ti 24GB)と nubia(RTX 3090 24GB)が同一の 1GbE LAN におり、互いに IP で到達できる。
- **確認**:

```bash
# ibera から
ping -c 3 <nubia IP>
ip route get <nubia IP>    # 出力の dev が LAN の NIC、src が ibera 自身の LAN IP
```

`ip route get` の結果(NIC 名と自 IP)は §9 で使うので控えておく。スクリプトは同じ方法で NIC を自動判定する。

### 8-2. NVIDIA ドライバー(両ホスト)

- **あるべき状態**: ホストの `nvidia-smi` が対象 GPU を表示する。
- **確認**: `nvidia-smi`
- **そうでない場合**: `sudo ubuntu-drivers install` でドライバーを導入して再起動(Ubuntu の場合)。

### 8-3. Docker(両ホスト)

- **あるべき状態**: `docker version` がクライアント・サーバー両方を表示する。
- **確認**: `docker version`
- **そうでない場合**: 公式の導入手順(https://docs.docker.com/engine/install/)に従う。

### 8-4. NVIDIA Container Toolkit(両ホスト)

Docker のコンテナから GPU を使うための橋渡し。これが無いと `--gpus all` が失敗する。

- **あるべき状態**: `docker info` の Runtimes に `nvidia` があり、コンテナ内から GPU が見える。
- **確認**:

```bash
nvidia-ctk --version
docker info --format '{{json .Runtimes}}'    # "nvidia" が含まれること
docker run --rm --gpus all --entrypoint nvidia-smi vllm/vllm-openai:v0.25.0
```

- **そうでない場合**(未導入時のみ):

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker   # Docker に nvidia ランタイムを登録
sudo systemctl restart docker
```

### 8-5. リポジトリと `.env`(両ホスト)

- **あるべき状態**:
  - ibera: `~/oc_2026` にこのリポジトリ。
  - nubia: `~/campus-guide-agent` に**同一リポジトリの clone**。
  - 両方のリポジトリルートに `.env` があり、**`Inference_sever=<nubia の LAN IP>`** を含む(この綴りは歴史的経緯の typo だが、スクリプト群がこの名前で読むため**変更しない**)。
- **確認**(両ホスト・リポジトリルートで):

```bash
grep Inference_sever .env
```

- **そうでない場合**: nubia へ clone し、ibera の `.env` と同じ内容を置く(nubia 側は API key 等は不要で、最低限 `Inference_sever` があればよい)。

### 8-6. モデル重み(両ホスト・同一 revision)

serve 時、rank0 と rank1 は**それぞれ手元のディスクから自分の担当層を読む**。だから両ホストの HF キャッシュ(`~/.cache/huggingface`)に**同一 revision** の 31B(ディスク上約 22GB)が必要。コンテナは `HF_HUB_OFFLINE=1` で動くため、**足りなくても自動ダウンロードはしない**(意図しない巨大ダウンロード事故の予防)。

- **確認**(両ホストで実行し、結果を突き合わせる):

```bash
MODEL_CACHE=~/.cache/huggingface/hub/models--google--gemma-4-31B-it-qat-w4a16-ct
cat  "${MODEL_CACHE}/refs/main"                     # ← revision 文字列が両ホストで一致すること
du -sh "${MODEL_CACHE}"                             # ← サイズが両ホストで一致(約 22GB)
find "${MODEL_CACHE}" -type f | wc -l               # ← ファイル数が一致
find -L "${MODEL_CACHE}/snapshots" -type l -print   # ← 何も出なければリンク切れなし
```

- **そうでない場合**(初回のみ): ibera から rsync で配布する。HF キャッシュは「blobs(実体)+ snapshots(シンボリックリンク)」という構造なので、**モデルディレクトリごと丸ごと**コピーすれば整合が保たれる。

```bash
# ibera から(約 22GB。1GbE で 4〜5 分)
rsync -av ~/.cache/huggingface/hub/models--google--gemma-4-31B-it-qat-w4a16-ct \
  <nubia のユーザー名>@<nubia IP>:~/.cache/huggingface/hub/
```

コピー後、上の確認コマンドで一致を再確認する。

### 8-7. vLLM イメージと派生イメージ(両ホスト)

- **あるべき状態**: 両ホストに派生イメージ **`pp2-vllm:v0.25.0-ray`** がある。公式イメージ `vllm/vllm-openai:v0.25.0` は **ray を同梱しない**(§7 罠#1)ため、ray==2.56.0 を追加した派生イメージを使う。
- **確認**:

```bash
docker images pp2-vllm
docker images --digests vllm/vllm-openai   # ← ベースイメージの digest が両ホストで一致すること
```

digest 照合は**ベースイメージ**で行う(派生イメージの digest はビルドごとに変わるため比較対象にしない)。「同じタグ名」ではなく「同じ digest」であることが重要 — マルチノードでは vLLM/Ray/CUDA の版ズレが典型的な起動失敗原因になる。

- **そうでない場合**(初回のみ・両ホストのリポジトリルートで):

```bash
docker pull vllm/vllm-openai:v0.25.0
docker build -t pp2-vllm:v0.25.0-ray -f infra/pp2/Dockerfile.ray infra/pp2
```

### 8-8. ファイアウォール(ibera)

- **あるべき状態**: ibera の ufw が **nubia からの全通信をホスト単位で許可**している。nubia 側は ufw が inactive なら何もしない(有効なら対称に ibera を許可)。
- **確認**:

```bash
sudo ufw status    # ibera: 「Anywhere ALLOW <nubia IP>」の行があること
```

- **そうでない場合**:

```bash
# ibera
sudo ufw allow from <nubia IP> comment 'pp2: nubia'
```

**なぜポート列挙ではだめか**: 固定で決まっているポート(Ray の 6379/10001/10002/10003/11000-11999、c10d の 29500、API の 8000)だけなら列挙できるが、**NCCL と Gloo は動的な高位ポートを両方向で開く**うえ、c10d が想定外のポートを選んだ実績もある(§7 罠#2「ポート 100 事件」)。列挙リストは必ずどこかで穴が開く。相手は LAN 内の特定 1 台なので、ホスト単位許可が安全かつ確実。外部(インターネット側)へ Ray ポートを公開しない、という原則はこの方式でも保たれる。

### 8-9. GPU の先客がいないこと(nubia)

- **あるべき状態**: nubia で GPU を掴む既存サービス(SGLang 等)が停止している。VRAM はほぼ全量(24GB 中 23GB 級)を vLLM が使うため、先客がいると即 OOM になる。
- **確認**: `nvidia-smi` のプロセス欄が空であること。
- **そうでない場合**: 該当サービスを停止する。

なお ibera 側の先客(本番 12B)は §9 手順 1 で退避するので、ここでは何もしなくてよい。

---

## 9. 構築手順 — 各手順で何が起きているか

§8 がすべて YES である前提。コマンドの正・全引数は `infra/pp2/README.md`。起動順序の全体像:

```
nubia: 手順2 worker 起動 ──┐ ← 先に立てて「待たせて」おける
                           ├→ 手順4 2GPU+NVML 確認 → 手順5 serve → 手順6 疎通 → 手順7 backend
ibera: 手順1 12B 退避 → 手順3 head 起動 ─┘
```

### 手順 1: 本番 12B の退避(ibera)

```bash
cd /home/junta_takahashi/oc_2026
docker compose stop backend vllm     # qdrant は残す
```

**何をしているか**: GPU(12B が使用中)とポート 8000 を PP=2 に明け渡す。`serve-31b.sh` は 8000 に先客がいると起動を拒否する設計なので、これを省くと手順 5 で止まる。**この瞬間から本番チャットは停止する**(backend は手順 7 で復帰)。

**成功の確認**: `docker compose ps` で vllm と backend が消えている(qdrant は残る)。

### 手順 2: Ray worker 起動(nubia)

```bash
cd ~/campus-guide-agent
HEAD_NODE_IP=172.28.208.109 infra/pp2/start-worker-nubia.sh
```

(`変数=値 コマンド` の形式は、その 1 コマンドにだけ環境変数を渡す bash の書き方。`HEAD_NODE_IP` は head つまり ibera の LAN IP)

**何をしているか**: host ネットワーク + GPU 全割当のコンテナ `pp2-ray-worker-nubia` が立ち、中で「ibera の 6379 番(head の台帳)へ参加を試みる → 失敗したら 5 秒待って再試行」というループが回り始める。**head がまだ居なくても構わない**(待ち続けるだけ)ので、先に立てておける。参加時に「GPU 1 枚あります」と自己申告する(§4-2)。

**成功の確認**:

```bash
infra/pp2/start-worker-nubia.sh status   # コンテナが Up。join 前なら "Trying Ray head..." が流れる
```

### 手順 3: Ray head 起動(ibera)

```bash
cd /home/junta_takahashi/oc_2026
infra/pp2/start-head.sh
```

**何をしているか**: コンテナ `pp2-ray-head-ibera` の中でクラスタの台帳(GCS)がポート 6379 で待ち受けを開始する。スクリプトは `.env` から nubia の IP を読み、`ip route get` で自分の LAN IP と NIC を自動判定して、NCCL/Gloo が使う NIC をその LAN 側に固定する(§4-4。自動判定が外れる環境では `PP2_NIC` で明示できる)。

**成功の確認**: `Ray head is ready.` が表示される。

### 手順 4: クラスタ確認と GPU 健全性確認(両ホスト)

```bash
# ibera — 2 nodes / GPU 2.0 になるまで待つ(worker 参加は通常数秒〜20 秒)
infra/pp2/start-head.sh status

# 両ノード — コンテナ内から GPU が本当に見えるか(§7 罠#3 の事前確認)
docker exec pp2-ray-head-ibera nvidia-smi        # ibera で
docker exec pp2-ray-worker-nubia nvidia-smi      # nubia で
```

**何をしているか**: 前者は「台帳上、2 台が 1 つのクラスタに見えているか」の確認。後者が別に必要なのは、Ray の GPU 数が**参加時の自己申告値**であり、いま現在の健全性を保証しないから(§4-2)。NVML エラーが出たらこの時点でコンテナを再作成する(`stop` → 再度 start。数分)。

**成功の確認**: `ray status` に 2 nodes と `GPU: 2.0`、両ノードの `nvidia-smi` が正常表示。

### 手順 5: serve — 31B を 2 台に展開(ibera)

```bash
infra/pp2/serve-31b.sh          # start が既定。READY まで自動で待ってくれる
```

**何をしているか**(スクリプトが順にやること):

1. ポート 8000 の先客検査(いれば中止)と、Ray 台帳の GPU 数検査(2 未満なら中止)。
2. head コンテナ内で `vllm serve` を**デタッチ起動**(SSH や端末が切れても生き続ける。ログはコンテナ内 `/root/pp2-serve.log`)。
3. vLLM が Ray に「GPU 1 枚の働き手を 2 人」依頼 → rank0 が ibera、rank1 が nubia に配置される(§4-2)。
4. rank 同士が c10d で待ち合わせ(ポート 29500 固定)→ NCCL/Gloo の通信路を確立(§4-4)。
5. 各 rank が手元の HF キャッシュから**自分の担当層だけ**を読み込む。ページキャッシュ(Linux が一度読んだファイルを RAM に覚えておく仕組み)に乗っていれば約 3 分、ホスト再起動直後の初回はディスク読みでもう数分かかる。
6. `Uvicorn running on http://127.0.0.1:8000` → スクリプトが READY を検知して戻る(最長 600 秒待機)。

主要な既定値(環境変数で上書き可。全一覧は `infra/pp2/README.md` §2-4):

| 設定 | 既定値 | 意味 |
|---|---|---|
| `--max-model-len` | 16384 | コンテキスト窓(§2-4 で張れるようになった値) |
| `--max-num-seqs` | 8 | 同時に走らせるリクエスト数の上限(オープンキャンパスの同時接続目標) |
| `--gpu-memory-utilization` | 0.92 | VRAM の 92% まで使う(残りは安全マージン) |
| `--enable-prefix-caching` | 有効 | §6-1 の生命線 |

**成功の確認**: `API READY after ~XXXs` の表示。以降の死活確認は `infra/pp2/serve-31b.sh status`、ログ追尾は同 `logs`。デバッグで前面起動したいときだけ `PP2_FOREGROUND=1` を付ける。

### 手順 6: 疎通確認(ibera)

```bash
curl -fs http://127.0.0.1:8000/v1/models    # モデル名と max_model_len 16384 を確認
# 1 リクエスト smoke — 生成が 2 筐体を往復して返ることの確認
curl -fs http://127.0.0.1:8000/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"google/gemma-4-31B-it-qat-w4a16-ct","messages":[{"role":"user","content":"一文で自己紹介して"}],"max_tokens":60}'
```

**何をしているか**: 前者は APIServer が起きているかとモデル設定の確認。後者は実際に prefill → LAN 転送 → decode の全経路(§5)を 1 周させる確認。

### 手順 7: backend 接続(ibera)

```bash
docker compose up -d backend
curl -fs http://127.0.0.1:8080/api/health   # model が 31B で status: ok を確認
```

**何をしているか**: backend は host ネットワークで動き、生成先は常に `http://127.0.0.1:8000/v1`(§10)。いま 8000 で待っているのは PP=2 の 31B なので、そのまま 31B につながる。`depends_on` で qdrant も一緒に上がる(compose の vllm=12B は起動**しない**)。

**成功の確認**: health の `model` が 31B・`status: ok`。実チャットを 1 往復させれば完了。

### 手順 8: 撤収(PoC 等の一時利用を畳む場合)

```bash
# ibera — PP スタック停止(serve は head コンテナと一緒に消える)
infra/pp2/start-head.sh stop

# nubia — worker 停止(GPU メモリ解放)
cd ~/campus-guide-agent && infra/pp2/start-worker-nubia.sh stop

# ibera — 12B 単機の本番に戻す場合
cd /home/junta_takahashi/oc_2026
LLM_MODEL=google/gemma-4-12B-it-qat-w4a16-ct docker compose up -d vllm backend
```

**何をしているか**: コンテナは使い捨て(ephemeral)なので stop で消える。HF キャッシュはホスト側ディレクトリのマウントなので消えない(次回もダウンロード不要)。

---

## 10. 本番運用モード(FR-35)〔旧 v1.0 §6-9〕

2026-07-18 の利用者指示で **31B PP=2 が本番既定**になった。§9 は「初回構築」、この節は「日常運用」を扱う。

### 10-1. 設計の要点 — 同じ URL の取り合い

FR-35 で backend は `network_mode: host` になり、生成エンドポイントは常に `http://127.0.0.1:8000/v1`。**PP=2 の serve(ホスト直)と 12B(compose vllm の 127.0.0.1:8000 公開)が同じ URL を取り合う**設計なので、両方同時には起動できない(`serve-31b.sh` は起動前に 8000 の占有を検査して弾く)。

裏返すと、**backend から見れば切替は「8000 で誰が待っているか」だけの問題**であり、backend の設定変更は一切不要。これが 3 分で切り戻せる理由。

平常時に生きているべきもの: nubia の worker コンテナ / ibera の head コンテナ + serve プロセス + backend + qdrant。serve はデタッチ起動なので SSH が切れても生きるが、**head コンテナを消す(`start-head.sh stop`)と一緒に死ぬ**。

### 10-2. 本番起動(通常運用・マシン再起動後もこの順)

コンテナは再起動で消えるため、ホスト再起動後は該当ホストぶんを立て直す。手順の中身は §9 手順 2〜7 と同一(§8 の初回項目は不要)。

```bash
# 0) nubia: worker 起動(常時稼働。nubia 再起動後もこれだけ)
cd ~/campus-guide-agent && HEAD_NODE_IP=172.28.208.109 infra/pp2/start-worker-nubia.sh

# 1) ibera: 12B が動いていれば止める(初回切替時のみ)
cd /home/junta_takahashi/oc_2026 && docker compose stop vllm

# 2) ibera: head 起動 → 2 GPU を待つ → 両ノード NVML 確認(§7 罠#3)
infra/pp2/start-head.sh && infra/pp2/start-head.sh status
docker exec pp2-ray-head-ibera nvidia-smi

# 3) ibera: serve(デタッチ起動・API READY まで自動待機・max-num-seqs 8)
infra/pp2/serve-31b.sh            # ← start が既定。ready 表示が出たら完了
infra/pp2/serve-31b.sh status     # 以降の死活確認 / logs でログ追尾

# 4) ibera: backend(qdrant も連れて上がる。vllm サービスは起動しない)
docker compose up -d backend
curl -fs http://127.0.0.1:8080/api/health   # model が 31B で status: ok を確認
```

### 10-3. 12B への緊急切り戻し(当日 PP 系障害時。目標 3 分)

```bash
# ibera のみで完結(nubia が死んでいても実行可能)
infra/pp2/serve-31b.sh stop || true
infra/pp2/start-head.sh stop || true        # head ごと落として 8000 を確実に解放
cd /home/junta_takahashi/oc_2026
LLM_MODEL=google/gemma-4-12B-it-qat-w4a16-ct docker compose up -d vllm backend
curl -fs http://127.0.0.1:8080/api/health   # model が 12B で status: ok(ロード 1〜2 分)
```

31B へ戻すときは §10-2 を再実行(`docker compose stop vllm` を忘れない)。`LLM_MODEL` は毎回の `docker compose up` コマンドの環境変数で切り替える(`.env` に書くと戻し忘れの事故になるため推奨しない)。

### 10-4. 運用上の注意

- **nubia 断 = 生成全停止**(§12 の限界)。nubia の再起動・停電後は worker 起動(§10-2 の 0)→ serve は自動では戻らないので ibera で `serve-31b.sh stop` → クラスタが 2 GPU に戻ったのを確認してから `serve-31b.sh`。直らなければ §11 の完全再起動へ。
- serve はコンテナ内デタッチプロセスなので、**起動したシェルや SSH が切れても生存**する。head コンテナを消すと一緒に死ぬ。
- 週次程度で §7 罠#3(NVML 剥がれ)の予防確認: 両ノードで `docker exec … nvidia-smi`。

---

## 11. トラブルシュート早見表

| 症状 | 見るところ | 原因と対処 |
|---|---|---|
| worker が `GCS connect timeout` を繰り返す | head は起動済みか・`HEAD_NODE_IP` は正しいか | head 未起動なら起動する(worker は放置でよい — 自動再試行で参加する) |
| `ray status` が 1 ノードのまま | nubia のコンテナ生存(`status` サブコマンド) | worker が停止済みなら §9 手順 2 を再実行 |
| serve が `ERROR: something already serves` で拒否 | 8000 番の先客 | 12B(compose vllm)が生きているか、前回の serve が残っている。`docker compose stop vllm` / `serve-31b.sh stop` してから再実行 |
| serve が数分無言 → `DistNetworkError (…, 100)` | ibera の ufw ルール | §7 罠#2。ホスト単位 allow(§8-8)を入れて serve 再実行 |
| `Failed to infer device type` で即死 | コンテナ内 `nvidia-smi` | §7 罠#3。NVML エラーならコンテナ再作成(head: stop→start、worker: stop→start) |
| `Engine core initialization failed` | ログ**上方の最初の**エラー(真因は末尾ではなく最初に出る) | rank1(nubia 側)の例外もここに集約される。NVML / FW / 重み欠落(§8-6)を順に疑う |
| API は生きているが応答が異常に遅い | `ray status` の GPU 数・nubia の負荷 | 片系断で再スケジュールされた可能性。worker/head/serve を完全再起動(下記) |
| 当日に PP 系が復旧不能 | — | **12B へ切り戻して継続**(§10-3)。品質は劣化するが全停止は回避できる |

**完全再起動の順序**(通信断・片系断のあとに古いプロセスを残さないための基本形): nubia `start-worker-nubia.sh stop` → ibera `start-head.sh stop` → §9 手順 2〜5 を再実行(worker → head → 2GPU/NVML 確認 → serve)。

---

## 12. 実測値サマリと構成の限界

2026-07-18 PoC(P1〜P4 全合格)の実測:

| 項目 | 値 |
|---|---|
| コンテキスト窓 | 16,384 トークン(15,009 トークンの実プロンプト供給を確認) |
| デコード速度 | 37.9 tok/s(1 並列)/ 67.8 tok/s(4 並列合算・1.79 倍スケール) |
| TTFT | 2.0 秒 @2k / 5.9 秒 @8k プロンプト |
| prefix cache | 再送 TTFT 5.89 秒 → 0.07 秒(98.8% 短縮) |
| guided JSON | スキーマ準拠 20/20(100%)・オーバーヘッド −10.9%(制約なしより速い) |
| VRAM | 両カードとも 23.2GB / 24.5GB 使用(均等・層分割の手動調整は不要だった) |
| 重みロード〜API READY | 約 3 分(ページキャッシュ温存時) |

**構成の限界**: PP=2 は性能を足す構成であって冗長化ではない。2 台で 1 つの論理インスタンスなので、**nubia 断・LAN 断・Ray 断のどれか 1 つでも生成が全停止**する(§4-5 のとおり全リクエストが必ず両ノードを通るため)。緊急時は 12B 単機へ切り戻す設計(§10-3、`docs/AGENT_REACT.md` §1-3)。
