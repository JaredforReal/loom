# Loom WebUI

Loom 的 Web 前端，基于 React + TypeScript + Vite 构建。

## 目录结构

```
webui/
├── app.py              # Python 入口 — 重新导出 FastAPI app，生产模式下挂载 dist/ 静态文件
├── frontend/                # Vite 前端项目
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── main.tsx            # 应用入口
│       ├── App.tsx             # 根组件
│       ├── components/         # UI 组件
│       │   ├── KanbanBoard.tsx # 看板主视图
│       │   ├── Column.tsx      # 看板列（new / waiting / done / dismissed）
│       │   ├── EnvelopeCard.tsx
│       │   ├── EnvelopeDetail.tsx
│       │   ├── EnvelopeDrawer.tsx
│       │   ├── Sidebar.tsx     # 左侧边栏（sources 筛选）
│       │   ├── StatusBar.tsx   # 底部状态栏
│       │   └── ui/             # shadcn/ui 基础组件
│       └── lib/
│           ├── api.ts          # API 客户端（fetch 封装）
│           ├── types.ts        # TypeScript 类型定义
│           ├── settings.ts     # 前端设置
│           └── utils.ts        # 工具函数
└── dist/               # 构建产物（gitignored，由 vite build 生成）
```

## 开发模式

前端和后端分别运行，Vite dev server 自动将 `/api` 请求代理到 daemon。

```bash
# 终端 1：启动 daemon（提供 API）
loom daemon --foreground

# 终端 2：启动前端开发服务器
cd loom/webui/frontend
npm install
npm run dev
```

打开 http://localhost:5173 即可访问。前端会通过 Vite proxy 自动转发 `/api/*` 请求到 `http://127.0.0.1:8732`。

## 生产模式

构建前端静态文件，由 daemon 直接提供 WebUI 服务：

```bash
cd loom/webui/src
npm run build    # 输出到 webui/dist/

# 启动 daemon，会自动检测 dist/ 并挂载静态文件
loom daemon --foreground
```

此时访问 http://127.0.0.1:8732 直接返回前端页面，`/api/*` 路径仍由 FastAPI 处理。

## API 接口

前端使用的所有接口（均在 `loom/api_server.py` 中定义）：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | Daemon 状态（5s 轮询） |
| GET | `/api/envelopes` | 列出信封（7s 轮询） |
| GET | `/api/envelopes/{id}` | 单条信封详情 |
| POST | `/api/envelopes/{id}/approve` | 批准信封 |
| POST | `/api/envelopes/{id}/dismiss` | 忽略信封 |
| GET | `/api/sources` | 列出数据源及未读数 |

## 技术栈

- **React 18** + **TypeScript**
- **Vite** — 开发服务器 + 构建工具
- **Tailwind CSS** — 样式
- **shadcn/ui** (Radix UI) — 组件库
- **TanStack React Query** — 数据获取与轮询
- **react-markdown** + **remark-gfm** — Markdown 渲染
- **Lucide** — 图标
