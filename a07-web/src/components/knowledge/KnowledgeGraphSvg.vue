<!-- AI-assisted -->
<!-- 图谱 SVG 轻量渲染：力导向迭代 + 按节点类型着色/按边关系虚线；
     T-029b（K2）：applies_to=[] 的全局规则节点无边属数据正确，UI 标「全局」+图例；
     边按关系类型曲率/透明度 + 可筛选，减轻交错。数据全部来自 GET /api/knowledge/graph（R4）。
     视觉升级：集成网格雷达底板、节点发光光晕、高对比度标签与实体详情卡片。 -->
<script setup lang="ts">
import { computed, ref } from 'vue'
import type { GraphEdge, GraphEdgeRelation, GraphNode, GraphNodeType } from '../../types/knowledge'
import { GRAPH_EDGE_RELATION_LABELS, GRAPH_NODE_TYPE_LABELS } from '../../types/knowledge'
import { DocumentCopy, InfoFilled, Connection, Warning } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const props = defineProps<{
  nodes: GraphNode[]
  edges: GraphEdge[]
}>()

/** BUG-019：加大画布与力导参数，节点/标签不再挤成一团（验收节点 32 / 边 39 可辨认）。 */
const VIEW_W = 1280
const VIEW_H = 860
const NODE_R = 20
/** 节点中心最小间距：直径 + 标签一行高度，碰撞半径用 */
const MIN_SEP = 78
const ITERATIONS = 220
/** 斥力系数：32 节点量级下需远大于原先 1800，否则聚成一团 */
const REPEL_K = 26000
/** 边理想长度（引力目标距离） */
const SPRING_LEN = 120

const TYPE_COLORS: Record<GraphNodeType, string> = {
  object: '#38bdf8',
  metric: '#34d399',
  rule: '#fbbf24',
  topic: '#c084fc',
}

const EDGE_COLORS: Record<string, string> = {
  topic_object: '#38bdf8',
  topic_metric: '#34d399',
  rule_metric: '#fbbf24',
}

/** 边曲率（垂直偏移 / 边长比例）：按关系类型分侧，降低同向交错重叠 */
const EDGE_CURVE: Record<string, number> = {
  topic_object: 0.14,
  topic_metric: -0.12,
  rule_metric: 0.07,
}

/** 边透明度：略降，交错区更易读 */
const EDGE_OPACITY = '0.6'

const RELATION_OPTIONS = Object.keys(GRAPH_EDGE_RELATION_LABELS) as GraphEdgeRelation[]

interface LayoutNode {
  node: GraphNode
  x: number
  y: number
  labelAbove?: boolean
}

const hoveredId = ref<string | null>(null)
const selected = ref<GraphNode | null>(null)
/** 边关系类型筛选：默认全开；取消勾选后仅隐藏边，布局保持稳定 */
const visibleRelations = ref<GraphEdgeRelation[]>([...RELATION_OPTIONS])

/** 与任意边相连的节点 id（全量边，不受筛选影响） */
const connectedIds = computed(() => {
  const set = new Set<string>()
  for (const e of props.edges) {
    set.add(e.source)
    set.add(e.target)
  }
  return set
})

/**
 * 全局规则节点：type=rule 且无任何关联边。
 * 数据层 K2：rule_time_range_default 等 applies_to=[] 时 graph 只对 applies_to 指标连边，
 * 无边=数据正确，非前端/后端丢边。
 */
const globalRuleIds = computed(() => {
  const set = new Set<string>()
  for (const n of props.nodes) {
    if (n.type === 'rule' && !connectedIds.value.has(n.id)) {
      set.add(n.id)
    }
  }
  return set
})

const globalRuleNodes = computed(() =>
  props.nodes.filter((n) => globalRuleIds.value.has(n.id)),
)

function isGlobalRule(id: string): boolean {
  return globalRuleIds.value.has(id)
}

/** 当前可见边（按关系类型筛选） */
const filteredEdges = computed(() => {
  const allowed = new Set(visibleRelations.value)
  return props.edges.filter((e) => allowed.has(e.relation))
})

