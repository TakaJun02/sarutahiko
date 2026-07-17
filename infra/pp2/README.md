# FR-34 Gemma 4 31B PP=2 PoC 実施キット

このディレクトリは `docs/AGENT_REACT.md` v0.1 §1・§6 の P1〜P4 を短時間で確認するための
起動スクリプト、計測ランナー、利用者向け手順書である。構成は ibera（Ray head / API、RTX 3090 Ti）
と nubia（Ray worker、RTX 3090）に 1 GPU ずつ割り当て、`PP=2, TP=1` の単一 OpenAI 互換
エンドポイントを ibera に立てる。

このキットの作成作業では、クラスタ起動、モデル重みのダウンロード、ベンチマークを実行していない。
以下の操作はすべて利用者が実機で行う。既存の `docker-compose.yml`、`backend/`、`frontend/` は
変更していない。

## ファイル

| ファイル | 用途 |
|---|---|
| `start-worker-nubia.sh` | nubia で Ray worker コンテナを起動し、ibera head が立つまで再試行する |
| `start-head.sh` | ibera で Ray head コンテナを起動する |
| `serve-31b.sh` | head コンテナ内で Gemma 4 31B を PP=2 で serve する |
| `verify_p1.py` | `/v1/models`、約 15k context、1/4 並列 TTFT・tok/s、prefix cache を実測する |
| `verify_p2.py` | guided / unguided を各 20 回呼び、decide スキーマ準拠率と overhead を測る |
| `run_p3.py` | EVAL 10 問＋指定 4 問の 1 手目・モック観測後 2 手目を保存する |
| `cluster-common.sh` / `poc_common.py` | 上記スクリプトの共通処理（単独実行しない） |

計測結果は実行時に `infra/pp2/results/` へ UTC timestamp 付き JSON と Markdown で保存される。
各ランナーは Python 標準ライブラリだけを使い、既定 endpoint は
`http://127.0.0.1:8000/v1` である。

## 0. 重要な運用条件

- vLLM イメージは両筐体とも **`vllm/vllm-openai:v0.25.0` 固定**。`:latest` は使わない。
- shell スクリプトはプロジェクトルートの `.env`（または `ENV_FILE`）を source し、nubia の
  アドレスを **`Inference_sever`** から読む。この綴りは変更しない。
- ibera のアドレスは `HEAD_NODE_IP` で渡す。スクリプトや README に実 IP、HF token、API key を
  書かない。
- 両コンテナは `HF_HUB_OFFLINE=1` が既定で、serve 時の意図しない重みダウンロードを防ぐ。
  モデルは事前に両筐体の HF cache に同じ revision で存在する必要がある。
- PP=2 は冗長化ではない。nubia、LAN、Ray のいずれかが失われると生成 API 全体が停止する。
- Ray / NCCL / Gloo は host network を使う。2 筐体間の通信を firewall で許可し、外部ネットワークへ
  Ray port を公開しない。

## 1. 両筐体の前提チェック

### 1-1. NVIDIA driver / Docker / NVIDIA Container Toolkit

【利用者・ibera】以下を実行する。

```bash
nvidia-smi
docker version
docker info --format '{{json .Runtimes}}'
nvidia-ctk --version
```

【利用者・nubia】同じ 4 コマンドを nubia でも実行する。`docker info` に `nvidia` runtime があり、
両方の `nvidia-smi` で対象 GPU が見えることを確認する。

イメージ取得後は、コンテナからも GPU が見えることを両筐体で確認する（追加イメージを pull しない）。

【利用者・ibera】

```bash
docker run --rm --gpus all --entrypoint nvidia-smi vllm/vllm-openai:v0.25.0
```

【利用者・nubia】同じコマンドを nubia でも実行する。

`nvidia-ctk` がない、`--gpus all` が失敗する、driver/CUDA compatibility error が出る場合は、
クラスタ起動へ進まず NVIDIA Container Toolkit の導入・再設定を先に行う。

### 1-2. 31B HF cache の残存確認（ネットワークアクセスなし）

ibera は 2026-07-12 以前に 31B を使用していたため cache が残っている可能性が高い。
次の確認はローカルファイルだけを読む。

【利用者・ibera】

```bash
MODEL_CACHE="${HF_HOME:-${HOME}/.cache/huggingface}/hub/models--google--gemma-4-31B-it-qat-w4a16-ct"
test -d "${MODEL_CACHE}" && echo "cache directory exists" || echo "cache directory missing"
find "${MODEL_CACHE}/snapshots" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null
cat "${MODEL_CACHE}/refs/main" 2>/dev/null
du -sh "${MODEL_CACHE}" 2>/dev/null
```

