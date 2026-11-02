#!/usr/bin/env bash
# 构建前端并同步到静态托管目录。用法：DEPLOY_DIR=/var/www/kegel scripts/update-frontend.sh
# 构建 base 为 /（见 frontend/vite.config.ts），DEPLOY_DIR 应对应反向代理里站点根路径的静态目录。
set -euo pipefail

: "${DEPLOY_DIR:?请设置 DEPLOY_DIR 为静态文件目标目录（本机路径，或 rsync 支持的 user@host:/path）}"

cd "$(dirname "$0")/../frontend"
pnpm install --frozen-lockfile
pnpm build
rsync -a --delete dist/ "$DEPLOY_DIR"/
echo "前端已发布到 $DEPLOY_DIR"
