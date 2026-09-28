#!/usr/bin/env bash
# AI-assisted: P1 阶段门禁（docs/04-多Agent协作与团队规范.md §6）
# 用法: bash deploy/gate.sh   —— 任一门禁失败即退出码 1，禁止带病进入下一阶段
# Windows: 请用 Git Bash（"C:\Program Files\Git\bin\bash.exe" deploy/gate.sh）；
#   在 pwsh/cmd 里直接 `bash` 可能进入 WSL 导致找不到 /bin/bash（OPS-003）。
set -uo pipefail
cd "$(dirname "$0")/.."
FAIL=0

step() { echo; echo "======== GATE: $1 ========"; }

step "Python 引擎测试"
( cd a07-agent && .venv/Scripts/python -m pytest tests -q ) || FAIL=1

if [ -f a07-server/pom.xml ]; then
  step "Java 测试 (mvnw)"
  ( cd a07-server && ./mvnw -q test ) || FAIL=1
else
  echo "SKIP: a07-server 尚未初始化"
fi

if [ -f a07-web/package.json ]; then
  step "前端 type-check + build"
  ( cd a07-web && npm run type-check && npm run build ) || FAIL=1
else
  echo "SKIP: a07-web 尚未初始化"
fi

step "端到端冒烟（需 E2E_SMOKE=1 + 引擎运行 + LLM Key；未配置时自动 SKIP）"
( cd a07-agent && E2E_SMOKE=${E2E_SMOKE:-0} .venv/Scripts/python -m pytest tests/e2e_smoke.py -q ) || FAIL=1

echo
if [ "$FAIL" -eq 0 ]; then echo "[GATE] ✅ 全部通过"; else echo "[GATE] ❌ 存在失败项，禁止进入下一阶段"; fi
exit $FAIL
