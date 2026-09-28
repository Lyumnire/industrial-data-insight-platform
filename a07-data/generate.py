# AI-assisted (T-002 数据底座 v1 / T-015 数据底座补全 · 数据评测组 · 复核人: 待主控评审后填写)
# ============================================================================
# mes_demo 合成数据生成器 (P1 三表 + T-015 增补两表)
# 规范来源: docs/plans/2026-09-19-P1-走通骨架.md §Task 2 Step 2.2、docs/tasks/T-002-数据底座v1.md、
#           docs/tasks/T-015-数据底座补全.md
#
# 【硬约束 · 后续读者必读】
#   1) 仅用 Python 标准库(random/csv/statistics/datetime 等), 禁止引入 numpy/pandas;
#      本机 Python 3.10, 不使用 3.11+ 特性。
#   2) random.seed(42) 固定: 同一解释器下重复运行, 输出 CSV 逐字节一致(可复现)。
#      新增两表(工单/库存)的随机消耗追加在三张原表之后, 保证原三表 CSV 逐字节不变。
#   3) 数据刻意注入 8 条业务规律(供检索/NL2SQL/异常分析演示与评测):
#        R-A  L3 产线最后 30 天产量环比约 -15%(末段产量因子由 0.93 线性降至 0.78);
#        R-B  "焊接"工序良率基线比其余工序低约 5 个百分点(基线不良率 0.08 vs 0.02~0.045);
#        R-C  "划痕"缺陷在最后 21 天的占比约翻倍(0.28 -> 0.56, 其余类型等比压缩);
#        R-D  设备 EQ-07(L2) 注入 5 次 >120 分钟长停机(总停机时长全厂第一);
#        R-E  (inventory_records) P-1003 库存近 60 天持续走高(呆滞, 期末较期初约 +80%);
#        R-F  (inventory_records) WH-02 每周五出库高峰(约为其他日期的 2.2~2.6 倍);
#        R-G  (inventory_records) P-1001 近 14 天跌破安全库存线(安全库存=其日均出库 x 7);
#        R-H  (production_orders) L2(长停机产线) 最近 30 天"已暂停"工单占比显著高于其他产线。
#   4) 程序末尾打印统计摘要并逐条断言上述规律与行数达标, 任一断言失败即以
#      非零退出码结束(AssertionError 向上抛出)。
#   5) CSV 列与 sql/01_mes_demo_ddl.sql(三表)、sql/06_orders_inventory_ddl.sql(两表)
#      字段一一对应(不含自增 id 列); defect_type 为空字符串表示该检验批次无不良;
#      actual_end 为 None 表示工单未完成, 写出为字面量 NULL(LOAD DATA 读作 NULL)。
#
# 产出: a07-data/generated/process_output.csv         约 8.1 万行
#       a07-data/generated/quality_inspections.csv    约 2.0 万行
#       a07-data/generated/equipment_downtime.csv     约 1500 行
#       a07-data/generated/production_orders.csv      约 3000 行 (T-015)
#       a07-data/generated/inventory_records.csv      约 3240 行 (T-015)
# ============================================================================

import csv
import random
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# ---------------- 全局常量(与 sql/01_mes_demo_ddl.sql 注释口径一致) ----------------
BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "generated"

SEED = 42
DAYS = 90
END_DATE = date(2026, 9, 18)  # 固定数据截止日以保证可复现; 如需对齐演示日可整体平移后重新生成

LINES = ["L1", "L2", "L3"]
PROCESSES = ["注塑", "焊接", "装配", "喷涂", "包装"]
# R-B 约束: 焊接基线不良率 0.08, 其余工序 0.02~0.045, 即焊接良率低约 5 个百分点
PROCESS_BASE_DEFECT_RATE = {"注塑": 0.030, "焊接": 0.080, "装配": 0.035, "喷涂": 0.045, "包装": 0.020}

