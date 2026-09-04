# 小智机器人

小智机器人是一个基于小智 MCP 接入点的知识库与联网检索服务。它把语音问答中的事实性问题路由到两类自有数据源：

- **私有论文知识库**：面向论文、控制理论、自适应控制、随机系统、算法与定理证明等问题；
- **自有联网搜索**：面向新闻、人物、政策、推荐、价格等一般性或时效性问题。

本项目不依赖小智官方知识库或官方联网搜索。所有敏感配置都通过服务器环境文件注入，仓库中只保留 `xxxxxxx` 占位符。

## 功能

- 小智 MCP WebSocket 桥接
- 统一查询入口 `query_information`
- 论文级与正文级混合检索
- 中英文语义向量检索
- Tavily 联网搜索与免费额度保护
- 硅基流动模型总结
- 本地缓存与请求用量统计
- systemd 服务守护

## 技术路线

```text
小智语音识别
    ↓
小智智能体调用 query_information
    ↓
┌────────────────────┬────────────────────┐
│ source=knowledge   │ source=web          │
│ 论文知识库          │ Tavily 联网搜索     │
│ SQLite FTS5        │ 搜索结果缓存         │
│ BGE-M3 + sqlite-vec│ 硅基流动 GLM 总结    │
└────────────────────┴────────────────────┘
    ↓
返回来源、页码、摘要与结构化结果
    ↓
小智组织最终回答并播报
```

### 知识库

- 论文数据：173 篇，4,655 页
- 文本块：10,294 个
- 文字版 PDF：140 篇，直接按页提取
- 扫描版 PDF：33 篇，MinerU OCR 识别
- 向量模型：`BAAI/bge-m3`
- 总结模型：`Pro/zai-org/GLM-5.1`

论文检索同时使用关键词、论文级向量和正文级向量。结果保留论文标题、年份、页码、DOI 或官网链接。扫描件中的精确公式需要回到原 PDF 核对。

## 安装

```bash
git clone https://github.com/Ruby1R1ng/xiaozhi-robot.git
cd xiaozhi-robot
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Windows PowerShell 使用：

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## 配置

复制示例配置并填入真实值：

```bash
cp .env.example .env
chmod 600 .env
```

需要配置：

```text
MCP_ENDPOINT=xxxxxxx
TAVILY_API_KEY=xxxxxxx
SILICONFLOW_API_KEY=xxxxxxx
```

获取方式：

- `MCP_ENDPOINT`：小智控制台 → 智能体 → 配置 → 扩展能力 → MCP接入点
- `TAVILY_API_KEY`：Tavily 控制台
- `SILICONFLOW_API_KEY`：硅基流动控制台

## 使用

### 启动 MCP 服务

```bash
set -a
source .env
set +a
python mcp_pipe.py web_search.py
```

### 三个 MCP 工具

| 工具 | 用途 |
| --- | --- |
| `query_information` | 统一入口。学术论文与控制理论走 `source=knowledge`，其他问题走 `source=web`，不确定时可用 `auto` |
| `knowledge_search` | 只查自建论文知识库，返回标题、年份、页码与原文片段 |
| `web_search` | 只调用 Tavily，返回实时网页结果与总结 |

示例：

```text
关于反馈能力极限做了哪些研究？请给出论文和页码。
今天人工智能领域有什么重要新闻？请列出来源。
```

## 构建论文知识库

```bash
python knowledge_ingest.py prepare --archive /path/to/papers.zip --output data/guolei
python knowledge_ingest.py build --output data/guolei --ocr-root data/guolei/ocr --database data/guolei/knowledge.sqlite3 --embedding-provider siliconflow
```

构建时必须配置 `SILICONFLOW_API_KEY`。大语料建议先抽取 10 篇样板验证，再批量处理全量论文。

## 部署到 Ubuntu 服务器

```bash
sudo mkdir -p /opt/xiaozhi-search
sudo cp -r . /opt/xiaozhi-search/
cd /opt/xiaozhi-search
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sudo cp deploy/xiaozhi-search.service /etc/systemd/system/xiaozhi-search.service
sudo systemctl daemon-reload
sudo systemctl enable --now xiaozhi-search
```

建议把环境文件放在 `/etc/xiaozhi-search.env`，并把 systemd 单元中的 `EnvironmentFile` 指向该文件。迁移到新服务器时，先停止旧实例，再启动新实例，避免两个服务同时连接同一个 MCP 接入点。

## 测试

```bash
.venv/bin/python tests/query_router_smoke.py
.venv/bin/python tests/mcp_smoke.py
.venv/bin/python tests/unified_query_mcp_smoke.py
```

联网测试会消耗 Tavily 额度。全量论文基准测试需要先构建知识库。

## 二次开发入口

- `web_search.py`：MCP 工具、Tavily 搜索、总结与统一路由
- `knowledge_base.py`：论文知识的 FTS5 与向量检索
- `knowledge_ingest.py`：论文提取、OCR、元数据补充和向量库构建
- `mcp_pipe.py`：小智 WebSocket 与本地 stdio MCP 桥
- `deploy/`：systemd 与服务器运维脚本
- `tests/`：MCP、检索、总结与模型测试

