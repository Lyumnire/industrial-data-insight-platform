#!/usr/bin/env bash
# AI-assisted
# 官方 mysql 镜像入口会对 secure-file-priv 指向目录做 chown，故 CSV 源目录必须只读挂载；
# 本脚本把 CSV 拷入可写的 /tmp，供 04_load_data.sql 的 LOAD DATA INFILE 使用（secure-file-priv=/tmp）。
set -e
cp -f /var/lib/csv-src/*.csv /tmp/
ls -l /tmp/*.csv
