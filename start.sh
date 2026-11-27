#!/usr/bin/env bash
# 本地开发一键启动：后端 uvicorn(7188) + 前端 vite(5173)。Ctrl+C 同时退出。
set -euo pipefail
cd "$(dirname "$0")"

PY=".venv/bin/uvicorn"
if [ ! -x "$PY" ]; then
  echo "未找到 .venv，请先执行: uv sync" >&2
  exit 1
fi
if [ ! -f .env ]; then
  echo "未找到 .env，请先: cp .env.example .env 并填写配置" >&2
  exit 1
fi
if [ ! -d frontend/node_modules ]; then
  (cd frontend && pnpm install)
fi

# Apple Silicon 上 .venv 为 arm64 构建，避免被 Rosetta 终端拉成 x86_64
RUN=()
if [ "$(uname -s)" = "Darwin" ] && arch -arm64 true 2>/dev/null; then
  RUN=(arch -arm64)
fi

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

${RUN[@]+"${RUN[@]}"} "$PY" app.server:app --host 127.0.0.1 --port 7188 --reload &
pids+=($!)
(cd frontend && exec pnpm dev) &
pids+=($!)

echo "后端: http://127.0.0.1:7188   前端: http://localhost:5173"
wait