PRODUCTS = [
    ("P-1001", "仪表板总成"),
    ("P-1002", "前保险杠"),
    ("P-1003", "车门内板"),
    ("P-1004", "大灯支架"),
    ("P-1005", "进气歧管"),
    ("P-1006", "后视镜外壳"),
]

DEFECT_TYPES = ["划痕", "气泡", "尺寸偏差", "色差", "变形"]
SCRATCH = "划痕"
DEFECT_WEIGHTS_BASE = {"划痕": 0.28, "气泡": 0.22, "尺寸偏差": 0.25, "色差": 0.15, "变形": 0.10}
# R-C 约束: 最后 21 天划痕占比翻倍(0.28*2=0.56), 其余类型按 (1-0.56)/(1-0.28) 等比压缩
DEFECT_WEIGHTS_TAIL = {"划痕": 0.56, "气泡": 0.134, "尺寸偏差": 0.153, "色差": 0.092, "变形": 0.061}

# 15 台设备(每产线 5 台); 注意 EQ-07 必须属于 L2(R-D 规律的前提)
EQUIPMENT = [
    ("EQ-01", "注塑机-1", "L1"), ("EQ-02", "注塑机-2", "L1"), ("EQ-03", "焊接机器人-1", "L1"),
    ("EQ-04", "装配线-1", "L1"), ("EQ-05", "喷涂线-1", "L1"),
    ("EQ-06", "注塑机-3", "L2"), ("EQ-07", "焊接机器人-2", "L2"), ("EQ-08", "装配线-2", "L2"),
    ("EQ-09", "喷涂线-2", "L2"), ("EQ-10", "包装机-1", "L2"),
    ("EQ-11", "注塑机-4", "L3"), ("EQ-12", "焊接机器人-3", "L3"), ("EQ-13", "装配线-3", "L3"),
    ("EQ-14", "喷涂线-3", "L3"), ("EQ-15", "包装机-2", "L3"),
]
STOP_REASONS = ["故障", "换型", "保养", "待料"]
STOP_REASON_WEIGHTS = [0.30, 0.35, 0.20, 0.15]
LONG_STOP_EQUIPMENT = "EQ-07"  # R-D: 长停机注入目标设备
LONG_STOP_COUNT = 5
LONG_STOP_MIN_MINUTES = 150    # 保证 > 120 分钟; 上限取 320 使 EQ-07 总停机时长
LONG_STOP_MAX_MINUTES = 320    # 相比第二名留出 >2 个标准差的余量(断言更稳健)

BATCHES_PER_DAY = 10      # 每天 产线x工序x产品 10 个批次 -> process_output = 90*3*5*6*10 = 81000 行
INSPECTIONS_PER_CELL = 15  # 每天 产线x工序 15 次检验 -> quality_inspections = 90*3*5*15 = 20250 行

# ---------------- T-015 新增两表常量(与 sql/06_orders_inventory_ddl.sql 注释口径一致) ----------------
WAREHOUSES = ["WH-01", "WH-02", "WH-03", "WH-04", "WH-05", "WH-06"]
FRIDAY_WEEKDAY = 4  # date.weekday(): 周一=0 ... 周五=4 ... 周日=6

# 每仓每日出库量区间(件): P-1003 出货稀少(呆滞铺垫), P-1001 出货活跃(跌破安全库存铺垫)
PRODUCT_OUTBOUND_RANGE = {
    "P-1001": (150, 240), "P-1002": (110, 180), "P-1003": (8, 18),
    "P-1004": (60, 110), "P-1005": (90, 150), "P-1006": (70, 120),
}
# 每仓期初库存(件): P-1003 合计约 1.0 万(P-1003 六仓合计, R-E 以此为基数走高约 80%),
# P-1001 合计约 1.4 万(约等于 12 天出库量, R-G 尾段断供 18 天可跌破安全线且不触 0)
PRODUCT_BASE_STOCK = {
    "P-1001": 2330, "P-1002": 2600, "P-1003": 1670,
    "P-1004": 2200, "P-1005": 2400, "P-1006": 2500,
}
# R-F: WH-02 周五出库倍数(期望约 2.4x, 断言阈值 1.6x 留足余量)
FRIDAY_OUTBOUND_FACTOR = (2.2, 2.6)
# R-G: P-1001 最后 17 天断供式补货(入库仅为出库的 40%~60%), 使末段日均净流出约 -585 件/天
P1001_DRAWDOWN_DAYS = 17
P1001_DRAWDOWN_COVER = (0.40, 0.60)
# R-E: P-1003 近 60 天每日净增(每仓, 件): 入库=出库+净增量, 期望净增约 23 件/天/仓 -> 60 天约 +83%
P1003_CLIMB_DAYS = 60
P1003_DAILY_NET_GAIN = (20, 28)

