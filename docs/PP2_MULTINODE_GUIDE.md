# PP=2 マルチノード vLLM 技術解説と構築手順（ibera + nubia）

- 版: v1.0（2026-07-18, Fable 執筆。FR-34 PoC 全合格の実測に基づく）
- 対象読者: 本プロジェクトの利用者（後から見返して自力で再現・復旧できることを目的とする）
- 関連: `infra/pp2/README.md`（運用クイックリファレンス・コマンド正）、
  `docs/AGENT_REACT.md` §0-2/§1/§6-2（裁定と実測値）

このドキュメントは「**ibera と nubia の間で vLLM が技術的に何をしているのか**」を原理から説明し、
その上で構築手順を再現可能な形で記載する。コマンドの正は `infra/pp2/README.md` 側にあり、
本書は「なぜそうするのか」を担当する。

---

## 1. なぜ 2 台必要なのか — VRAM の算数

すべての出発点は **24GB という VRAM の壁**にある。

### 1-1. LLM サービングのメモリ内訳

GPU で LLM を動かすとき、VRAM は大きく 3 つに分かれる:

| 用途 | 内容 | Gemma 4 31B (w4a16) の場合 |
|---|---|---|
| モデル重み | パラメータ本体。4bit 量子化でもパラメータ数×0.5byte+α | 約 17GB |
| KV キャッシュ | 過去トークンの Key/Value を全層ぶん保持する作業領域 | 残り VRAM 次第 |
| その他 | activation・CUDA グラフ・バッファ | 1〜2GB |

**KV キャッシュ**が本質的に重要で、これは「会話コンテキストの長さ」に比例して線形に増える。
1 トークンあたり `層数 × 2(K と V) × hidden 次元 × dtype バイト数` を消費するため、
コンテキスト窓を長く取りたいほど KV 用の空き VRAM が必要になる。

### 1-2. 単カード時代に起きたこと（2816 問題）

31B を 24GB 単カード（ibera の RTX 3090 Ti）に載せると、重み 17GB を引いた残りは
5GB 程度しかない。このとき張れた KV キャッシュは **`max-model-len 2816`**（約 2,800 トークン）
が限界だった（2026-07-12 の実測。`ARCHITECTURE.md` v0.3 の撤去記録）。

2,800 トークンでは「システムプロンプト＋履歴＋検索結果＋回答」がまともに入らない。
とりわけ FR-34 の ReAct ハーネスは観測を蓄積しながら探索するため、この窓では成立しない。
これが 12B へ一時後退した理由であり、31B へ戻すために 2 台目（nubia の RTX 3090）を使う
動機になった。

### 1-3. 2 台に分けるとどうなるか

モデルの層を半分ずつ 2 枚のカードに置くと、各カードの重み負担は約 8.5GB になり、
**各カードに 13GB 級の KV 領域が生まれる**。これで `max-model-len 16384`（16k トークン、
単カード比 5.8 倍）が張れた。

実測（2026-07-18 PoC）: 両カードとも VRAM 使用 23.2GB / 24.5GB で綺麗に均等。
15,009 トークンの実プロンプトを受け付けることを確認済み。

---

## 2. 並列化 3 方式と、なぜ「パイプライン並列」を選んだか

複数 GPU で 1 つのモデルを動かす方式は大きく 3 つある。**どの方式が使えるかは
GPU 間をつなぐ配線の帯域で決まる**。ibera–nubia 間は 1GbE の家庭用 LAN（実効 ~110MB/s）で、
これは NVLink（数百 GB/s）の 3〜4 桁下である。この制約がすべてを決めた。

### 2-1. データ並列（DP）— 不可

モデルの完全なコピーを各 GPU に置き、リクエストを振り分ける方式。
スループットは上がるがカード 1 枚に全モデルが載ることが前提。31B は 24GB に載らないので不可。

### 2-2. テンソル並列（TP）— LAN では不成立

