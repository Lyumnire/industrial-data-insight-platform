// AI-assisted
/**
 * ML 结果渲染适配层（T-010 前置契约：a07-agent/app/ml/{contracts,templates}.py）。
 *
 * metrics 键名与 plots.data 四种形态均来自引擎沙箱模板的真实输出，此处只做展示映射：
 * - scatter {x, y, points: [[a,b],…]}            回归：实际值 vs 预测值
 * - scatter {x, y, series: [{name, data}]}       聚类：PCA 二维散点按簇着色
 * - histogram {bins, counts, threshold}          异常检测：异常分数分布 + 阈值线
 * - heatmap {labels, matrix}                     分类：混淆矩阵
 * - line {x, y, points, auc}                     分类：ROC 曲线
 * 无法识别的形态返回 null，由组件降级为原始 JSON 展示（不伪造、不崩溃）。
 */
import type { EChartsOption } from 'echarts'
import type { MLPlot, ModelType, MlTaskType } from '../types/agent'

export const MODEL_TYPE_LABELS: Record<ModelType, string> = {
  linear_regression: '线性回归',
  decision_tree: '决策树',
  random_forest: '随机森林',
  logistic_regression: '逻辑回归',
  kmeans: 'KMeans 聚类',
  isolation_forest: '孤立森林（异常检测）',
}

export const TASK_TYPE_LABELS: Record<MlTaskType, string> = {
  regression: '回归',
  classification: '分类',
  clustering: '聚类',
  anomaly: '异常检测',
}

/** 分析主题中文名（与 a07-agent/app/report/builder.py TOPIC_NAMES 对齐）。 */
export const TOPIC_LABELS: Record<string, string> = {
  production: '生产分析',
  quality: '质量分析',
  equipment: '设备分析',
  inventory: '库存分析',
  general: '综合分析',
}

const METRIC_LABELS: Record<string, string> = {
  r2: 'R²',
  mae: 'MAE',
  rmse: 'RMSE',
  accuracy: '准确率',
  precision: '精确率 (P)',
  recall: '召回率 (R)',
  f1: 'F1',
  silhouette: '轮廓系数',
  n_clusters: '簇数',
  n_anomalies: '异常数',
  anomaly_ratio: '异常占比',
  threshold: '异常分数阈值',
  score_mean: '异常分数均值',
  score_max: '异常分数最大值',
  train_rows: '训练行数',
  test_rows: '测试行数',
}

export function metricLabel(key: string): string {
  return METRIC_LABELS[key] ?? key
}

