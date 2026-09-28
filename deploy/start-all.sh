#!/usr/bin/env bash
# AI-assisted
# A07 一键启动（Windows Git Bash）：MySQL(Docker) + Agent 引擎 + 业务服务 + 前端
# 用法：bash deploy/start-all.sh   停止：bash deploy/stop-all.sh
# 日志：deploy/logs/*.log；演示期间请保持运行窗口开启（Git Bash 关窗会带走子进程）
set -u
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
mkdir -p deploy/logs

# ---- 读取根目录 .env（不回显任何值，红线 R3）----
if [ -f .env ]; then
  while IFS='=' read -r k v; do
    case "$k" in
      \#*|"") ;;
      MYSQL_HOST|MYSQL_PORT|MYSQL_DB|MYSQL_READONLY_USER|JWT_SECRET) export "$k=$v" ;;
    esac
  done < .env
fi
MYSQL_HOST="${MYSQL_HOST:-localhost}"; MYSQL_PORT="${MYSQL_PORT:-3306}"

echo "==== [1/4] MySQL (Docker) ===="
docker compose -f deploy/docker-compose.yml up -d mysql
for i in $(seq 1 24); do
  ST=$(docker inspect -f '{{.State.Health.Status}}' a07-mysql 2>/dev/null)
  [ "$ST" = "healthy" ] && echo "MySQL healthy ✓" && break
  sleep 5
done

echo "==== [2/4] Agent 引擎 (8100) ===="
(cd a07-agent && nohup .venv/Scripts/python -m uvicorn app.main:app --host 0.0.0.0 --port 8100 \
  > ../deploy/logs/agent.log 2>&1 & echo $! > ../deploy/logs/agent.pid)
for i in $(seq 1 20); do
  curl -sf http://localhost:8100/health >/dev/null 2>&1 && echo "引擎 ready ✓" && break
  sleep 2
done

echo "==== [3/4] 业务服务 (8080, MySQL 实库模式) ===="
(cd a07-server && \
  MYSQL_URL="jdbc:mysql://${MYSQL_HOST}:${MYSQL_PORT}/a07_platform?useSSL=false&allowPublicKeyRetrieval=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai" \
  MYSQL_USER=root MYSQL_PASSWORD=a07root \
  nohup ./mvnw spring-boot:run > ../deploy/logs/server.log 2>&1 & echo $! > ../deploy/logs/server.pid)
for i in $(seq 1 30); do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8080/api/auth/login \
    -H "Content-Type: application/json" -d '{}' 2>/dev/null)
  [ "$CODE" = "400" ] && echo "业务服务 ready ✓" && break
  sleep 3
done

echo "==== [4/4] 前端 dev (5173) ===="
(cd a07-web && nohup npm run dev > ../deploy/logs/web.log 2>&1 & echo $! > ../deploy/logs/web.pid)
for i in $(seq 1 15); do
  curl -sf -o /dev/null http://localhost:5173/ && echo "前端 ready ✓" && break
  sleep 2
done

echo
echo "全部就绪后访问 http://localhost:5173 （账号 user/user123456）"
echo "停止请执行：bash deploy/stop-all.sh"