【利用者・nubia】同じ 4 コマンドを nubia でも実行する。root で cache を作った場合など、場所が
異なるときは `HF_CACHE_DIR=/実際の/huggingface/cache` を起動時に export する。

両筐体で `refs/main` の revision 文字列が一致し、その revision 名の snapshot directory が存在する
ことを確認する。snapshot 内の `config.json` と weight shard が symlink 切れしていないことも確認する。

【利用者・ibera】

```bash
REVISION="$(cat "${MODEL_CACHE}/refs/main")"
test -f "${MODEL_CACHE}/snapshots/${REVISION}/config.json"
find -L "${MODEL_CACHE}/snapshots/${REVISION}" -type l -print
```

【利用者・nubia】同じ確認を行う。最後の `find` が何か表示した場合は broken symlink であり不完全な
cache である。

cache がない、revision が違う、shard が欠ける場合、PoC キットは自動取得しない。モデルは約 17GB で
gated の可能性があるため、Hugging Face 上で利用条件への同意と認証を済ませた上で、利用者が別作業として
両筐体へ同一 revision を用意する。用意できるまで `serve-31b.sh` は実行しない。

### 1-3. vLLM 0.25.0 image と digest の固定

【利用者・ibera】

```bash
docker pull vllm/vllm-openai:v0.25.0
docker image inspect vllm/vllm-openai:v0.25.0 \
  --format '{{range .RepoDigests}}{{println .}}{{end}}'
docker run --rm --entrypoint python3 vllm/vllm-openai:v0.25.0 \
  -c 'import vllm; print(vllm.__version__)'
```

【利用者・nubia】同じ 3 コマンドを実行する。version が両方 `0.25.0`、RepoDigest が完全一致する
ことを確認する。multi-node では vLLM / Ray / CUDA の差異が典型的な起動失敗原因になる。

**派生イメージのビルド（必須・両筐体）**: 公式 `vllm/vllm-openai:v0.25.0` は **ray を同梱しない**
（2026-07-18 の PoC 実施で判明。`ray` CLI も `import ray` も存在しない）。Ray クラスタ用に
以下の派生イメージを両筐体でビルドする。起動スクリプトの既定イメージはこの派生タグ
（`pp2-vllm:v0.25.0-ray`。`PP2_IMAGE` で上書き可）。

```bash
docker build -t pp2-vllm:v0.25.0-ray - <<'EOF'
FROM vllm/vllm-openai:v0.25.0
RUN pip install --no-cache-dir "ray[default,cgraph]"
EOF
```

- digest 照合は**ベースイメージ**（`vllm/vllm-openai:v0.25.0`）で行う（派生イメージの digest は
  ビルドごとに変わるため比較対象にしない）。ray のバージョンは両筐体のビルドログで一致を確認する。
- TODO（PoC 合格後・仕様 v1.0 で対応）: PoC で検証された ray バージョンを `ray[default,cgraph]==X`
  に固定する。

実施時に以下へ転記する。

| host | image tag | base RepoDigest | `vllm.__version__` | ray | 確認日 |
|---|---|---|---|---|---|
| ibera | `pp2-vllm:v0.25.0-ray` | （利用者記録） | （利用者記録） | （利用者記録） | （利用者記録） |
| nubia | `pp2-vllm:v0.25.0-ray` | （利用者記録） | （利用者記録） | （利用者記録） | （利用者記録） |

### 1-4. `.env`、LAN IP、NIC

【利用者・ibera】プロジェクトルートの `.env` に `Inference_sever=<nubia の LAN IP>` が存在する
ことだけを確認する。値はログやレビューへ貼らない。

```bash
set -a
source .env
set +a
test -n "${Inference_sever}"
ip route get "${Inference_sever}"
```

【利用者・ibera】同じ `ip route get` 出力の `src` を ibera の `HEAD_NODE_IP`、`dev` を利用 NIC として
控える。

【利用者・nubia】`infra/pp2/` を同じ相対位置へ安全にコピーする。nubia 側にも source 可能な `.env` を
用意し、最低限 `Inference_sever=<nubia 自身の LAN IP>` を含める。ibera の `.env` に含まれる API key を
コピーする必要はない。別位置に置く場合は `ENV_FILE=/path/to/.env` を export する。

【利用者・nubia】ibera のアドレスへの経路と NIC を確認する。

