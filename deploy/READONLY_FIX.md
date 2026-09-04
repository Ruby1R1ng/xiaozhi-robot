# 只读知识库线上修复

2026-09-04修复：知识库位于/opt只读挂载中，之前WAL模式在辅助文件缺失时可能尝试创建-wal/-shm而失败。已停止服务、使用SQLite backup创建一致性备份、执行checkpoint并切换journal_mode=DELETE。未关闭ProtectSystem=strict，未放宽目录权限，未改模型或API密钥。

实际数据库：/opt/xiaozhi-search/data/guolei-20260804/knowledge.sqlite3。
备份：/opt/xiaozhi-search/backup-readonly-20260904-225202/knowledge.sqlite3。
PRAGMA quick_check通过；173篇、10294片段、1条核验数学记录均保持不变。

验收不是root在普通终端独立调用：测试进入正式服务的mount namespace，切换UID/GID至admin(1000)，继承运行进程环境，启动stdio MCP并调用query_information。

- 完整标题Convergence and Logarithm Laws of Self-tuning Regulators：知识库第一名，约0.472秒。
- 二分之三加根号二：核验公式命中，约0.0067秒。
- 郭雷自适应控制有哪些研究：知识库命中，约0.2495秒。
- 验证前后均无-wal/-shm文件；服务active，WebSocket已连接，工具列表和Ping正常。

建库脚本也改为DELETE模式，防止重新发布WAL库。以后批量更新须在非在线副本上完成，保留核验表，做一致性/只读环境验收后停服切换，不能在只读发布目录热写数据库。

以上耗时不含语音识别与合成。实体机器人还需实际提问确认最终播报。