# 生产工单: 每天 30~40 单 -> production_orders 约 3000 行
ORDER_MIN_PER_DAY, ORDER_MAX_PER_DAY = 30, 40
ORDER_MIN_DURATION, ORDER_MAX_DURATION = 3, 7   # 计划工期(天)
# R-H: "已暂停"基础占比 3%; L2(EQ-07 长停机产线) 最近 30 天抬到 15%(断言 > 其他产线 2 倍)
PAUSED_PROB_BASE = 0.03
PAUSED_PROB_L2_RECENT = 0.15
PAUSED_RECENT_DAYS = 29

CSV_HEADERS: dict[str, list[str]] = {
    "process_output": ["production_date", "production_line", "product_id", "product_name",
                       "process_name", "produced_qty", "qualified_qty", "defect_qty"],
    "quality_inspections": ["inspection_time", "product_id", "product_name", "production_line",
                            "process_name", "inspection_qty", "qualified_qty", "defect_qty", "defect_type"],
    "equipment_downtime": ["equipment_id", "equipment_name", "production_line", "start_time",
                           "end_time", "downtime_minutes", "reason", "alarm_count"],
    "production_orders": ["order_no", "product_id", "product_name", "production_line", "planned_qty",
                          "completed_qty", "status", "planned_start", "planned_end",
                          "actual_start", "actual_end"],
    "inventory_records": ["record_date", "warehouse", "product_id", "product_name",
                          "inventory_qty", "inbound_qty", "outbound_qty"],
}


def iter_dates() -> list[date]:
    start = END_DATE - timedelta(days=DAYS - 1)
    return [start + timedelta(days=i) for i in range(DAYS)]


def days_from_end(d: date) -> int:
    """距离数据截止日的天数(0=截止日当天), 用于定义'最后 N 天'窗口。"""
    return (END_DATE - d).days


# ---------------- 三张表的生成 ----------------
def gen_process_output() -> list[dict]:
    """工序产量表: 注入 R-A(L3 末段减产) 与 R-B(焊接低良率)。"""
    rows: list[dict] = []
    for d in iter_dates():
        dfe = days_from_end(d)
        for line in LINES:
            for proc in PROCESSES:
                base_rate = PROCESS_BASE_DEFECT_RATE[proc]
                for pid, pname in PRODUCTS:
                    for _ in range(BATCHES_PER_DAY):
                        qty = random.randint(300, 900)
                        if line == "L3" and dfe <= 29:
                            # R-A: 最后 30 天产量因子 0.93 -> 0.78 线性下降, 段内均值约 0.855(约 -15%)
                            factor = 0.93 - (29 - dfe) * (0.15 / 29)
                            qty = max(1, int(qty * factor))
                        # 不良率在工序基线附近 ±30% 抖动, 保证焊接良率稳定低于全体均值
                        rate = base_rate * random.uniform(0.7, 1.3)
                        defect = int(round(qty * rate)) + random.randint(-5, 5)
                        defect = max(0, min(qty, defect))
                        rows.append({
                            "production_date": d.isoformat(),
                            "production_line": line,
                            "product_id": pid,
                            "product_name": pname,
                            "process_name": proc,
                            "produced_qty": qty,
                            "qualified_qty": qty - defect,
                            "defect_qty": defect,
                        })
    return rows