/** 轻量力导向：强斥力 + 边引力 + 向心 + 碰撞半径，迭代固定次数（无动画库依赖）。 */
function runLayout(nodes: GraphNode[], edges: GraphEdge[]): LayoutNode[] {
  const n = nodes.length
  if (n === 0) return []
  // 初始布局：按类型分扇区 + 螺旋半径，避免全部落在同一圆环上
  const pos: LayoutNode[] = nodes.map((node, i) => {
    const angle = (2 * Math.PI * i) / n + (i % 3) * 0.15
    const radius = Math.min(VIEW_W, VIEW_H) * (0.22 + 0.18 * ((i % 5) / 4))
    return {
      node,
      x: VIEW_W / 2 + Math.cos(angle) * radius,
      y: VIEW_H / 2 + Math.sin(angle) * radius,
    }
  })
  const index = new Map<string, number>()
  pos.forEach((p, i) => index.set(p.node.id, i))
  const fx = new Float64Array(n)
  const fy = new Float64Array(n)
  const margin = NODE_R + 28

  for (let iter = 0; iter < ITERATIONS; iter += 1) {
    fx.fill(0)
    fy.fill(0)
    const cooling = 1 - iter / (ITERATIONS * 1.4)
    for (let i = 0; i < n; i += 1) {
      for (let j = i + 1; j < n; j += 1) {
        let dx = pos[i].x - pos[j].x
        let dy = pos[i].y - pos[j].y
        let dist = Math.hypot(dx, dy)
        if (dist < 1) {
          dx = (i % 2 === 0 ? 1 : -1) * 0.5
          dy = (j % 2 === 0 ? 1 : -1) * 0.5
          dist = 1
        }
        let repel = REPEL_K / (dist * dist)
        if (dist < MIN_SEP) {
          repel += (MIN_SEP - dist) * 2.2
        }
        const ux = dx / dist
        const uy = dy / dist
        fx[i] += ux * repel
        fy[i] += uy * repel
        fx[j] -= ux * repel
        fy[j] -= uy * repel
      }
    }
    for (const edge of edges) {
      const si = index.get(edge.source)
      const ti = index.get(edge.target)
      if (si == null || ti == null) continue
      const dx = pos[ti].x - pos[si].x
      const dy = pos[ti].y - pos[si].y
      const dist = Math.max(Math.hypot(dx, dy), 1)
      const attract = (dist - SPRING_LEN) * 0.045
      const ux = dx / dist
      const uy = dy / dist
      fx[si] += ux * attract
      fy[si] += uy * attract
      fx[ti] -= ux * attract
      fy[ti] -= uy * attract
    }
    const step = 0.28 * cooling
    for (let i = 0; i < n; i += 1) {
      fx[i] += (VIEW_W / 2 - pos[i].x) * 0.008
      fy[i] += (VIEW_H / 2 - pos[i].y) * 0.008
      const mx = clamp(fx[i] * step, -40, 40)
      const my = clamp(fy[i] * step, -40, 40)
      pos[i].x = clamp(pos[i].x + mx, margin, VIEW_W - margin)
      pos[i].y = clamp(pos[i].y + my, margin + 12, VIEW_H - margin)
    }
    if (iter % 4 === 0 || iter === ITERATIONS - 1) {
      for (let pass = 0; pass < 3; pass += 1) {
        for (let i = 0; i < n; i += 1) {
          for (let j = i + 1; j < n; j += 1) {
            let dx = pos[j].x - pos[i].x
            let dy = pos[j].y - pos[i].y
            let dist = Math.hypot(dx, dy)
            if (dist < 1) {
              dx = 1
              dy = 0
              dist = 1
            }
            if (dist < MIN_SEP) {
              const push = (MIN_SEP - dist) * 0.45
              const ux = dx / dist
              const uy = dy / dist
              pos[i].x = clamp(pos[i].x - ux * push, margin, VIEW_W - margin)
              pos[i].y = clamp(pos[i].y - uy * push, margin + 12, VIEW_H - margin)
              pos[j].x = clamp(pos[j].x + ux * push, margin, VIEW_W - margin)
              pos[j].y = clamp(pos[j].y + uy * push, margin + 12, VIEW_H - margin)
            }
          }
        }
      }
    }
  }
  return placeLabels(pos)
}

