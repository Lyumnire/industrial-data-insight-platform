#!/usr/bin/env bash
# AI-assisted
# A07 一键停止：按端口精确清理（5173 前端 / 8080 业务服务 / 8100 引擎）；MySQL 容器保留
set -u
for port in 5173 8080 8100; do
  PIDS=$(netstat -ano | grep ":$port" | grep LISTENING | awk '{print $5}' | sort -u)
  for pid in $PIDS; do
    taskkill //F //PID "$pid" >/dev/null 2>&1 && echo "已停止端口 $port (PID $pid)"
  done
done
echo "完成（MySQL 容器未动，如需停止：docker compose -f deploy/docker-compose.yml down）"