各層の行列そのものを列/行方向に割って 2 枚で分担する方式。1 枚あたりの重みは半分になるが、
**全層で毎トークン all-reduce（部分結果の集約）が必要**になる。集約のたびに hidden ベクトル
全体が GPU 間を往復するため、層数×トークン数の回数だけ低レイテンシ・広帯域通信が走る。
NVLink や同一ホスト PCIe を前提とした方式で、1GbE の LAN 越しでは通信が支配的になり実用にならない。

### 2-3. パイプライン並列（PP）— 採用

層を「前半グループ／後半グループ」に**層の境界で**切り、前半を ibera、後半を nubia に置く方式。

```
  リクエスト → [ibera: 層 1〜N/2] → (LAN: activation 転送) → [nubia: 層 N/2+1〜N] → logits → トークン
```

境界をまたぐデータは **activation（その時点の hidden ベクトル）だけ**である。
デコード時は 1 トークンあたり hidden 次元 × 2byte 程度 = **10KB 級**しか流れない。
毎トークン 2 回（行って logits、は末端 nubia 側で出るので実際は片道＋制御）としても
1GbE で全く問題にならない。これが「LAN 越しでも PP なら成立する」理由である。

### 2-4. PP の代償 — バブルとレイテンシ

PP はタダではない。1 トークン作るのに必ず「ibera で計算 → 転送 → nubia で計算」という
直列の旅程を通るため、**単発レイテンシは単カードよりやや悪化**する。また片方が計算している間
もう片方は暇になる（パイプラインバブル）。vLLM は複数リクエストをマイクロバッチとして
交互に流し込むことでバブルを埋める。

実測が示す姿:
- 1 並列デコード **37.9 tok/s**（読み上げ速度としては十分速い）
- 4 並列合算 **67.8 tok/s**（1.79 倍 — バブルが埋まり並列でスケールする）
- TTFT（最初のトークンまで）2.0 秒 @2k プロンプト

---

## 3. 登場人物 — Ray と vLLM は何を分担しているか

### 3-1. Ray: 「2 台を 1 台に見せる」土台

Ray は分散計算のためのクラスタ基盤で、この構成では次だけを担う:

- **head（ibera）**: GCS（Global Control Store）というクラスタ台帳を持つ。「どのノードに
  GPU が何個あるか」「どのプロセス（アクタ）がどこで生きているか」を一元管理する。
- **worker（nubia）**: raylet というノード常駐デーモンが head に自己申告して参加し、
  自ノードでのプロセス起動を代行する。

vLLM から見ると Ray は「**GPU 1 個ください、と頼むと適切なノードにプロセスを配置してくれる
執事**」である。ibera/nubia のどちらで何を起動するかを vLLM 自身は管理せず、Ray に委譲する。
`ray status` で `2 nodes / 2.0 GPU` と見えていることが「1 台に見えている」状態の確認になる。

### 3-2. vLLM: プロセスの実際の配置

`vllm serve --distributed-executor-backend ray --pipeline-parallel-size 2` を ibera で実行すると、
次のプロセス群が生まれる:

| プロセス | 場所 | 役割 |
|---|---|---|
| APIServer | ibera | OpenAI 互換 HTTP（:8000）。リクエスト受付・SSE 返却 |
| EngineCore | ibera | スケジューラ。バッチ編成・KV ブロック管理・各 rank への指示 |
| RayWorkerProc rank0 | ibera（Ray アクタ） | 層前半の GPU 計算 |
| RayWorkerProc rank1 | nubia（Ray アクタ） | 層後半の GPU 計算 |

バックエンド（campus-guide-agent）から見えるのは ibera:8000 の 1 エンドポイントだけで、
背後に 2 台いることは完全に隠蔽される（`VLLM_BASE_URL` の差し替えのみで移行できる理由）。

### 3-3. torch.distributed の初期化 — 「ポート 100 事件」の現場

rank0/rank1 は計算開始前に torch.distributed のプロセスグループを組む。このとき
**c10d TCPStore ランデブー**という集合手続きが走る: rank0 が TCP サーバーを立て、
全 rank がそこへ接続して互いの所在を交換する。