function placeLabels(pos: LayoutNode[]): LayoutNode[] {
  const sorted = [...pos].sort((a, b) => a.y - b.y || a.x - b.x)
  const placed: { x: number; y: number }[] = []
  const flipMap = new Map<string, boolean>()
  const LABEL_W = 58
  const LABEL_H = 14
  for (const item of sorted) {
    const yBelow = item.y + NODE_R + 14
    const yAbove = item.y - NODE_R - 10
    let useAbove = false
    const overlaps = (y: number): boolean =>
      placed.some((p) => Math.abs(item.x - p.x) < LABEL_W && Math.abs(y - p.y) < LABEL_H)
    if (overlaps(yBelow) && !overlaps(yAbove)) {
      useAbove = true
    }
    placed.push({ x: item.x, y: useAbove ? yAbove : yBelow })
    flipMap.set(item.node.id, useAbove)
  }
  return pos.map((p) => ({ ...p, labelAbove: flipMap.get(p.node.id) ?? false }))
}

function clamp(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v))
}

const layoutNodes = computed(() => runLayout(props.nodes, props.edges))
const posMap = computed(() => {
  const map = new Map<string, LayoutNode>()
  for (const item of layoutNodes.value) map.set(item.node.id, item)
  return map
})

function edgePath(s: LayoutNode, t: LayoutNode, relation: string): string {
  const dx = t.x - s.x
  const dy = t.y - s.y
  const dist = Math.hypot(dx, dy) || 1
  const nx = -dy / dist
  const ny = dx / dist
  const curve = EDGE_CURVE[relation] ?? 0.08
  const midX = (s.x + t.x) / 2 + nx * dist * curve
  const midY = (s.y + t.y) / 2 + ny * dist * curve
  return `M ${s.x} ${s.y} Q ${midX} ${midY} ${t.x} ${t.y}`
}

const drawEdges = computed(() => {
  return filteredEdges.value
    .map((edge) => {
      const s = posMap.value.get(edge.source)
      const t = posMap.value.get(edge.target)
      if (!s || !t) return null
      return {
        key: `${edge.source}->${edge.target}:${edge.relation}`,
        d: edgePath(s, t, edge.relation),
        color: EDGE_COLORS[edge.relation] ?? '#64748b',
        dashed: edge.relation === 'rule_metric',
      }
    })
    .filter((e): e is NonNullable<typeof e> => e !== null)
})

const legendItems = computed(() =>
  (Object.keys(TYPE_COLORS) as GraphNodeType[]).map((type) => ({
    type,
    label: GRAPH_NODE_TYPE_LABELS[type],
    color: TYPE_COLORS[type],
  })),
)

function shortName(name: string): string {
  return name.length > 8 ? `${name.slice(0, 7)}…` : name
}

function pick(node: GraphNode): void {
  selected.value = node
}

function edgeLabel(relation: string): string {
  return GRAPH_EDGE_RELATION_LABELS[relation as keyof typeof GRAPH_EDGE_RELATION_LABELS] ?? relation
}

function toggleRelation(relation: GraphEdgeRelation, on: boolean): void {
  const next = new Set(visibleRelations.value)
  if (on) next.add(relation)
  else next.delete(relation)
  visibleRelations.value = RELATION_OPTIONS.filter((r) => next.has(r))
}

async function copyNodeId(): Promise<void> {
  if (!selected.value) return
  try {
    await navigator.clipboard.writeText(selected.value.id)
    ElMessage.success('实体编码已复制')
  } catch {
    ElMessage.warning('复制失败')
  }
}
</script>