def gen_quality_inspections() -> list[dict]:
    """质量检验表: 注入 R-C(划痕缺陷末段占比翻倍)。defect_type 空串=无不良。"""
    rows: list[dict] = []
    for d in iter_dates():
        dfe = days_from_end(d)
        weights = [DEFECT_WEIGHTS_TAIL[t] if dfe <= 20 else DEFECT_WEIGHTS_BASE[t] for t in DEFECT_TYPES]
        for line in LINES:
            for proc in PROCESSES:
                base_rate = PROCESS_BASE_DEFECT_RATE[proc]
                for _ in range(INSPECTIONS_PER_CELL):
                    pid, pname = random.choice(PRODUCTS)
                    insp_qty = random.randint(80, 300)
                    rate = base_rate * random.uniform(0.5, 1.5)
                    defect = min(insp_qty, int(round(insp_qty * rate)))
                    dtype = random.choices(DEFECT_TYPES, weights=weights, k=1)[0] if defect > 0 else ""
                    rows.append({
                        "inspection_time": "%s %02d:%02d:%02d" % (
                            d.isoformat(), random.randint(8, 20), random.randint(0, 59), random.randint(0, 59)),
                        "product_id": pid,
                        "product_name": pname,
                        "production_line": line,
                        "process_name": proc,
                        "inspection_qty": insp_qty,
                        "qualified_qty": insp_qty - defect,
                        "defect_qty": defect,
                        "defect_type": dtype,
                    })
    return rows


def _downtime_row(eq_id: str, eq_name: str, line: str, d: date, minutes: int, reason: str) -> dict:
    start = datetime(d.year, d.month, d.day, random.randint(6, 21), random.randint(0, 59), random.randint(0, 59))
    end = start + timedelta(minutes=minutes)  # 允许自然跨天, 与真实停机语义一致
    alarm = random.randint(2, 8) if reason == "故障" else random.randint(0, 2)
    return {
        "equipment_id": eq_id, "equipment_name": eq_name, "production_line": line,
        "start_time": start.strftime("%Y-%m-%d %H:%M:%S"),
        "end_time": end.strftime("%Y-%m-%d %H:%M:%S"),
        "downtime_minutes": minutes, "reason": reason, "alarm_count": alarm,
    }


def gen_equipment_downtime() -> list[dict]:
    """设备停机表: 常规停机(10~90 分钟) + R-D(EQ-07 五次 >120 分钟长停机)。"""
    rows: list[dict] = []
    for eq_id, eq_name, line in EQUIPMENT:
        for d in iter_dates():
            # 每设备每天期望约 1.11 次停机 -> 15 台 x 90 天 x 1.11 + 5 ≈ 1500 行(目标值)
            r = random.random()
            n_events = 0 if r < 0.04 else (1 if r < 0.85 else 2)
            for _ in range(n_events):
                dur = int(random.uniform(10, 90))
                reason = random.choices(STOP_REASONS, weights=STOP_REASON_WEIGHTS, k=1)[0]
                rows.append(_downtime_row(eq_id, eq_name, line, d, dur, reason))
    # R-D: EQ-07(L2) 追加 5 次 >120 分钟长停机, 分散在最后 45 天, 使其总停机时长全厂第一
    for _ in range(LONG_STOP_COUNT):
        d = END_DATE - timedelta(days=random.randint(0, 44))
        rows.append(_downtime_row(LONG_STOP_EQUIPMENT, "焊接机器人-2", "L2", d,
                                  random.randint(LONG_STOP_MIN_MINUTES, LONG_STOP_MAX_MINUTES), "故障"))
    rows.sort(key=lambda x: x["start_time"])
    return rows


