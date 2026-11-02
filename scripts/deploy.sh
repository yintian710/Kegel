#!/usr/bin/env bash
# 服务器端一键更新：拉取代码，按改动范围决定是否重建前端、重启后端。
#
#   scripts/deploy.sh              拉取并按改动自动处理
#   scripts/deploy.sh --backend    不论有无改动都同步依赖并重启后端
#   scripts/deploy.sh --frontend   不论有无改动都重新构建并发布前端
#   scripts/deploy.sh --all        两者都强制执行
#
# 可用环境变量覆盖：APP_DIR、SITE_DIR、SERVICE、BRANCH、PORT。
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/kegel-v2}"
SITE_DIR="${SITE_DIR:-/srv/kegel/site}"
SERVICE="${SERVICE:-kegel-v2}"
BRANCH="${BRANCH:-main}"
PORT="${PORT:-7188}"
NODE_IMAGE="${NODE_IMAGE:-node:22-alpine}"
UV="${UV:-$(command -v uv || echo /root/.local/bin/uv)}"

force_backend=0
force_frontend=0
for arg in "$@"; do
    case "$arg" in
        --backend) force_backend=1 ;;
        --frontend) force_frontend=1 ;;
        --all) force_backend=1; force_frontend=1 ;;
        *) echo "未知参数：$arg（可用 --backend / --frontend / --all）" >&2; exit 2 ;;
    esac
done

log() { printf '\n==> %s\n' "$*"; }
cd "$APP_DIR"

# 已跟踪文件有本地修改时不覆盖，避免丢失手工改动。
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    echo "工作区存在未提交的修改，请先处理：" >&2
    git status --short --untracked-files=no >&2
    exit 1
fi

before="$(git rev-parse HEAD)"
log "拉取 origin/$BRANCH（当前 ${before:0:7}）"
GIT_TERMINAL_PROMPT=0 git fetch -q origin "$BRANCH"
git merge -q --ff-only "origin/$BRANCH"
after="$(git rev-parse HEAD)"

backend_changed=$force_backend
frontend_changed=$force_frontend
schema_changed=0
if [[ "$before" != "$after" ]]; then
    echo "更新 ${before:0:7} -> ${after:0:7}"
    git --no-pager log --oneline "$before..$after"
    changed="$(git diff --name-only "$before" "$after")"
    grep -qE '^(app/|sql/|pyproject\.toml$|uv\.lock$)' <<<"$changed" && backend_changed=1
    grep -qE '^frontend/' <<<"$changed" && frontend_changed=1
    grep -qE '^sql/' <<<"$changed" && schema_changed=1
else
    echo "代码已是最新（${after:0:7}）"
fi

if (( schema_changed )); then
    echo "注意：sql/schema.sql 有变化。脚本不会自动改库，请核对后手动执行（建表语句幂等，但不会修改已有表）。" >&2
fi

wait_healthy() {
    for _ in $(seq 1 30); do
        curl -fsS -o /dev/null "http://127.0.0.1:${PORT}/health" && return 0
        sleep 1
    done
    return 1
}

deploy_backend() {
    log "后端：同步依赖并重启 $SERVICE"
    "$UV" sync --frozen --no-dev --python 3.12 -q
    systemctl restart "$SERVICE"
    if wait_healthy; then
        echo "后端健康检查通过"
        return 0
    fi
    echo "后端启动失败，回滚到 ${before:0:7}" >&2
    journalctl -u "$SERVICE" -n 15 --no-pager >&2 || true
    git reset -q --hard "$before"
    "$UV" sync --frozen --no-dev --python 3.12 -q
    systemctl restart "$SERVICE"
    wait_healthy && echo "已回滚并恢复服务" >&2
    return 1
}

build_frontend() {
    local node_major=0
    command -v node >/dev/null && node_major="$(node -p 'process.versions.node.split(".")[0]')"
    if command -v pnpm >/dev/null && (( node_major >= 22 )); then
        echo "使用本机 Node $node_major + pnpm 构建"
        (cd frontend && pnpm install --frozen-lockfile && pnpm build)
    elif command -v docker >/dev/null; then
        echo "本机 Node 版本不足，使用 $NODE_IMAGE 容器构建"
        docker run --rm -v "$APP_DIR/frontend:/app" -w /app "$NODE_IMAGE" \
            sh -c 'npm install -g pnpm@10 >/dev/null 2>&1 && pnpm install --frozen-lockfile && pnpm build'
    else
        echo "没有可用的构建环境：需要 Node >= 22 + pnpm，或 Docker" >&2
        return 1
    fi
    [[ -f frontend/dist/index.html ]] || { echo "构建产物缺少 index.html" >&2; return 1; }
}

deploy_frontend() {
    log "前端：构建并发布到 $SITE_DIR"
    build_frontend
    local stamp incoming prev
    stamp="$(date +%Y%m%d%H%M%S)"
    incoming="${SITE_DIR}.incoming.${stamp}"
    prev="${SITE_DIR}.prev.${stamp}"
    cp -r frontend/dist "$incoming"
    find "$incoming" -type d -exec chmod 755 {} +
    find "$incoming" -type f -exec chmod 644 {} +
    mv "$SITE_DIR" "$prev"
    mv "$incoming" "$SITE_DIR"
    echo "前端已发布；上一版本保留在 $prev"
}

status=0
if (( backend_changed )); then
    deploy_backend || status=1
else
    echo "后端无改动，跳过"
fi
if (( frontend_changed )); then
    deploy_frontend || status=1
else
    echo "前端无改动，跳过"
fi

log "完成：当前 $(git rev-parse --short HEAD)，服务 $(systemctl is-active "$SERVICE")"
exit "$status"