<template>
  <div class="graph-component">
    <!-- 图谱控制与图例工具栏 -->
    <div class="graph-top-bar">
      <div class="legend-cluster">
        <span v-for="item in legendItems" :key="item.type" class="legend-badge">
          <i class="dot" :style="{ backgroundColor: item.color }" />
          <span class="legend-text">{{ item.label }}</span>
        </span>
        <span class="legend-badge global-legend">
          <i class="dot ring-dot" />
          <span class="legend-text">全局规则（applies_to为空，无边正常）</span>
        </span>
      </div>

      <div class="filter-controls">
        <span class="filter-caption">边关系筛选:</span>
        <el-checkbox
          v-for="rel in RELATION_OPTIONS"
          :key="rel"
          :model-value="visibleRelations.includes(rel)"
          size="small"
          class="custom-chk"
          @change="(v: string | number | boolean) => toggleRelation(rel, Boolean(v))"
        >
          {{ edgeLabel(rel) }}
        </el-checkbox>
      </div>
    </div>

    <!-- 图谱主体画布 + 侧边详情 -->
    <div class="graph-layout">
      <!-- SVG 力导向拓扑画布 -->
      <div class="svg-container">
        <svg
          :viewBox="`0 0 ${VIEW_W} ${VIEW_H}`"
          class="topology-svg"
          role="img"
          aria-label="业务知识图谱拓扑"
        >
          <defs>
            <!-- 科技点阵背景 -->
            <pattern id="graph-dots" width="40" height="40" patternUnits="userSpaceOnUse">
              <circle cx="20" cy="20" r="1.2" fill="rgba(148, 163, 184, 0.15)" />
            </pattern>
            <!-- 发光滤镜 -->
            <filter id="glow-filter" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
          </defs>

          <!-- 背景点阵 -->
          <rect width="100%" height="100%" fill="url(#graph-dots)" />

          <!-- 拓扑连线 -->
          <path
            v-for="edge in drawEdges"
            :key="edge.key"
            :d="edge.d"
            fill="none"
            :stroke="edge.color"
            stroke-width="1.8"
            :stroke-dasharray="edge.dashed ? '6 4' : undefined"
            :opacity="EDGE_OPACITY"
            class="topology-edge"
          />

          <!-- 节点群组 -->
          <g
            v-for="item in layoutNodes"
            :key="item.node.id"
            class="topology-node"
            :class="{
              'is-hovered': hoveredId === item.node.id,
              'is-selected': selected?.id === item.node.id,
              'is-global': isGlobalRule(item.node.id),
            }"
            @mouseenter="hoveredId = item.node.id"
            @mouseleave="hoveredId = null"
            @click="pick(item.node)"
          >
            <!-- 全局规则虚线外圈 -->
            <circle
              v-if="isGlobalRule(item.node.id)"
              :cx="item.x"
              :cy="item.y"
              :r="NODE_R + 6"
              fill="none"
              :stroke="TYPE_COLORS.rule"
              stroke-width="1.5"
              stroke-dasharray="3 3"
              opacity="0.85"
            />

            <!-- 节点实体圆圈 -->
            <circle
              :cx="item.x"
              :cy="item.y"
              :r="NODE_R"
              :fill="TYPE_COLORS[item.node.type] ?? '#94a3b8'"
              :opacity="hoveredId === item.node.id || selected?.id === item.node.id ? 1 : 0.88"
              class="node-circle"
            />

            <!-- 节点标签文本（双层文字阴影确保清晰度） -->
            <text
              :x="item.x"
              :y="item.labelAbove ? item.y - NODE_R - 10 : item.y + NODE_R + 15"
              text-anchor="middle"
              class="node-label-bg"
            >
              {{ shortName(item.node.name) }}
            </text>
            <text
              :x="item.x"
              :y="item.labelAbove ? item.y - NODE_R - 10 : item.y + NODE_R + 15"
              text-anchor="middle"
              class="node-label"
            >
              {{ shortName(item.node.name) }}
            </text>

            <!-- 全局小字 -->
            <text
              v-if="isGlobalRule(item.node.id)"
              :x="item.x"
              :y="item.y + 4"
              text-anchor="middle"
              class="global-text"
            >
              全局
            </text>
          </g>
        </svg>
      </div>

      <!-- 侧边栏：全局规则列表 + 选中实体属性卡 -->
      <aside class="graph-inspector">
        <!-- 全局规则清单 -->
        <div v-if="globalRuleNodes.length > 0" class="global-panel">
          <div class="panel-head">
            <span class="panel-title">全局规则 ({{ globalRuleNodes.length }})</span>
            <el-tooltip
              content="applies_to=[] 全局生效规则，无边属正常现象（K2 定则）"
              placement="top"
            >
              <el-icon class="hint-icon"><InfoFilled /></el-icon>
            </el-tooltip>
          </div>
          <div class="global-rules-scroll">
            <div
              v-for="n in globalRuleNodes"
              :key="n.id"
              class="global-rule-row"
              :class="{ 'is-active': selected?.id === n.id }"
              @click="pick(n)"
            >
              <i class="dot rule-dot" />
              <span class="rule-name">{{ n.name }}</span>
              <span v-if="n.extra" class="rule-type">{{ n.extra }}</span>
            </div>
          </div>
        </div>

        <!-- 选中节点详细卡片 -->
        <div v-if="selected" class="selected-detail-panel">
          <div class="detail-header">
            <span class="detail-name">{{ selected.name }}</span>
            <el-tag
              size="small"
              :color="TYPE_COLORS[selected.type]"
              effect="dark"
              class="type-pill"
            >
              {{ GRAPH_NODE_TYPE_LABELS[selected.type] ?? selected.type }}
            </el-tag>
          </div>

          <div class="detail-attrs">
            <div class="attr-row">
              <span class="attr-key">实体编码:</span>
              <span class="attr-val code-val">
                {{ selected.id }}
                <el-icon class="copy-icon" @click="copyNodeId"><DocumentCopy /></el-icon>
              </span>
            </div>

            <div class="attr-row">
              <span class="attr-key">业务领域:</span>
              <span class="attr-val">{{ selected.domain || '—' }}</span>
            </div>

            <div v-if="selected.description" class="attr-row block-row">
              <span class="attr-key">说明描述:</span>
              <span class="attr-val desc-val">{{ selected.description }}</span>
            </div>

            <div v-if="selected.extra" class="attr-row block-row">
              <span class="attr-key">附加/公式:</span>
              <span class="attr-val formula-val">{{ selected.extra }}</span>
            </div>
          </div>

          <div v-if="isGlobalRule(selected.id)" class="global-explain-callout">
            <el-icon><Warning /></el-icon>
            <span>全局规则：默认适用于系统全量问析上下文，无需通过关联边约束单项指标。</span>
          </div>
          <div v-else class="topology-explain-callout">
            <el-icon><Connection /></el-icon>
            <span>关联网络已通过知识检索注入 Agent 提示词上下文，驱动精准 SQL 生成。</span>
          </div>
        </div>

        <div v-else class="empty-inspector">
          <el-icon class="empty-icon"><Connection /></el-icon>
          <span class="empty-text">点击图上任意节点查看详细属性与公式</span>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.graph-component {
  display: flex;
  flex-direction: column;
  background: var(--app-bg-card);
}

