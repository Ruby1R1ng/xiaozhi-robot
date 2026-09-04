import json
import logging
import os
import sqlite3
import threading
import time
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

from mcp.server.fastmcp import FastMCP

from knowledge_base import KnowledgeBase
from resilient_search import search as resilient_web_search
from formula_evidence import normalize_alias


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("web_search")
mcp = FastMCP("xiaozhi-web-search")


def _integer_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} 必须是整数") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} 必须在 {minimum} 到 {maximum} 之间")
    return value


SEARCH_DEPTH = os.getenv("TAVILY_SEARCH_DEPTH", "basic").strip().lower()
if SEARCH_DEPTH not in {"basic", "fast", "ultra-fast", "advanced"}:
    raise RuntimeError("TAVILY_SEARCH_DEPTH 配置无效")

MAX_RESULTS = _integer_setting("TAVILY_MAX_RESULTS", 10, 1, 20)
MONTHLY_CREDIT_BUDGET = _integer_setting("TAVILY_MONTHLY_CREDIT_BUDGET", 900, 1, 1000)
CACHE_TTL_SECONDS = _integer_setting("TAVILY_CACHE_TTL_SECONDS", 1800, 0, 86400)
ESTIMATED_CREDITS = 2 if SEARCH_DEPTH == "advanced" else 1
SILICONFLOW_BASE_URL = os.getenv(
    "SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"
).strip().rstrip("/")
SILICONFLOW_MODEL = os.getenv("SILICONFLOW_MODEL", "zai-org/GLM-5.2").strip()
SILICONFLOW_MAX_TOKENS = _integer_setting(
    "SILICONFLOW_MAX_TOKENS", 450, 256, 8192
)
SILICONFLOW_TIMEOUT_SECONDS = _integer_setting(
    "SILICONFLOW_TIMEOUT_SECONDS", 22, 3, 300
)
SILICONFLOW_THINKING_BUDGET = _integer_setting(
    "SILICONFLOW_THINKING_BUDGET", 128, 128, 32768
)
SUMMARY_SOURCE_CHARS = _integer_setting(
    "SUMMARY_SOURCE_CHARS", 500, 200, 5000
)
USAGE_DB_PATH = Path(
    os.getenv("TAVILY_USAGE_DB", str(Path.cwd() / ".tavily_usage.sqlite3"))
)

_knowledge_base: KnowledgeBase | None = None
_knowledge_base_lock = threading.Lock()

_KNOWLEDGE_ROUTE_MARKERS = (
    "郭雷", "院士", "论文", "文献", "定理", "证明", "自适应", "控制理论",
    "随机系统", "系统辨识", "参数估计", "最小二乘", "反馈能力", "非线性镇定",
    "多智能体", "博弈控制", "self-tuning", "adaptive control", "stochastic system",
    "system identification", "parameter estimation", "least squares",
    "feedback capability", "multi-agent", "game-based control", " armax", " arma",
    " els", " lms", " rls", " pid", " epd",
)


def _get_knowledge_base() -> KnowledgeBase:
    global _knowledge_base
    if _knowledge_base is None:
        with _knowledge_base_lock:
            if _knowledge_base is None:
                _knowledge_base = KnowledgeBase()
    return _knowledge_base


class UsageStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS monthly_usage (
                    month TEXT PRIMARY KEY,
                    credits INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS search_cache (
                    cache_key TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _month() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def reserve(self, credits: int) -> tuple[bool, int]:
        month = self._month()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR IGNORE INTO monthly_usage(month, credits) VALUES (?, 0)",
                (month,),
            )
            cursor = connection.execute(
                """
                UPDATE monthly_usage
                SET credits = credits + ?
                WHERE month = ? AND credits + ? <= ?
                """,
                (credits, month, credits, MONTHLY_CREDIT_BUDGET),
            )
            used = connection.execute(
                "SELECT credits FROM monthly_usage WHERE month = ?", (month,)
            ).fetchone()[0]
            return cursor.rowcount == 1, int(used)

    def refund(self, credits: int) -> None:
        if credits <= 0:
            return
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE monthly_usage
                SET credits = MAX(credits - ?, 0)
                WHERE month = ?
                """,
                (credits, self._month()),
            )

    def current_usage(self) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT credits FROM monthly_usage WHERE month = ?", (self._month(),)
            ).fetchone()
            return int(row[0]) if row else 0

    def get_cached(self, cache_key: str) -> dict[str, Any] | None:
        if CACHE_TTL_SECONDS == 0:
            return None
        threshold = time.time() - CACHE_TTL_SECONDS
        with self._connection() as connection:
            connection.execute("DELETE FROM search_cache WHERE created_at < ?", (threshold,))
            row = connection.execute(
                "SELECT payload FROM search_cache WHERE cache_key = ? AND created_at >= ?",
                (cache_key, threshold),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def set_cached(self, cache_key: str, payload: dict[str, Any]) -> None:
        if CACHE_TTL_SECONDS == 0:
            return
        serialized = json.dumps(payload, ensure_ascii=False)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO search_cache(cache_key, created_at, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    created_at = excluded.created_at,
                    payload = excluded.payload
                """,
                (cache_key, time.time(), serialized),
            )


usage_store = UsageStore(USAGE_DB_PATH)