2026-07-18 の PoC ではここで 10 分タイムアウトが発生した。原因は vLLM が選んだ
ランデブーポートが **100 番**（実装上 `DP マスターポート(デフォルト 0) + 100` という計算。
コンテナが root で動くため 1024 未満でも bind に成功してしまう）で、ibera の
ファイアウォール開放リストに載っていなかったこと。

**教訓（裁定 §0-2 #13）**: ポート番号の列挙で守ろうとしない。c10d は上記のような想定外の
ポートを選び得るし、この後に張られる NCCL/Gloo 接続も動的な高ポートを使う。
**相手ホスト単位の許可**（`sudo ufw allow from <相手 IP>`）が正解。

### 3-4. 実データの通信路 — NCCL と Gloo

プロセスグループ成立後の実通信は 2 種:

- **NCCL**: GPU テンソル（activation）の転送。NVLink が無い環境では TCP ソケットに
  フォールバックする。`NCCL_SOCKET_IFNAME=eno1` で使う NIC を固定している
  （Docker の仮想 NIC 等を誤選択させないため）。
- **Gloo**: CPU 側の制御メッセージ・メタデータ交換。

いずれも起動スクリプトが `--network host` でコンテナを動かすことで、コンテナ間 NAT を
挟まず 2 台のホスト LAN IP 同士で直接通信させている。

---

## 4. リクエストの一生 — 1 トークンの旅

`POST /v1/chat/completions` が届いてから 1 トークン出るまで:

1. **受付**: APIServer がプロンプトをトークナイズし EngineCore へ渡す。
2. **スケジューリング**: EngineCore が KV キャッシュのブロック（ページ）を割り当て、
   今ステップに走らせるリクエスト群（バッチ）を決める。
3. **prefill（プロンプト読み込み）**: プロンプト全トークンを一括で前半層（ibera）に流し、
   境界 activation を LAN 転送、後半層（nubia）が処理して最初の 1 トークンが出る。
   ここが TTFT の正体（2k で 2.0 秒、8k で 5.9 秒 — プロンプト長にほぼ比例）。
4. **decode（逐次生成）**: 以降は 1 ステップ 1 トークン。**KV キャッシュは各カードの
   自分の層ぶんが手元に残る**ため、LAN を流れるのは毎ステップ境界 activation（10KB 級）だけ。
5. **ストリーム返却**: トークンが出るたび APIServer が SSE で返す。

### 4-1. prefix caching — ReAct ループの生命線

vLLM はプロンプトの先頭一致部分（prefix）の KV ブロックをハッシュで共有・再利用する。
2 回目以降のリクエストで先頭が同じなら、その部分の prefill 計算を丸ごとスキップできる。

実測: 8k トークンの同一 prefix を再送すると TTFT **5.89 秒 → 0.07 秒（98.8% 短縮）**。

FR-34 の ReAct ハーネスは「システムプロンプト＋質問＋増えていく観測」を毎ターン再送する
構造なので、この機構がないと毎ターン数秒の prefill を払うことになる。PP=2 でも prefix
caching が効くことは P1 ゲートの必須確認項目だった（合格）。

### 4-2. guided JSON — 出力形式の構造的保証

decide コンポーネントは `response_format: {type: "json_schema", ...}` を付けて呼ぶ。
vLLM はスキーマから**文法オートマトン**を構築し、デコードの毎ステップで「文法的に
許されないトークンの確率を 0 にする」フィルタを logits に掛ける。つまりモデルが
どう間違えようとしても**スキーマ違反の JSON は物理的に出力できない**。

実測（P2）: スキーマ準拠 20/20（100%）vs 制約なし 0/20。しかも制約ありの方が 10.9% 速い
（余計な前置きや markdown フェンスを「出せない」ため出力が短くなる）。

---

## 5. 実際に踏んだ罠と教訓（2026-07-18 の実話）

構築当日に起きた問題は、そのまま将来の再現時のチェックリストになる。