```bash
export HEAD_NODE_IP='<ibera の LAN IP>'
ip route get "${HEAD_NODE_IP}"
```

自動検出された NIC が意図と違う場合は、両筐体で `PP2_NIC` を明示する。NCCL と Gloo を別指定
したい場合は `NCCL_SOCKET_IFNAME` / `GLOO_SOCKET_IFNAME` を直接 export できる。

```bash
export PP2_NIC='<利用する NIC 名>'
```

Ray の既定 GCS port は `6379`。上書きする場合は両筐体で同じ `RAY_PORT` を export する。
このキットは node/object manager を `10002/10003`、worker range を `11000-11999` に固定し、各値も
`RAY_NODE_MANAGER_PORT`、`RAY_OBJECT_MANAGER_PORT`、`RAY_MIN_WORKER_PORT`、
`RAY_MAX_WORKER_PORT` で上書きできる。最も確実な PoC firewall 条件は、外部からは閉じたまま、ibera と
nubia の正確な 2 IP 間だけ双方向 TCP を許可することである。

## 2. 起動手順（nubia worker → ibera head → serve → 検証）

### 2-1. 既存 12B の停止

port 8000 の競合を避けるため、現行 compose の backend / vLLM を停止する。Qdrant data は削除しない。

【利用者・ibera】

```bash
cd /home/junta_takahashi/oc_2026
docker compose stop backend vllm
```

### 2-2. nubia worker を先に起動

worker container は head がまだなくても終了せず、5 秒ごとに join を再試行する。

【利用者・nubia】新しい shell で、コピーしたプロジェクトディレクトリから実行する。

```bash
export HEAD_NODE_IP='<ibera の LAN IP>'
# 必要な場合のみ: export ENV_FILE=/path/to/.env
# 必要な場合のみ: export PP2_NIC='<nubia の LAN NIC>'
./infra/pp2/start-worker-nubia.sh
./infra/pp2/start-worker-nubia.sh status
```

待機ログを見る場合:

【利用者・nubia】

```bash
./infra/pp2/start-worker-nubia.sh logs
```

### 2-3. ibera head を起動

【利用者・ibera】

```bash
cd /home/junta_takahashi/oc_2026
export HEAD_NODE_IP='<ibera の LAN IP>'
# 必要な場合のみ: export PP2_NIC='<ibera の LAN NIC>'
./infra/pp2/start-head.sh
./infra/pp2/start-head.sh status
```

`ray status` に 2 nodes、resource に `GPU: 2.0` が現れるまで serve へ進まない。nubia が参加しない場合は、
両側の NIC、firewall、`RAY_PORT`、image digest、時刻同期を確認する。

### 2-4. Gemma 4 31B を serve

【利用者・ibera】別 shell で foreground 起動する。初回は層分割を指定せず、vLLM の均等分割で測る。

```bash
cd /home/junta_takahashi/oc_2026
./infra/pp2/serve-31b.sh
```

既定引数は次のとおり。

```text
--distributed-executor-backend ray
--pipeline-parallel-size 2
--tensor-parallel-size 1
--max-model-len 16384
--max-num-seqs 4
--gpu-memory-utilization 0.92
--limit-mm-per-prompt '{"image": 0}'
--enable-prefix-caching
```

`--enforce-eager` は旧 31B 単カード構成から持ち込まない。主要値は次の環境変数で上書きできる。

| env | 既定値 |
|---|---:|
| `PP2_MODEL` | `google/gemma-4-31B-it-qat-w4a16-ct` |
| `PIPELINE_PARALLEL_SIZE` | `2` |
| `TENSOR_PARALLEL_SIZE` | `1` |
| `MAX_MODEL_LEN` | `16384` |
| `MAX_NUM_SEQS` | `4` |
| `GPU_MEMORY_UTILIZATION` | `0.92` |
| `LIMIT_MM_PER_PROMPT` | `{"image": 0}` |
| `VLLM_HOST` / `VLLM_PORT` | `127.0.0.1` / `8000` |
| `ENABLE_PREFIX_CACHING` | `1` |
| `ENABLE_NATIVE_TOOL_CALLING` | `0` |
| `VLLM_CHAT_TEMPLATE` | 未設定（native 試験時のみ任意） |

API は安全のため ibera loopback bind が既定。別 host/container から接続する検証だけ
`VLLM_HOST=0.0.0.0` にし、必ず firewall で nubia/Ray port と API port の公開範囲を制限する。

### 2-5. API と P1〜P4 用データの検証