/** 指标值展示：占比类转百分数，对象/数组转 JSON，其余 String 化；未知结构不崩（R4：全部来自真实载荷）。 */
export function formatMetricValue(key: string, value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (key === 'anomaly_ratio' && typeof value === 'number') return `${(value * 100).toFixed(1)}%`
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

// ---------- plot.data 形态守卫（type 别名：具隐式索引签名，可作 Record 的类型谓词） ----------

type PointsData = {
  x?: unknown
  y?: unknown
  points: [number, number][]
}

function isPointsData(d: Record<string, unknown>): d is PointsData {
  return (
    Array.isArray(d.points) &&
    d.points.length > 0 &&
    d.points.every(
      (p) => Array.isArray(p) && p.length === 2 && typeof p[0] === 'number' && typeof p[1] === 'number',
    )
  )
}

type SeriesData = {
  x?: unknown
  y?: unknown
  series: { name?: unknown; data: [number, number][] }[]
}

function isSeriesData(d: Record<string, unknown>): d is SeriesData {
  return (
    Array.isArray(d.series) &&
    d.series.length > 0 &&
    d.series.every(
      (s) =>
        typeof s === 'object' &&
        s !== null &&
        Array.isArray((s as Record<string, unknown>).data) &&
        ((s as Record<string, unknown>).data as unknown[]).every(
          (p) => Array.isArray(p) && p.length === 2 && typeof p[0] === 'number' && typeof p[1] === 'number',
        ),
    )
  )
}

type HistogramData = {
  bins: number[]
  counts: number[]
  threshold?: number
}

function isHistogramData(d: Record<string, unknown>): d is HistogramData {
  return (
    Array.isArray(d.bins) &&
    Array.isArray(d.counts) &&
    d.bins.every((v) => typeof v === 'number') &&
    d.counts.every((v) => typeof v === 'number') &&
    d.bins.length >= 2 &&
    d.counts.length === d.bins.length - 1
  )
}

type HeatmapData = {
  labels: string[]
  matrix: number[][]
}

function isHeatmapData(d: Record<string, unknown>): d is HeatmapData {
  if (!Array.isArray(d.labels) || !d.labels.every((v) => typeof v === 'string')) return false
  const labels = d.labels
  if (!Array.isArray(d.matrix)) return false
  const matrix = d.matrix
  return (
    matrix.length === labels.length &&
    matrix.every((row) => Array.isArray(row) && row.length === labels.length && row.every((v) => typeof v === 'number'))
  )
}

type RocData = {
  x?: unknown
  y?: unknown
  points: [number, number][]
  auc?: number
}

function isRocData(d: Record<string, unknown>): d is RocData {
  return isPointsData(d)
}

function axisName(v: unknown, fallback: string): string {
  return typeof v === 'string' && v.length > 0 ? v : fallback
}

/** plot → EChartsOption；形态不识别返回 null（组件降级为 JSON 展示）。 */
export function buildMlPlotOption(plot: MLPlot): EChartsOption | null {
  const d = plot.data
  switch (plot.type) {
    case 'scatter': {
      if (isSeriesData(d)) {
        return {
          tooltip: { trigger: 'item' },
          legend: {},
          xAxis: { type: 'value', name: axisName(d.x, '主成分 1') },
          yAxis: { type: 'value', name: axisName(d.y, '主成分 2') },
          series: d.series.map((s) => ({
            type: 'scatter' as const,
            name: typeof s.name === 'string' ? s.name : 'series',
            data: s.data,
            symbolSize: 7,
          })),
        }
      }
      if (isPointsData(d)) {
        return {
          tooltip: { trigger: 'item' },
          xAxis: { type: 'value', name: axisName(d.x, '实际值'), scale: true },
          yAxis: { type: 'value', name: axisName(d.y, '预测值'), scale: true },
          series: [{ type: 'scatter' as const, name: axisName(d.y, '预测值'), data: d.points, symbolSize: 7 }],
        }
      }
      return null
    }
    case 'histogram': {
      if (!isHistogramData(d)) return null
      const categories = d.bins.slice(0, -1).map((edge, i) => `${edge.toFixed(3)}~${d.bins[i + 1]?.toFixed(3)}`)
      const series: EChartsOption['series'] = [
        {
          type: 'bar' as const,
          name: '样本数',
          data: d.counts,
        },
      ]
      if (typeof d.threshold === 'number') {
        series[0] = {
          ...series[0],
          markLine: {
            symbol: 'none',
            data: [{ yAxis: d.threshold, label: { formatter: `阈值 ${d.threshold.toFixed(3)}` } }],
          },
        }
      }
      return {
        tooltip: { trigger: 'axis' },
        xAxis: { type: 'category', name: '异常分数区间', data: categories },
        yAxis: { type: 'value', name: '样本数' },
        series,
      }
    }
    case 'heatmap': {
      if (!isHeatmapData(d)) return null
      const maxV = Math.max(...d.matrix.flat())
      const cells: [number, number, number][] = []
      d.matrix.forEach((row, i) => row.forEach((v, j) => cells.push([j, i, v])))
      return {
        tooltip: {
          formatter: (p: unknown) => {
            const cell = p as { value?: [number, number, number] }
            const v = cell?.value?.[2]
            return `实际 ${d.labels[cell?.value?.[1] ?? 0]} / 预测 ${d.labels[cell?.value?.[0] ?? 0]}：${v ?? '?'}`
          },
        },
        grid: { left: 80, bottom: 80 },
        xAxis: { type: 'category', data: d.labels, name: '预测标签' },
        yAxis: { type: 'category', data: d.labels, name: '实际标签' },
        visualMap: {
          min: 0,
          max: maxV > 0 ? maxV : 1,
          calculable: true,
          orient: 'horizontal',
          left: 'center',
          bottom: 0,
        },
        series: [
          {
            type: 'heatmap' as const,
            data: cells,
            label: { show: true },
          },
        ],
      }
    }
    case 'line': {
      if (!isRocData(d)) return null
      const aucSuffix = typeof d.auc === 'number' ? `（AUC=${d.auc.toFixed(3)}）` : ''
      return {
        tooltip: { trigger: 'item' },
        xAxis: { type: 'value', name: axisName(d.x, 'fpr'), max: 1 },
        yAxis: { type: 'value', name: axisName(d.y, 'tpr'), max: 1 },
        series: [
          {
            type: 'line' as const,
            name: `ROC${aucSuffix}`,
            data: d.points,
            showSymbol: false,
            smooth: true,
          },
        ],
      }
    }
    default:
      return null
  }
}