# ---------------- T-015 新增两表的生成 ----------------
def gen_production_orders() -> list[dict]:
    """生产工单表: 每天 30~40 单; 注入 R-H(L2 最近 30 天已暂停占比显著抬高)。

    语义约定: 工单下达日(planned_start)即实际开工日(actual_start); 计划完成日在数据
    截止日之前的工单按 已完成/已暂停 落定, 计划完成日跨过截止日的工单为 进行中/已暂停
    (actual_end 为 NULL, 由 write_csv 写作字面量 NULL 供 LOAD DATA 读作 NULL)。
    """
    rows: list[dict] = []
    for d in iter_dates():
        dfe = days_from_end(d)
        for i in range(random.randint(ORDER_MIN_PER_DAY, ORDER_MAX_PER_DAY)):
            pid, pname = random.choice(PRODUCTS)
            line = random.choice(LINES)
            planned_qty = random.randint(500, 2000)
            duration = random.randint(ORDER_MIN_DURATION, ORDER_MAX_DURATION)
            planned_end = d + timedelta(days=duration - 1)
            # R-H: L2 在最近 30 天(对应 EQ-07 频繁长停机)暂停概率显著抬高
            p_paused = PAUSED_PROB_L2_RECENT if (line == "L2" and dfe <= PAUSED_RECENT_DAYS) else PAUSED_PROB_BASE
            paused = random.random() < p_paused
            if planned_end > END_DATE:
                # 未到计划完成日: 只能是 进行中/已暂停, 完成数按已推进工期折算
                status = "已暂停" if paused else "进行中"
                progress = min(1.0, (END_DATE - d).days + 1) / duration
                completed = int(planned_qty * progress * random.uniform(0.6, 1.0))
                actual_end = None
            elif paused:
                status = "已暂停"
                completed = int(planned_qty * random.uniform(0.05, 0.6))
                actual_end = None
            else:
                status = "已完成"
                completed = int(planned_qty * random.uniform(0.96, 1.00))
                actual_end = min(planned_end + timedelta(days=random.randint(-1, 1)), END_DATE)
            rows.append({
                "order_no": "WO-%s-%03d" % (d.strftime("%Y%m%d"), i + 1),
                "product_id": pid,
                "product_name": pname,
                "production_line": line,
                "planned_qty": planned_qty,
                "completed_qty": completed,
                "status": status,
                "planned_start": d.isoformat(),
                "planned_end": planned_end.isoformat(),
                "actual_start": d.isoformat(),
                "actual_end": actual_end.isoformat() if actual_end else None,
            })
    return rows


def gen_inventory_records() -> list[dict]:
    """库存日快照表: 仓库 x 产品 逐日快照(期末库存 = 昨日库存 + 入库 - 出库)。

    注入三条规律: R-E(P-1003 近 60 天持续走高, 呆滞)、R-F(WH-02 周五出库高峰)、
    R-G(P-1001 近 14 天跌破安全库存线=日均出库 x 7); 其余产品在补货策略
    (库存低于期初 70% 加大补货、高于 135% 收紧补货)下围绕期初水平波动。
    """
    rows: list[dict] = []
    state: dict[tuple[str, str], int] = {
        (w, p): PRODUCT_BASE_STOCK[p] for w in WAREHOUSES for p in PRODUCT_OUTBOUND_RANGE
    }
    for d in iter_dates():
        dfe = days_from_end(d)
        is_friday = d.weekday() == FRIDAY_WEEKDAY
        for w in WAREHOUSES:
            for p in PRODUCT_OUTBOUND_RANGE:
                lo, hi = PRODUCT_OUTBOUND_RANGE[p]
                out = random.randint(lo, hi)
                if w == "WH-02" and is_friday:
                    # R-F: WH-02 每周五出货高峰
                    out = max(out + 1, int(out * random.uniform(*FRIDAY_OUTBOUND_FACTOR)))
                cur = state[(w, p)]
                base = PRODUCT_BASE_STOCK[p]
                if p == "P-1001" and dfe <= P1001_DRAWDOWN_DAYS:
                    # R-G: P-1001 尾段断供式补货, 库存加速下滑并跌破安全库存线
                    inbound = int(out * random.uniform(*P1001_DRAWDOWN_COVER))
                elif p == "P-1003" and dfe <= P1003_CLIMB_DAYS:
                    # R-E: P-1003 近 60 天入库持续大于出货, 库存单边走高(呆滞)
                    inbound = out + random.randint(*P1003_DAILY_NET_GAIN)
                elif p == "P-1003":
                    # 高走期之前围绕期初水平小幅波动
                    inbound = max(0, out + random.randint(-4, 4))
                else:
                    # 常规补货策略: 出库量附近浮动, 库存偏离期初过大时反向纠偏
                    cover = random.uniform(0.92, 1.08)
                    if cur < base * 0.7:
                        cover = random.uniform(1.2, 1.4)
                    elif cur > base * 1.35:
                        cover = random.uniform(0.7, 0.9)
                    inbound = int(out * cover)
                new_qty = cur + inbound - out
                state[(w, p)] = new_qty
                rows.append({
                    "record_date": d.isoformat(),
                    "warehouse": w,
                    "product_id": p,
                    "product_name": dict(PRODUCTS)[p],
                    "inventory_qty": new_qty,
                    "inbound_qty": inbound,
                    "outbound_qty": out,
                })
    return rows


