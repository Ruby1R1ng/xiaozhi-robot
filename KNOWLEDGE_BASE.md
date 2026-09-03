# 郭雷论文知识库

## 方案

- 原始 PDF 是事实主库，不能只保存官网摘要；摘要无法回答论文中的定理、算法、证明和实验细节。
- 有可靠文字层的 PDF 直接按页提取；扫描件和文字稀疏文件使用 MinerU OCR。
- 每个文本块保留论文名、年份、页码和提取方式，回答时可回到原 PDF 核对。
- SQLite FTS5 负责精确词检索，`sqlite-vec` + `BAAI/bge-m3` 分别建立论文标题/摘要向量和正文向量，三路结果按论文级加权 RRF 融合。
- Crossref 只用于补充 DOI、作者、期刊、官网链接和摘要，不替代 PDF 正文。
- 服务器不加载本地大模型；查询向量由硅基流动的 `BAAI/bge-m3` 生成，适合轻量云服务器。

## 构建

```powershell
python knowledge_ingest.py prepare --archive "郭雷老师.zip" --output data/guolei_full
mineru -p data/guolei_full/ocr_input -o data/guolei_full/ocr -m ocr -b hybrid-engine --effort high
python knowledge_ingest.py build --output data/guolei_full --ocr-root data/guolei_full/ocr --database data/guolei_full/knowledge.sqlite3 --embedding-provider siliconflow
```

构建时需要环境变量 `SILICONFLOW_API_KEY`。线上查询还使用：

```text
KNOWLEDGE_DB_PATH=/opt/xiaozhi-search/data/guolei/knowledge.sqlite3
KNOWLEDGE_EMBEDDING_MODEL=BAAI/bge-m3
KNOWLEDGE_EMBEDDING_TIMEOUT_SECONDS=5
```

## 查询接口

小智 MCP 中提供 `knowledge_search(query_text)`。它返回：

- 与问题最相关的论文正文片段；
- 论文标题、年份和页码引用；
- DOI/官网链接（能够可靠匹配时）；
- OCR 证据的核对提示；
- 向量化、数据库检索和总耗时。

## 每问必查路由

小智优先调用统一入口 `query_information(query_text, source)`：

- `source=knowledge`：只查询自建郭雷论文库；
- `source=web`：只调用用户自己的 Tavily 搜索；
- `source=auto`：由服务端关键词规则自动选择，学术论文与控制理论问题优先走私库，其他问题走 Tavily。

小智控制台已关闭官方的天气、新闻、知识库和联网搜索信息源，并在角色提示词中要求每个事实性、解释性、比较、推荐或时效问题先调用一次 `query_information`。笑话和音乐属于非事实问答能力，仍保持启用。

## 样板验收

10 篇样板包含 3 篇扫描件和 7 篇文字层 PDF，共 105 页、383 个文本块。10 个中英文问题的 Top-3 命中率和页码引用有效率均为 100%；数据库检索 P95 为 7.6 ms。

## 全量验收

完整库包含 173 篇论文、4,655 页和 10,294 个可检索文本块，其中 140 篇直接提取文字层，33 篇经过 MinerU OCR。数据库完整性检查为 `ok`，正文向量与文本块逐一对应，另有 173 条论文标题/摘要向量。

全量库使用 10 个中英文问题实测：Top-3 命中率 100%，页码引用有效率 100%，数据库检索 P95 为 43.9 ms；包含硅基流动查询向量生成的端到端 P95 为 722.7 ms。详细结果见 `data/guolei_full/benchmark_report.json`。