.graph-top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 18px;
  background: rgba(255, 255, 255, 0.02);
  border-bottom: 1px solid var(--app-border);
  gap: 16px;
  flex-wrap: wrap;
}

.legend-cluster {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.legend-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--app-border-subtle);
  border-radius: 6px;
}

.legend-text {
  font-size: 11.5px;
  color: var(--app-text-secondary);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.ring-dot {
  border: 1.5px dashed #fbbf24;
  background: transparent;
}

.rule-dot {
  background: #fbbf24;
}

.filter-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.filter-caption {
  font-size: 11.5px;
  color: var(--app-text-muted);
}

.graph-layout {
  display: grid;
  grid-template-columns: 1fr 300px;
  min-height: 660px;
}

.svg-container {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 660px;
  background: #080d19;
  overflow: hidden;
}

html:not(.dark) .svg-container {
  background: #f1f5f9;
}

.topology-svg {
  width: 100%;
  height: 100%;
  display: block;
}

.topology-node {
  cursor: pointer;
  transition: transform 0.2s ease;
}

.topology-node.is-hovered {
  filter: url(#glow-filter);
}

.node-circle {
  transition: all 0.2s ease;
}

.topology-node.is-hovered .node-circle {
  stroke: #ffffff;
  stroke-width: 2px;
}

.topology-node.is-selected .node-circle {
  stroke: #38bdf8;
  stroke-width: 3px;
}

.node-label-bg {
  font-size: 11px;
  font-weight: 700;
  stroke: #080d19;
  stroke-width: 3px;
  fill: #080d19;
  pointer-events: none;
}

html:not(.dark) .node-label-bg {
  stroke: #ffffff;
  fill: #ffffff;
}

.node-label {
  font-size: 11px;
  font-weight: 600;
  fill: #e2e8f0;
  pointer-events: none;
}

html:not(.dark) .node-label {
  fill: #0f172a;
}

.global-text {
  font-size: 9px;
  font-weight: 700;
  fill: #ffffff;
  pointer-events: none;
}

/* 侧边审查面板 */
.graph-inspector {
  display: flex;
  flex-direction: column;
  background: var(--app-bg-surface);
  border-left: 1px solid var(--app-border);
}

.global-panel {
  padding: 12px 14px;
  border-bottom: 1px solid var(--app-border);
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.panel-title {
  font-size: 12px;
  font-weight: 700;
  color: #f59e0b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.hint-icon {
  font-size: 13px;
  color: var(--app-text-muted);
  cursor: help;
}

.global-rules-scroll {
  max-height: 180px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.global-rule-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid var(--app-border-subtle);
  cursor: pointer;
  transition: all 0.2s ease;
}

.global-rule-row:hover,
.global-rule-row.is-active {
  background: rgba(245, 158, 11, 0.12);
  border-color: rgba(245, 158, 11, 0.35);
}

.rule-name {
  font-size: 11.5px;
  color: var(--app-text-primary);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rule-type {
  font-size: 10px;
  color: var(--app-text-muted);
}

/* 选中实体面板 */
.selected-detail-panel {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1;
}

.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--app-border);
}

.detail-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--app-text-primary);
}