| # | 事象 | 原因 | 対処（再発時もこれ） |
|---|---|---|---|
| 1 | コンテナ内で `ray: not found` | 公式 `vllm/vllm-openai:v0.25.0` イメージは ray を同梱しない | 派生イメージ `pp2-vllm:v0.25.0-ray` を両ホストでビルド（`infra/pp2/Dockerfile.ray`、ray==2.56.0 固定） |
| 2 | serve が起動途中で 10 分固まって死ぬ（`DistNetworkError ... (172.28.208.109, 100)`） | c10d ランデブーがポート 100 を選び、FW の開放リストに無かった | ibera で `sudo ufw allow from <nubia IP>`（**ホスト単位**。ポート列挙は不十分） |
| 3 | `Failed to initialize NVML: Unknown Error` / `RuntimeError: Failed to infer device type` | 長時間稼働のコンテナがホスト cgroup 再読込で GPU デバイス権限を失う（既知の Docker+cgroup 問題。head/worker 両方で実発生） | ホストの `nvidia-smi` が正常なら**コンテナ再作成**で復旧（数分）。serve 前に両ノードでコンテナ内 `nvidia-smi` を確認する習慣にする |
| 4 | 計測スクリプトの `/v1/tokenize` が 404 | vLLM の `/tokenize` はサーバー**ルート**に生える（`/v1` 配下ではない） | ルートを叩く（バックエンド実装 `client.py` は当初から正しい） |
| 5 | スループット計測値が異常に低い | モデルが数トークンで自発停止し、計測の分母が壊れた | ベンチでは `ignore_eos: true` で規定トークン数を強制生成 |

補足（#3 の仕組み）: GPU コンテナはホストの cgroup で「このコンテナは GPU デバイスに
アクセスしてよい」という許可を持つが、ホスト側で systemd の daemon-reload 等が走ると
この許可が剥がれることがある。コンテナ自体は生きているため Ray からは正常に見え続けるのが
厄介な点（Ray の GPU 数は raylet 起動時の申告値で、実時点の健全性を反映しない）。
worker は再join ループを持つため、head を作り直しても約 20 秒で自動復帰する。

---

## 6. 構築手順（完全再現用）

> コマンドの正・詳細な引数は `infra/pp2/README.md`。ここでは「順序と、各手順で何が
> 起きているか」を主に記す。`<nubia IP>` は `.env` の `Inference_sever` の値。

### 前提条件

| 項目 | ibera | nubia |
|---|---|---|
| GPU | RTX 3090 Ti 24GB | RTX 3090 24GB |
| 役割 | Ray head + APIServer + rank0 | Ray worker + rank1 |
| リポジトリ | `~/oc_2026` | `~/campus-guide-agent`（同一リポジトリの clone） |
| `.env` | リポジトリルートに配置（`Inference_sever=<nubia IP>` 必須） | 同じ内容をリポジトリルートに配置 |
| Docker | GPU アクセス可能（`docker run --gpus all` が動く） | 同左 |
| その他 | — | SGLang 等、GPU を掴む既存サービスは停止しておく |

### 手順 0: モデル重みの同期（初回のみ）

両ホストの HF キャッシュ（`~/.cache/huggingface`）に同一の 31B 重み（約 22GB）が必要。
初回は ibera から rsync で配布し、ファイル数とサイズの一致を確認する。
ベースイメージも `docker images --digests` で両ホストの digest 一致を確認する
（「同じタグ名」ではなく「同じ digest」であることが重要）。

### 手順 1: 派生イメージのビルド（両ホスト・初回のみ）

```bash
# ibera / nubia 共通（リポジトリルートで）
docker build -t pp2-vllm:v0.25.0-ray -f infra/pp2/Dockerfile.ray infra/pp2
```

何が起きるか: 公式 vLLM イメージに `ray[default,cgraph]==2.56.0` を追加する（§5 罠#1）。

### 手順 2: ファイアウォール（ibera・初回のみ）

```bash
# ibera
sudo ufw allow from <nubia IP> comment 'pp2 PoC: nubia'
# nubia 側は `sudo ufw status` が inactive なら何もしない
```

何が起きるか: c10d ランデブー・NCCL・Gloo の全接続を通す（§5 罠#2。ポート列挙では守れない）。

### 手順 3: 本番サービスの退避（ibera）

```bash
# ibera（リポジトリルートで実行 — .env 読込のため）
docker compose stop backend vllm     # qdrant は残す
```

