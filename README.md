# campus-guide-agent

秋田県立大学 本荘キャンパスの学内情報を答える AI エージェント（オープンキャンパス 2026 来場者向け）。

- Agentic RAG + Web Search、ローカル LLM（vLLM）、推論ステップの実況表示
- 仕様: [`docs/SPEC.md`](docs/SPEC.md) ／ 構成: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- 開発体制: 仕様・レビュー = Claude (Fable)、実装・サーベイ = Codex — 詳細は [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md)

## Docker Compose 起動

vLLM は RTX 3090 Ti 上で検証済みの `Qwen/Qwen3-14B-AWQ` 設定で起動します。
ホストの Hugging Face キャッシュ `~/.cache/huggingface` を再利用します。

```bash
docker compose up -d qdrant vllm
python -m pip install -r backend/requirements.txt
python knowledge/ingest/ingest.py --recreate
docker compose up -d backend frontend
```

起動後:

- Frontend: http://localhost:5173
- Backend health: http://localhost:8080/api/health
- vLLM: http://localhost:8000/v1
- Qdrant: http://localhost:6333

## ローカル開発起動

### Backend

```bash
cd backend
python -m pip install -r requirements.txt
AGENT_MODE=mock uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

実エージェントをローカルで使う場合は、リポジトリルートで別途 vLLM と Qdrant を起動し、ナレッジを投入してから起動します。

```bash
docker compose up -d qdrant vllm
python knowledge/ingest/ingest.py --recreate
cd backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

SQLite は既定で `backend/data/campus-guide.sqlite3` に作成されます。設定例は `.env.example` を参照してください。

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Vite dev server は `/api` を既定で `http://127.0.0.1:8080` にプロキシします。
必要に応じて `VITE_API_PROXY_TARGET` でプロキシ先を上書きできます。

### Verification

```bash
cd frontend && npm run build
cd ..
pytest
```
