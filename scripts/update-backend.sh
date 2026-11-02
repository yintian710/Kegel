#!/usr/bin/env bash
# 同步依赖并重启单机 uvicorn 进程。用法：scripts/update-backend.sh
# 可选环境变量：PID_FILE（默认 run/uvicorn.pid）、LOG_FILE（默认 run/uvicorn.log）
set -euo pipefail

cd "$(dirname "$0")/.."
PID_FILE="${PID_FILE:-run/uvicorn.pid}"
LOG_FILE="${LOG_FILE:-run/uvicorn.log}"
mkdir -p "$(dirname "$PID_FILE")"

uv sync --frozen --no-dev

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    kill "$(cat "$PID_FILE")"
    for _ in $(seq 1 20); do
        kill -0 "$(cat "$PID_FILE")" 2>/dev/null || break
        sleep 0.5
    done
fi

# 端口与监听地址由 .env 的 HOST / PORT 决定（默认 127.0.0.1:7188）。
set -a
[[ -f .env ]] && source .env
set +a
nohup uv run --no-dev uvicorn app.server:app \
    --host "${HOST:-127.0.0.1}" --port "${PORT:-7188}" >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
echo "uvicorn 已启动 pid=$(cat "$PID_FILE")，日志：$LOG_FILE"
