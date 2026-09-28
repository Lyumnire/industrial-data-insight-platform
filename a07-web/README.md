# a07-web · 前端（Vue 3 + TS + Vite）

A07 制造数据智能问析平台前端。当前为 P1 最小切片（T-007）：登录页 + 智能问析工作台（SSE 流式渲染）。

## 启动

```bash
npm install
npm run dev        # http://localhost:5173，/api 代理到 http://localhost:8080（a07-server）
```

## 质量门禁（docs/04 §6 前端质量）

```bash
npm run type-check # vue-tsc，TS strict
npm run build      # type-check + vite build
```

## 结构

- `src/types/agent.ts` —— Agent 事件协议契约锚点（docs/03 §4，勿擅自改名）
- `src/types/knowledge.ts` / `metadata.ts` —— S2/S3 契约 DTO（docs/api/README.md §1/§2）
- `src/api/http.ts` —— axios 实例 + Authorization 拦截器 + 登录 + describeHttpError
- `src/api/knowledge.ts` / `metadata.ts` / `common.ts` —— F2/F3 API 与 PageResult 解包
- `src/api/sse.ts` —— fetch + ReadableStream 解析 SSE（POST /api/chat/analyze）
- `src/stores/` —— pinia：auth（token）、chat（SSE 事件 → 消息流状态）
- `src/views/` —— LoginView、WorkbenchView、MlTasksView、KnowledgeView（四 Tab+图谱）、MetadataView
- `src/components/` —— StepTimeline/ResultCard 系、AppNav、knowledge/*、metadata/*

## 依赖服务

- a07-server（8080）：登录 + SSE 代理（前端不直连 8100 引擎）
- 引擎未启动时页面给出可读错误提示，不白屏、不伪造数据（红线 R4）