何が起きるか: GPU（12B が使用中）とポート 8000 を PP=2 に明け渡す。
**この瞬間から本番チャットは停止する。**

### 手順 4: Ray head 起動（ibera）

```bash
/home/junta_takahashi/oc_2026/infra/pp2/start-head.sh
docker exec pp2-ray-head-ibera nvidia-smi   # ← GPU が見えること（§5 罠#3 の事前確認）
```

何が起きるか: host ネットワークで Ray head コンテナが立ち、GCS がポート 6379 で待ち受ける。

### 手順 5: Ray worker 起動（nubia）

```bash
cd ~/campus-guide-agent
HEAD_NODE_IP=172.28.208.109 infra/pp2/start-worker-nubia.sh
# 状態確認:
infra/pp2/start-worker-nubia.sh status
```

何が起きるか: worker コンテナが head の 6379 へ接続を試み続けるループに入る（head が
未起動でも先に立ててよい）。参加後は `ray status`（ibera 側）に 2 ノード目が現れる。

### 手順 6: クラスタ確認と serve（ibera）

```bash
# 2 GPU になるまで待つ（worker 参加は通常数秒〜20 秒）
/home/junta_takahashi/oc_2026/infra/pp2/start-head.sh status

# nubia 側コンテナの GPU 健全性も確認してから（§5 罠#3）:
/home/junta_takahashi/oc_2026/infra/pp2/serve-31b.sh
```

何が起きるか: Ray の GPU 数を事前検査したうえで `vllm serve` が走り、rank0/rank1 アクタが
両ノードに配置される。c10d ランデブー → NCCL 初期化 → 重みロード（ページキャッシュに
乗っていれば約 3 分）→ `Uvicorn running on http://127.0.0.1:8000`。

### 手順 7: 疎通確認（ibera）

```bash
curl -fs http://127.0.0.1:8000/v1/models          # モデル名と max_model_len 16384 を確認
# 1 リクエスト smoke（生成が 2 筐体を往復して返ることの確認）
curl -fs http://127.0.0.1:8000/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"google/gemma-4-31B-it-qat-w4a16-ct","messages":[{"role":"user","content":"一文で自己紹介して"}],"max_tokens":60}'
```

### 手順 8: 撤収（PoC 等の一時利用を畳む場合）

```bash
# ibera — PP スタック停止（serve はコンテナごと消える）
/home/junta_takahashi/oc_2026/infra/pp2/start-head.sh stop

# nubia — worker 停止（GPU メモリ解放）
cd ~/campus-guide-agent && infra/pp2/start-worker-nubia.sh stop
```

## 6-9. 本番運用モード（FR-35・2026-07-18 利用者指示で 31B PP=2 が本番既定）

FR-35 で backend は `network_mode: host` になり、生成エンドポイントは常に
`http://127.0.0.1:8000/v1`。**PP=2 の serve（ホスト直）と 12B（compose vllm の
127.0.0.1:8000 公開）が同じ URL を取り合う**設計なので、両方同時には起動できない
（`serve-31b.sh` は起動前に 8000 の占有を検査して弾く）。

### 本番起動（通常運用・再起動後もこの順）

```bash
# 0) nubia: worker 起動（常時稼働。再起動後もこれだけ）
cd ~/campus-guide-agent && HEAD_NODE_IP=172.28.208.109 infra/pp2/start-worker-nubia.sh

# 1) ibera: 12B が動いていれば止める（初回切替時のみ）
cd /home/junta_takahashi/oc_2026 && docker compose stop vllm

# 2) ibera: head 起動 → 2 GPU を待つ → 両ノード NVML 確認（§5 罠#3）
infra/pp2/start-head.sh && infra/pp2/start-head.sh status
docker exec pp2-ray-head-ibera nvidia-smi

# 3) ibera: serve（デタッチ起動・API READY まで自動待機・max-num-seqs 8）
infra/pp2/serve-31b.sh            # ← start が既定。ready 表示が出たら完了
infra/pp2/serve-31b.sh status     # 以降の死活確認 / logs でログ追尾

# 4) ibera: backend（qdrant も連れて上がる。vllm サービスは起動しない）
docker compose up -d backend
curl -fs http://127.0.0.1:8080/api/health   # model が 31B で status: ok を確認
```