@mcp.tool(
    name="web_search",
    title="联网查询",
    description=(
        "CUSTOM WEB SEARCH. Use Tavily plus SiliconFlow GLM, with independent Zhipu search and GLM fallback on failure. Return a summarized answer with numbered sources. "
        "Use this tool exactly ONCE per user request: put all subquestions into one query_text and never split "
        "a request into multiple web_search calls. Use it for current news, prices, policies, people, "
        "organizations, research papers, and facts needing online verification. "
        "Do not use Xiaozhi's official web search. 输入完整问题，一次调用即可获得带来源的总结；同一用户问题禁止多次调用。"
    ),
)
async def web_search(query_text: str) -> dict[str, Any]:
    return await resilient_web_search(query_text, usage_store)


@mcp.tool(
    name="knowledge_search",
    title="郭雷论文知识库",
    description=(
        "CUSTOM PRIVATE KNOWLEDGE BASE. Search the private Guo Lei scholarly paper knowledge base. Use this tool for questions "
        "about Professor Guo Lei's papers, theories, algorithms, results, proofs, or research history. "
        "Return an answer grounded only in the supplied paper excerpts and keep the numbered paper/page citations. "
        "查询郭雷院士论文、理论、算法、研究工作和学术观点时使用；回答必须保留论文名和页码来源。"
    ),
)
def knowledge_search(query_text: str) -> dict[str, Any]:
    """Retrieve page-cited evidence from the private paper corpus."""
    try:
        return _get_knowledge_base().search(query_text, limit=5)
    except Exception as exc:
        logger.exception("Knowledge base search failed: %s", type(exc).__name__)
        return {
            "success": False,
            "query": " ".join((query_text or "").split())[:400],
            "error_code": "knowledge_search_error",
            "error": "论文知识库查询暂时不可用，请稍后重试",
            "result": [],
        }


def _automatic_route(query_text: str) -> Literal["knowledge", "web"]:
    normalized = f" {query_text.casefold()}"
    formula_query = normalize_alias(query_text)
    if any(term in formula_query for term in ('3/2+sqrt2', 'xieguoconstant', '谢郭常数', 'howmuchuncertaintycanbedealtwithbyfeedback')):
        return "knowledge"
    return "knowledge" if any(
        marker in normalized for marker in _KNOWLEDGE_ROUTE_MARKERS
    ) else "web"


@mcp.tool(
    name="query_information",
    title="每问必查：私库或联网",
    description=(
        "MANDATORY information gateway for every factual, explanatory, comparative, recommendation, "
        "or current-information question. Call this tool before answering. Set source='knowledge' for "
        "questions about Guo Lei, his papers, control theory, adaptive/stochastic systems, algorithms, "
        "theorems, or proofs; set source='web' for current or general information outside that corpus. "
        "Use source='auto' only when uncertain. This gateway uses only the user's private paper database "
        "or the user's web search accounts (Tavily primary, Zhipu fallback), never Xiaozhi's official knowledge base/search. "
        "每个事实性、解释性、比较、推荐或时效性问题，回答前必须调用本工具；郭雷论文及控制理论问题走私有知识库，其他问题走自有Tavily联网。"
    ),
)
async def query_information(
    query_text: str,
    source: Literal["auto", "knowledge", "web"] = "auto",
) -> dict[str, Any]:
    """Route one user question exclusively to the private corpus or Tavily."""
    query = " ".join((query_text or "").split())
    if not query:
        return {
            "success": False,
            "route": "none",
            "error": "查询内容不能为空",
            "result": [],
        }
    selected: Literal["knowledge", "web"] = (
        _automatic_route(query) if source == "auto" else source
    )
    if selected == "knowledge":
        started = time.monotonic()
        budget = float(os.getenv('KNOWLEDGE_GATEWAY_BUDGET_SECONDS', '4'))
        try:
            payload = await asyncio.wait_for(asyncio.to_thread(knowledge_search, query), timeout=min(1.2, budget))
        except asyncio.TimeoutError:
            payload = {'success':False,'result':[],'evidence_status':'insufficient','error_code':'knowledge_timeout'}
        status = payload.get('evidence_status', 'insufficient')
        if not payload.get('success') or status in ('insufficient','partial'):
            remaining = budget - (time.monotonic()-started)
            supplement = None
            if remaining > 0.1:
                try:
                    supplement = await asyncio.wait_for(
                        resilient_web_search(query, usage_store, budget_seconds=remaining), timeout=remaining)
                except asyncio.TimeoutError:
                    pass
            if supplement and supplement.get('success'):
                payload = dict(supplement, knowledge_evidence_status=status, knowledge_result=payload.get('result', []))
                selected = 'web'
            else:
                payload = dict(payload)
                payload.update(web_supplement_attempted=remaining>0.1, web_supplement_status='not_completed',
                               summary_status='insufficient_evidence', success=False,
                               summary='知识库暂未找到足够的已核验证据，联网补查也未在快速响应时限内完成，暂时无法可靠回答。')
        payload.setdefault('timing_seconds', {})['gateway_total'] = round(time.monotonic()-started,4)
    else:
        payload = await web_search(query)
    response = dict(payload)
    response["route"] = selected
    response["data_source"] = (
        "private_guolei_knowledge_base"
        if selected == "knowledge"
        else payload.get("data_source", "user_tavily_web_search")
    )
    return response


if __name__ == "__main__":
    mcp.run(transport="stdio")