# ---------------- 输出与校验 ----------------
def write_csv(name: str, rows: list[dict]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.csv"
    # utf-8-sig 便于 Excel 直接查看; LOAD DATA ... IGNORE 1 LINES 时 BOM 随表头一并跳过
    # None 写出为字面量 NULL, 供 LOAD DATA 经 NULLIF(...,'NULL') 读作 SQL NULL(T-015 工单 actual_end)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS[name])
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("NULL" if v is None else v) for k, v in row.items()})
    return path


def _paused_ratio(orders: list[dict], line: str, recent_only: bool) -> tuple[int, int]:
    """返回 (已暂停数, 工单总数); recent_only=True 时只统计最近 30 天(planned_start)。"""
    rows = [r for r in orders if r["production_line"] == line]
    if recent_only:
        rows = [r for r in rows if days_from_end(date.fromisoformat(r["planned_start"])) <= 29]
    paused = sum(1 for r in rows if r["status"] == "已暂停")
    return paused, len(rows)


def verify_and_report(po: list[dict], qi: list[dict], ed: list[dict],
                      orders: list[dict], inv: list[dict]) -> None:
    """打印统计摘要并断言 8 条业务规律与五表行数达标(断言失败 -> 非零退出码)。"""
    print("=" * 72)
    print("统计摘要 (seed=%d, %d 天: %s ~ %s)" % (SEED, DAYS, iter_dates()[0], END_DATE))
    print("  process_output       %7d 行 (目标约 80000)" % len(po))
    print("  quality_inspections  %7d 行 (目标约 20000)" % len(qi))
    print("  equipment_downtime   %7d 行 (目标约 1500)" % len(ed))
    print("  production_orders    %7d 行 (目标约 3000)" % len(orders))
    print("  inventory_records    %7d 行 (目标 3240 = 90x6x6)" % len(inv))
    print("-" * 72)

    # 1) 行数达标(区间断言, 允许随机抖动)
    assert 70000 <= len(po) <= 90000, "process_output 行数不达标: %d" % len(po)
    assert 18000 <= len(qi) <= 22000, "quality_inspections 行数不达标: %d" % len(qi)
    assert 1200 <= len(ed) <= 1800, "equipment_downtime 行数不达标: %d" % len(ed)
    assert 2500 <= len(orders) <= 4000, "production_orders 行数不达标: %d" % len(orders)
    assert 3200 <= len(inv) <= 3300, "inventory_records 行数不达标: %d" % len(inv)

    # 2) R-A: L3 最后 30 天日均产量 < 前 60 天(环比约 -15%)
    l3_daily: dict[str, int] = {}
    for r in po:
        if r["production_line"] == "L3":
            l3_daily[r["production_date"]] = l3_daily.get(r["production_date"], 0) + r["produced_qty"]
    tail = [v for k, v in l3_daily.items() if days_from_end(date.fromisoformat(k)) <= 29]
    head = [v for k, v in l3_daily.items() if days_from_end(date.fromisoformat(k)) > 29]
    tail_mean, head_mean = statistics.mean(tail), statistics.mean(head)
    print("  R-A L3 产量: 末30天日均 %.0f 件 vs 前60天日均 %.0f 件 (环比 %+.1f%%)"
          % (tail_mean, head_mean, (tail_mean / head_mean - 1) * 100))
    assert tail_mean < head_mean, "R-A 失败: L3 末段产量均值未低于前段"

    # 3) R-B: 焊接良率 < 全体良率均值
    weld_p = sum(r["produced_qty"] for r in po if r["process_name"] == "焊接")
    weld_q = sum(r["qualified_qty"] for r in po if r["process_name"] == "焊接")
    all_p = sum(r["produced_qty"] for r in po)
    all_q = sum(r["qualified_qty"] for r in po)
    weld_yield, overall_yield = weld_q / weld_p * 100, all_q / all_p * 100
    print("  R-B 良率: 焊接 %.2f%% vs 全体均值 %.2f%%" % (weld_yield, overall_yield))
    assert weld_yield < overall_yield, "R-B 失败: 焊接良率未低于全体均值"

    # 4) R-C: 划痕缺陷最后 21 天占比 > 之前占比 x 1.5(目标约翻倍)
    defect_rows = [r for r in qi if r["defect_type"]]
    tail_def = [r for r in defect_rows if days_from_end(date.fromisoformat(r["inspection_time"][:10])) <= 20]
    head_def = [r for r in defect_rows if days_from_end(date.fromisoformat(r["inspection_time"][:10])) > 20]
    s_tail = sum(1 for r in tail_def if r["defect_type"] == SCRATCH) / len(tail_def)
    s_head = sum(1 for r in head_def if r["defect_type"] == SCRATCH) / len(head_def)
    print("  R-C 划痕占比: 末21天 %.1f%% vs 之前 %.1f%% (倍数 %.2f)"
          % (s_tail * 100, s_head * 100, s_tail / s_head))
    assert s_tail > s_head * 1.5, "R-C 失败: 划痕末段占比未显著翻倍"

    # 5) R-D: EQ-07 总停机时长全厂 top1
    total_by_eq: dict[str, int] = {}
    for r in ed:
        total_by_eq[r["equipment_id"]] = total_by_eq.get(r["equipment_id"], 0) + r["downtime_minutes"]
    top3 = sorted(total_by_eq.items(), key=lambda kv: kv[1], reverse=True)[:3]
    print("  R-D 停机时长 top3: " + ", ".join("%s=%d分钟" % kv for kv in top3))
    top_eq = max(total_by_eq, key=lambda k: total_by_eq[k])
    assert top_eq == LONG_STOP_EQUIPMENT, "R-D 失败: EQ-07 不是停机时长 top1"

    # 6) R-E: P-1003 六仓合计库存近 60 天持续走高(呆滞, 期末较 60 天前约 +80%)
    p1003_daily: dict[str, int] = {}
    for r in inv:
        if r["product_id"] == "P-1003":
            p1003_daily[r["record_date"]] = p1003_daily.get(r["record_date"], 0) + int(r["inventory_qty"])
    latest_day = END_DATE.isoformat()
    anchor_day = (END_DATE - timedelta(days=P1003_CLIMB_DAYS)).isoformat()
    stock_latest, stock_anchor = p1003_daily[latest_day], p1003_daily[anchor_day]
    climb_pct = (stock_latest / stock_anchor - 1) * 100
    print("  R-E P-1003 库存: 截止日 %d 件 vs %d 天前 %d 件 (变化 %+.1f%%)"
          % (stock_latest, P1003_CLIMB_DAYS, stock_anchor, climb_pct))
    assert stock_latest > stock_anchor * 1.30, \
        "R-E 失败: P-1003 末段库存未显著走高 (%d vs %d)" % (stock_latest, stock_anchor)

    # 7) R-F: WH-02 每周五出库高峰(约为其他日期的 2.2~2.6 倍)
    wh02_fri = [int(r["outbound_qty"]) for r in inv
                if r["warehouse"] == "WH-02" and date.fromisoformat(r["record_date"]).weekday() == FRIDAY_WEEKDAY]
    wh02_non = [int(r["outbound_qty"]) for r in inv
                if r["warehouse"] == "WH-02" and date.fromisoformat(r["record_date"]).weekday() != FRIDAY_WEEKDAY]
    fri_mean, non_mean = statistics.mean(wh02_fri), statistics.mean(wh02_non)
    fri_ratio = fri_mean / non_mean if non_mean else 0.0
    print("  R-F WH-02 出库: 周五日均 %.1f 件 vs 其他日日均 %.1f 件 (倍数 %.2f)"
          % (fri_mean, non_mean, fri_ratio))
    assert fri_ratio > 1.6, "R-F 失败: WH-02 周五出库未显著高于其他日期 (%.2f)" % fri_ratio

    # 8) R-G: P-1001 近 14 天跌破安全库存线(安全库存 = 日均出库 x 7)
    p1001_rows = [r for r in inv if r["product_id"] == "P-1001"]
    avg_out_1001 = statistics.mean(int(r["outbound_qty"]) for r in p1001_rows)
    safety_line = avg_out_1001 * 7
    recent_1001 = [r for r in p1001_rows if days_from_end(date.fromisoformat(r["record_date"])) <= 13]
    below_cnt = sum(1 for r in recent_1001 if int(r["inventory_qty"]) < safety_line)
    min_recent = min(int(r["inventory_qty"]) for r in recent_1001)
    print("  R-G P-1001 安全库存线 %.0f 件(日均出库 %.1f x7); 近14天跌破记录 %d 条, 最低 %d 件"
          % (safety_line, avg_out_1001, below_cnt, min_recent))
    assert below_cnt > 0, "R-G 失败: P-1001 近 14 天无跌破安全库存线的记录"

    # 9) R-H: L2(长停机产线) 最近 30 天"已暂停"工单占比显著高于其他产线
    l2_p, l2_n = _paused_ratio(orders, "L2", True)
    oth_p, oth_n = 0, 0
    for ln in LINES:
        if ln == "L2":
            continue
        p_, n_ = _paused_ratio(orders, ln, True)
        oth_p, oth_n = oth_p + p_, oth_n + n_
    l2_ratio = l2_p / l2_n if l2_n else 0.0
    oth_ratio = oth_p / oth_n if oth_n else 0.0
    print("  R-H L2 近30天已暂停占比 %.1f%% (%d/%d) vs 其他产线 %.1f%% (%d/%d)"
          % (l2_ratio * 100, l2_p, l2_n, oth_ratio * 100, oth_p, oth_n))
    assert l2_n > 0 and l2_ratio >= 0.08, \
        "R-H 失败: L2 近30天已暂停占比过低 (%.1f%%)" % (l2_ratio * 100)
    assert l2_ratio > oth_ratio * 2, \
        "R-H 失败: L2 工单暂停占比未显著高于其他产线 (%.1f%% vs %.1f%%)" % (l2_ratio * 100, oth_ratio * 100)

    print("-" * 72)
    print("[OK] 全部生成正确性断言通过 (五表行数 + R-A~R-H)")


def main() -> int:
    random.seed(SEED)  # 关键: 固定随机种子保证可复现(见文件头约束 2)
    # 原三表必须先生成: 新表随机消耗排在其后, 保证 P1 三张 CSV 逐字节可复现(文件头约束 2)
    tables = (("process_output", gen_process_output()),
              ("quality_inspections", gen_quality_inspections()),
              ("equipment_downtime", gen_equipment_downtime()))
    extra = (("production_orders", gen_production_orders()),
             ("inventory_records", gen_inventory_records()))
    all_tables = tables + extra
    for name, rows in all_tables:
        print("已写出 %s (%d 行)" % (write_csv(name, rows), len(rows)))
    verify_and_report(*[rows for _, rows in all_tables])
    return 0


if __name__ == "__main__":
    sys.exit(main())