### 12B への緊急切り戻し（当日 PP 系障害時。目標 3 分）

```bash
# ibera のみで完結（nubia が死んでいても実行可能）
infra/pp2/serve-31b.sh stop || true
infra/pp2/start-head.sh stop || true        # head ごと落として 8000 を確実に解放
cd /home/junta_takahashi/oc_2026
LLM_MODEL=google/gemma-4-12B-it-qat-w4a16-ct docker compose up -d vllm backend
curl -fs http://127.0.0.1:8080/api/health   # model が 12B で status: ok（ロード 1〜2 分）
```

31B へ戻すときは「本番起動」手順を再実行（`docker compose stop vllm` を忘れない）。
`LLM_MODEL` は毎回の `docker compose up` コマンドの環境変数で切り替える（.env に書くと
戻し忘れの事故になるため推奨しない）。

### 運用上の注意

- **nubia 断 = 生成全停止**。nubia の再起動・停電後は worker 起動（手順 0）→ serve は
  自動では戻らないので `serve-31b.sh stop` → `serve-31b.sh`（クラスタが 2 GPU に戻ってから）。
- serve はコンテナ内デタッチプロセスなので、**launching したシェルや SSH が切れても生存**する。
  head コンテナを消す（`start-head.sh stop`）と一緒に死ぬ。
- 週次程度で §5 罠#3（NVML 剥がれ）の予防確認: 両ノードで `docker exec … nvidia-smi`。

---

## 7. トラブルシュート早見表

| 症状 | 見るところ | 原因と対処 |
|---|---|---|
| worker が `GCS connect timeout` を繰り返す | head は起動済みか・`HEAD_NODE_IP` は正しいか | head 未起動なら起動（worker は放置でよい — 自動再試行で参加する） |
| `ray status` が 1 ノードのまま | nubia のコンテナ生存 (`status` サブコマンド) | worker 停止済みなら手順 5 を再実行 |
| serve が数分無言 → `DistNetworkError (…, 100)` | ibera の ufw ルール | §5 罠#2。ホスト単位 allow を入れて serve 再実行 |
| `Failed to infer device type` で即死 | コンテナ内 `nvidia-smi` | §5 罠#3。NVML エラーならコンテナ再作成（head: stop→start、worker: stop→start） |
| `Engine core initialization failed` | ログ上方の最初のエラー（真因は末尾ではなく最初） | rank1（nubia 側）例外もここに集約される。NVML/FW/重み欠落を順に疑う |
| API は生きているが応答が異常に遅い | `ray status` の GPU 数・nubia の負荷 | 片系断で再スケジュールされた可能性。クラスタを組み直す |
| 当日に PP 系が復旧不能 | — | **12B へ切り戻して継続**（手順 8 の本番復帰のみ実行。品質劣化はするが全停止は回避） |

## 8. 実測値サマリと構成の限界

2026-07-18 PoC（P1〜P4 全合格）の実測:

| 項目 | 値 |
|---|---|
| コンテキスト窓 | 16,384 トークン（15,009 トークンの実プロンプト供給を確認） |
| デコード速度 | 37.9 tok/s（1 並列）/ 67.8 tok/s（4 並列合算・1.79 倍スケール） |
| TTFT | 2.0 秒 @2k / 5.9 秒 @8k プロンプト |
| prefix cache | 再送 TTFT 0.07 秒（98.8% 短縮） |
| guided JSON | 準拠 100%・オーバーヘッド −10.9%（unguided より速い） |
| VRAM | ibera 23.2GB / nubia 23.2GB（均等・層分割調整不要） |
| 重みロード〜API | 約 3 分（ページキャッシュ温存時） |

限界として、PP=2 は 1 論理インスタンスなので **nubia 断・LAN 断・Ray 断のどれでも生成が
全停止**する。冗長化はなく、緊急時は 12B 単機へ切り戻す設計（`docs/AGENT_REACT.md` §1-3）。