.type-pill {
  color: #ffffff;
  border: none;
  font-size: 10.5px;
}

.detail-attrs {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.attr-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
}

.attr-row.block-row {
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

.attr-key {
  color: var(--app-text-muted);
  font-size: 11.5px;
}

.attr-val {
  color: var(--app-text-primary);
}

.code-val {
  font-family: var(--app-font-mono);
  color: var(--app-primary);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.copy-icon {
  font-size: 13px;
  cursor: pointer;
  color: var(--app-text-muted);
  transition: color 0.2s ease;
}

.copy-icon:hover {
  color: var(--app-primary);
}

.desc-val {
  font-size: 12px;
  line-height: 1.5;
  color: var(--app-text-secondary);
}

.formula-val {
  font-family: var(--app-font-mono);
  font-size: 11.5px;
  color: #a5b4fc;
  background: rgba(0, 0, 0, 0.2);
  padding: 4px 8px;
  border-radius: 4px;
  width: 100%;
  word-break: break-all;
}

.global-explain-callout {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 10px;
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.25);
  border-radius: 6px;
  color: #f59e0b;
  font-size: 11.5px;
  line-height: 1.5;
}

.topology-explain-callout {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 10px;
  background: rgba(56, 189, 248, 0.08);
  border: 1px solid rgba(56, 189, 248, 0.25);
  border-radius: 6px;
  color: var(--app-primary);
  font-size: 11.5px;
  line-height: 1.5;
}

.empty-inspector {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  gap: 10px;
  color: var(--app-text-muted);
  text-align: center;
  flex: 1;
}

.empty-icon {
  font-size: 32px;
  opacity: 0.5;
}

.empty-text {
  font-size: 12px;
  line-height: 1.6;
}

@media (max-width: 900px) {
  .graph-layout {
    grid-template-columns: 1fr;
  }
}
</style>