【利用者・ibera】serve ログが ready になってから実行する。

```bash
curl -fsS http://127.0.0.1:8000/version
curl -fsS http://127.0.0.1:8000/v1/models
python3 infra/pp2/verify_p1.py
python3 infra/pp2/verify_p2.py
python3 infra/pp2/run_p3.py
```

- `verify_p1.py`: P1 の約 15k 実プロンプト、1/4 並列性能と、P4 の prefix-cache TTFT 短縮を記録する。
- `verify_p2.py`: guided 20 回＋同一 prompt の unguided 20 回を行い、P2 準拠率と 1 decide の latency
  overhead を記録する。
- `run_p3.py`: `EVAL_QUESTIONS.md` の A〜I 各カテゴリ先頭＋頑健性先頭を機械選択した 10 問と、指定
  4 問を実行する。合否は付けず、Fable が JSON を定性判定する。0-tool finish 率と同一 action 反復率は
  診断値としてのみ保存する。
- P4 は `verify_p1.py` の TTFT/prefix、`verify_p2.py` の 1 decide、`run_p3.py` の 2 decide 分の
  latency を材料にする。試作 harness は実ツールを実行しないため、代表質問 E2E 60 秒の最終合否は
  ツール latency を足した実装前レビューで Fable が判断する。

endpoint と model は全ランナーで切替できる。`POC_MODEL` 未指定なら `/v1/models` の先頭を使う。

【利用者・ibera】現行 12B endpoint で機構だけ先に素振りする例:

```bash
VLLM_BASE_URL=http://127.0.0.1:8000/v1 \
P1_CONTEXT_TOKENS=7000 \
python3 infra/pp2/verify_p1.py
```

共通 timeout は `POC_TIMEOUT_SECONDS`（既定 900 秒）。P1 は
`P1_CONTEXT_TOKENS` / `P1_PERF_PROMPT_TOKENS` / `P1_PERF_OUTPUT_TOKENS` /
`P1_PREFIX_TOKENS`、P2 は `P2_ITERATIONS`、P3 は `P3_MAX_TOKENS` 等で短縮できる。
正式な P2 は `P2_ITERATIONS=20` の既定値で行う。

## 3. `VLLM_PP_LAYER_PARTITION` の調整

初回は未設定（均等）で P1 を保存する。3090 Ti と 3090 の差により遅い nubia stage が律速する場合だけ、
ibera stage へ 1〜2 層ずつ寄せて再測定する。層数は model cache の config から確認し、推測しない。

【利用者・ibera】

```bash
MODEL_CACHE="${HF_HOME:-${HOME}/.cache/huggingface}/hub/models--google--gemma-4-31B-it-qat-w4a16-ct"
REVISION="$(cat "${MODEL_CACHE}/refs/main")"
python3 - "${MODEL_CACHE}/snapshots/${REVISION}/config.json" <<'PY'
import json
import sys

config = json.load(open(sys.argv[1], encoding="utf-8"))
layers = config.get("num_hidden_layers")
if layers is None:
    layers = config.get("text_config", {}).get("num_hidden_layers")
print(layers)
PY
```

`VLLM_PP_LAYER_PARTITION='N,M'` は stage 0（通常 ibera）と stage 1（通常 nubia）の層数で、`N+M` は
上で確認した総層数と一致させる。起動ログで stage / node 対応を必ず確認する。

例の数値をコピーせず、実際の総層数から値を計算する。同じ値を worker/head/serve の全 process に渡す
ため、cluster を完全再起動する。

【利用者・nubia】worker を停止し、計算済みの同じ partition を export して先に起動する。

```bash
./infra/pp2/start-worker-nubia.sh stop
export VLLM_PP_LAYER_PARTITION='<ibera の層数>,<nubia の層数>'
./infra/pp2/start-worker-nubia.sh
```

【利用者・ibera】head を停止し、nubia と同じ partition を export して head、serve の順に起動する。

```bash
./infra/pp2/start-head.sh stop
export VLLM_PP_LAYER_PARTITION='<ibera の層数>,<nubia の層数>'
./infra/pp2/start-head.sh
./infra/pp2/serve-31b.sh
```

各 partition で P1 JSON を別保存し、TTFT・decode tok/s・両 GPU 使用量・OOM の有無を比較する。
ibera 側 OOM なら ibera の層を減らす。nubia 側 OOM または明確な律速なら逆に調整する。partition 変更は
既存 serve へ動的反映されないので、必ず §5 の完全再起動を行う。

