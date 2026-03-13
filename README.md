# OpenRouter Model Explorer

一个自动抓取 [OpenRouter](https://openrouter.ai/) 全部 AI 模型信息并生成对比页面的工具。

## 在线预览

部署后可直接访问 Cloudflare Worker URL 查看实时模型对比表，支持搜索、排序、筛选。

- `/`：全量模型浏览页
- `/flashship`：OpenAI / Anthropic / Google / Grok / DeepSeek / Qwen / Kimi / MiniMax / Z.ai 最新代际模型对照页，包含同代轻量级/高配等核心变体

## 功能

- 从 OpenRouter API 获取所有可用模型
- 生成包含搜索、排序、筛选功能的静态 HTML 页面
- 展示模型价格（输入/输出/图片/推理）、上下文长度、模态等信息
- 支持按 Provider 筛选、按价格排序
- 额外生成 `/flashship` 页面，对比指定厂商最新一代 family 及其核心变体
- 提供本地脚本和 Cloudflare Worker 两种运行方式

## 项目结构

```
├── fetch_models.py        # 本地 Python 脚本，直接生成 HTML 文件
├── output/                # 本地脚本生成的 HTML 输出目录
└── worker/                # Cloudflare Worker 部署
    ├── src/worker.py      # Worker 源码（Python Worker）
    ├── wrangler.toml      # Wrangler 配置
    └── package.json
```

## 使用方式

### 本地运行

无需安装任何依赖，使用 Python 标准库即可：

```bash
python fetch_models.py
```

生成的 HTML 文件保存在 `output/` 目录，包括：

- `models_*.html`：全量模型浏览页
- `flashship_*.html`：最新一代模型对照页

### 部署到 Cloudflare Workers

1. 安装依赖：

```bash
cd worker
npm install
```

2. 在 `wrangler.toml` 中填入你的 KV Namespace ID：

```toml
[[kv_namespaces]]
binding = "MODELS_KV"
id = "YOUR_KV_NAMESPACE_ID"
```

3. 部署：

```bash
npm run deploy
```

Worker 会每小时自动通过 cron 更新数据，也可以访问 `/refresh` 手动触发更新。每次刷新都会同时更新 `/` 和 `/flashship` 两个页面。

## License

MIT