## 4. native tool calling 調査結論

**結論: vLLM 0.25.0 には Gemma 4 用 `gemma4` tool-call parser があり、native tool calling の機構上の
対応はある。** 自動 tool choice には `--enable-auto-tool-choice --tool-call-parser gemma4` を使う。
vLLM の Gemma 4 recipe も同じ起動形を示している。

- v0.25.0 Tool Calling: https://docs.vllm.ai/en/v0.25.0/features/tool_calling/
- v0.25.0 parser API（Gemma4 parser を収載）: https://docs.vllm.ai/en/v0.25.0/api/vllm/parser/
- vLLM official Gemma 4 recipe: https://github.com/vllm-project/recipes/blob/main/Google/Gemma4.md

ただし、このタスクでは `google/gemma-4-31B-it-qat-w4a16-ct` と PP=2 に対する parser の安定性を
実測していない。また v0.25.0 の一般 Tool Calling ページで明示される Gemma 系モデル例は
FunctionGemma が中心である。したがって FR-34 v0.1 の裁定どおり、P2 の主対象は model 非依存の
guided JSON (`response_format.type=json_schema`) とし、native は「利用可能だが未昇格」とする。

試験的に server flag だけ有効化する場合は次を付けて完全再起動する。guided JSON の P2 結果と混ぜず、
別記録にする。

【利用者・ibera】

```bash
export ENABLE_NATIVE_TOOL_CALLING=1
./infra/pp2/serve-31b.sh
```

model 同梱 template で tool protocol が成立しない場合だけ、公式 container 内の template path を
`VLLM_CHAT_TEMPLATE` で明示できる。本 PoC では Gemma 4 の thinking 用 parser や
`chat_template_kwargs` を送らない。

## 5. 停止・完全再起動

### 通常停止

`serve-31b.sh` の foreground shell で `Ctrl-C` 後、head、worker の順に ephemeral container を消す。
HF cache は bind mount であり削除されない。

【利用者・ibera】

```bash
./infra/pp2/start-head.sh stop
```

【利用者・nubia】

```bash
./infra/pp2/start-worker-nubia.sh stop
```

### nubia 断 / LAN 断 / Ray 断

| 障害 | 典型症状 | 確認 |
|---|---|---|
| nubia 電源・container 断 | 生成中断、API hang/5xx、Ray actor/node lost | ibera `start-head.sh status`、nubia `start-worker-nubia.sh status` |
| LAN / NIC 断 | NCCL/Gloo timeout、Ray heartbeat timeout、GPU utilization 停止 | 両側 `ip route get`、`ping`、container logs |
| Ray head/worker 断 | `ray status` から node/GPU が消える、serve process 終了 | ibera `start-head.sh status` と `start-head.sh logs` |

PP request の途中復旧や worker だけの差し戻しは行わない。通信を直した後、古い actor / NCCL process を
残さないため **worker/head/serve を完全再起動**する。

【利用者・ibera】head を停止する。

```bash
./infra/pp2/start-head.sh stop
```

【利用者・nubia】worker を停止してから §2-2 の worker start を再実行する。

```bash
./infra/pp2/start-worker-nubia.sh stop
./infra/pp2/start-worker-nubia.sh
```

【利用者・ibera】§2-3 の head、§2-4 の serve の順で再起動し、`GPU: 2.0` と `/v1/models` を再確認する。

## 6. 緊急切り戻し（現行 12B 単機 compose）

オープンキャンパス当日に PP 系が不安定なら、品質劣化を受け入れて現行
`google/gemma-4-12B-it-qat-w4a16-ct` 単機構成へ戻す。既存 compose 定義はこのキットで変更していない。

【利用者・ibera】PP head を停止する。

```bash
cd /home/junta_takahashi/oc_2026
./infra/pp2/start-head.sh stop
```

【利用者・nubia】worker を停止する。

```bash
./infra/pp2/start-worker-nubia.sh stop
```

【利用者・ibera】12B と backend を既存 compose から起動する。

```bash
cd /home/junta_takahashi/oc_2026
docker compose up -d backend
docker compose ps
curl -fsS http://127.0.0.1:8000/v1/models
curl -fsS http://127.0.0.1:8080/api/health
```

`backend` の `depends_on` により既存 `vllm` と `qdrant` も起動する。切り戻し時は PP 用 env export が
残った shell を使い回さず、新しい shell で compose を起動する。12B が応答することを確認してから
来場者向け Nginx endpoint を復帰確認する。
