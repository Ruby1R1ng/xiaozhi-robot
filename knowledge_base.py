"""Lightweight hybrid retrieval for the Guo Lei paper knowledge base."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import httpx
from formula_evidence import lookup as lookup_formula, relevance as assess_relevance

try:
    import sqlite_vec
except ImportError:  # pragma: no cover - exercised by the FTS-only fallback
    sqlite_vec = None


logger = logging.getLogger("knowledge_base")
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "guolei" / "knowledge.sqlite3"


def connect_database(database_path: Path, *, load_vectors: bool = True) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path, timeout=10, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    if load_vectors and sqlite_vec is not None:
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.enable_load_extension(False)
    return connection


def _normalize_query(value: str) -> str:
    return " ".join((value or "").strip().split())


def _fts_query(value: str) -> str:
    ascii_terms = re.findall(r"[A-Za-z0-9][A-Za-z0-9_.-]+", value)
    cjk_terms = re.findall(r"[\u3400-\u9fff]{2,}", value)
    terms = [term.replace('"', "") for term in ascii_terms + cjk_terms]
    return " OR ".join(f'"{term}"' for term in terms[:16])


def _excerpt(text: str, query: str, limit: int = 620) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    lowered = compact.casefold()
    positions = [lowered.find(term.casefold()) for term in re.findall(r"[\w-]{3,}", query)]
    positions = [position for position in positions if position >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - limit // 4)
    end = min(len(compact), start + limit)
    prefix = "..." if start else ""
    suffix = "..." if end < len(compact) else ""
    return f"{prefix}{compact[start:end].strip()}{suffix}"


class SiliconFlowEmbedder:
    """Generate query embeddings without loading a model on the small VM."""

    def __init__(self) -> None:
        self.api_key = os.getenv("SILICONFLOW_API_KEY", "").strip()
        self.base_url = os.getenv(
            "SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"
        ).strip().rstrip("/")
        self.model = os.getenv("KNOWLEDGE_EMBEDDING_MODEL", "BAAI/bge-m3").strip()
        self.timeout = float(os.getenv("KNOWLEDGE_EMBEDDING_TIMEOUT_SECONDS", "5"))
        self._client: httpx.Client | None = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def embed(self, text: str) -> list[float] | None:
        if not self.available:
            return None
        with self._lock:
            if self._client is None:
                self._client = httpx.Client(
                    base_url=self.base_url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=self.timeout,
                )
        response = self._client.post(
            "/embeddings",
            json={"model": self.model, "input": [text], "encoding_format": "float"},
        )
        response.raise_for_status()
        data = response.json().get("data") or []
        if not data:
            raise RuntimeError("SiliconFlow embedding response is empty")
        vector = [float(value) for value in data[0].get("embedding") or []]
        if not vector:
            raise RuntimeError("SiliconFlow embedding vector is empty")
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


@dataclass(frozen=True)
class SearchTiming:
    embedding_seconds: float
    retrieval_seconds: float
    total_seconds: float


class KnowledgeBase:
    def __init__(
        self,
        database_path: Path | str | None = None,
        *,
        embedder: Any | None = None,
    ) -> None:
        self.database_path = Path(
            database_path
            or os.getenv("KNOWLEDGE_DB_PATH", "").strip()
            or DEFAULT_DB_PATH
        )
        self.embedder = embedder if embedder is not None else SiliconFlowEmbedder()

    @property
    def available(self) -> bool:
        return self.database_path.is_file()

    def statistics(self) -> dict[str, Any]:
        if not self.available:
            return {"available": False, "database_path": str(self.database_path)}
        with connect_database(self.database_path, load_vectors=False) as connection:
            papers = connection.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
            chunks = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            pages = connection.execute(
                "SELECT COALESCE(SUM(page_count), 0) FROM papers"
            ).fetchone()[0]
            methods = {
                row["extraction_method"]: row["count"]
                for row in connection.execute(
                    "SELECT extraction_method, COUNT(*) AS count FROM papers GROUP BY extraction_method"
                )
            }
        return {
            "available": True,
            "database_path": str(self.database_path),
            "papers": int(papers),
            "chunks": int(chunks),
            "pages": int(pages),
            "extraction_methods": methods,
        }

    def _keyword_candidates(
        self, connection: sqlite3.Connection, query: str, limit: int
    ) -> list[int]:
        expression = _fts_query(query)
        if not expression:
            return []
        try:
            rows = connection.execute(
                """
                SELECT rowid
                FROM chunks_fts
                WHERE chunks_fts MATCH ?
                ORDER BY bm25(chunks_fts, 1.0, 2.5, 1.5)
                LIMIT ?
                """,
                (expression, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            logger.warning("FTS query could not be parsed", exc_info=True)
            return []
        return [int(row[0]) for row in rows]

    @staticmethod
    def _vector_candidates(
        connection: sqlite3.Connection, vector: list[float], limit: int
    ) -> list[int]:
        rows = connection.execute(
            """
            SELECT rowid, distance
            FROM chunk_vectors
            WHERE embedding MATCH ? AND k = ?
            ORDER BY distance
            """,
            (json.dumps(vector, separators=(",", ":")), limit),
        ).fetchall()
        return [int(row[0]) for row in rows]

    @staticmethod
    def _paper_vector_candidates(
        connection: sqlite3.Connection, vector: list[float], limit: int
    ) -> list[int]:
        """Rank papers by title/abstract, returning their overview chunk IDs."""
        rows = connection.execute(
            """
            SELECT pv.rowid AS paper_id, c.id AS chunk_id
            FROM paper_vectors pv
            JOIN chunks c ON c.paper_id = pv.rowid AND c.section = 'paper_overview'
            WHERE pv.embedding MATCH ? AND k = ?
            ORDER BY pv.distance
            """,
            (json.dumps(vector, separators=(",", ":")), limit),
        ).fetchall()
        return [int(row["chunk_id"]) for row in rows]

    @staticmethod
    def _diversify_candidates(
        connection: sqlite3.Connection, chunk_ids: list[int], max_per_paper: int = 2
    ) -> list[int]:
        if not chunk_ids:
            return []
        placeholders = ",".join("?" for _ in chunk_ids)
        rows = connection.execute(
            f"SELECT id, paper_id FROM chunks WHERE id IN ({placeholders})", chunk_ids
        ).fetchall()
        paper_by_chunk = {int(row["id"]): int(row["paper_id"]) for row in rows}
        counts: dict[int, int] = {}
        result = []
        for chunk_id in chunk_ids:
            paper_id = paper_by_chunk.get(chunk_id)
            if paper_id is None or counts.get(paper_id, 0) >= max_per_paper:
                continue
            counts[paper_id] = counts.get(paper_id, 0) + 1
            result.append(chunk_id)
        return result

    @staticmethod
    def _fuse_rankings_by_paper(
        connection: sqlite3.Connection,
        rankings: Iterable[list[int]],
        weights: Iterable[float] | None = None,
    ) -> list[tuple[int, float]]:
        ranking_list = list(rankings)
        weight_list = list(weights) if weights is not None else [1.0] * len(ranking_list)
        if len(weight_list) != len(ranking_list):
            raise ValueError("Each ranking must have one fusion weight")
        chunk_ids = list(dict.fromkeys(chunk_id for ranking in ranking_list for chunk_id in ranking))
        if not chunk_ids:
            return []
        placeholders = ",".join("?" for _ in chunk_ids)
        rows = connection.execute(
            f"SELECT id, paper_id FROM chunks WHERE id IN ({placeholders})", chunk_ids
        ).fetchall()
        paper_by_chunk = {int(row["id"]): int(row["paper_id"]) for row in rows}
        scores: dict[int, float] = {}
        representative: dict[int, int] = {}
        for ranking, weight in zip(ranking_list, weight_list):
            seen_papers: set[int] = set()
            for rank, chunk_id in enumerate(ranking, start=1):
                paper_id = paper_by_chunk.get(chunk_id)
                if paper_id is None or paper_id in seen_papers:
                    continue
                seen_papers.add(paper_id)
                scores[paper_id] = scores.get(paper_id, 0.0) + weight / (60 + rank)
                representative.setdefault(paper_id, chunk_id)
        ranked_papers = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return [(representative[paper_id], score) for paper_id, score in ranked_papers]

    def search(self, query_text: str, *, limit: int = 5) -> dict[str, Any]:
        query = _normalize_query(query_text)
        if not query:
            return {"success": False, "error": "查询内容不能为空", "result": []}
        if len(query) > 400:
            return {"success": False, "error": "查询内容不能超过400个字符", "result": []}
        if not self.available:
            return {
                "success": False,
                "error": "郭雷论文知识库尚未部署",
                "database_path": str(self.database_path),
                "result": [],
            }

        reviewed = lookup_formula(self.database_path, query)
        if reviewed is not None:
            return reviewed

        started = time.perf_counter()
        vector: list[float] | None = None
        embedding_error = ""
        embedding_started = time.perf_counter()
        try:
            vector = self.embedder.embed(query) if self.embedder is not None else None
        except Exception as exc:  # FTS still provides a useful fallback
            embedding_error = type(exc).__name__
            logger.warning("Knowledge query embedding failed; using keyword search", exc_info=True)
        embedding_seconds = time.perf_counter() - embedding_started

        retrieval_started = time.perf_counter()
        with connect_database(self.database_path, load_vectors=vector is not None) as connection:
            keyword_ids = self._keyword_candidates(connection, query, 120)
            vector_ids: list[int] = []
            paper_vector_ids: list[int] = []
            if vector is not None:
                try:
                    vector_ids = self._vector_candidates(connection, vector, 240)
                    paper_vector_ids = self._paper_vector_candidates(connection, vector, 80)
                except sqlite3.Error:
                    logger.warning("Vector lookup failed; using keyword search", exc_info=True)

            fused = self._fuse_rankings_by_paper(
                connection,
                [keyword_ids, paper_vector_ids, vector_ids],
                weights=[1.8, 2.4, 1.0],
            )
            if not fused:
                title_rows = connection.execute(
                    """
                    SELECT c.id
                    FROM chunks c JOIN papers p ON p.id = c.paper_id
                    WHERE lower(p.title) LIKE lower(?)
                    ORDER BY p.year, c.page_start
                    LIMIT 20
                    """,
                    (f"%{query}%",),
                ).fetchall()
                fused = [(int(row[0]), 0.0) for row in title_rows]

            # A paper-level hit is not a passage-level hit. Re-select within leading
            # papers for precise questions; avoid returning only title/reference chunks.
            if any(term in query.casefold() for term in ('公式', '定理', '证明', '常数', 'theorem', 'proof', 'constant')):
                improved = []
                for representative, score in fused[:max(limit * 3, limit)]:
                    paper = connection.execute('SELECT paper_id FROM chunks WHERE id=?', (representative,)).fetchone()
                    candidates = connection.execute('SELECT id,section,text FROM chunks WHERE paper_id=?', (paper[0],)).fetchall()
                    terms = re.findall(r'[a-z]{4,}', query.casefold())
                    if '定理' in query or '常数' in query: terms += ['theorem', 'critical']
                    if '证明' in query: terms += ['proof']
                    def passage_score(row):
                        text = row['text'].casefold()
                        value = sum(min(text.count(term), 3) for term in set(terms))
                        value -= 4 if row['section'] == 'paper_overview' else 0
                        value -= 8 if 'references' in text else 0
                        return value
                    best = max(candidates, key=passage_score)
                    improved.append((int(best['id']), score))
                fused = improved + fused[max(limit * 3, limit):]
            selected_ids = [chunk_id for chunk_id, _ in fused[: max(limit * 3, limit)]]
            score_map = dict(fused)
            records: list[dict[str, Any]] = []
            if selected_ids:
                placeholders = ",".join("?" for _ in selected_ids)
                rows = connection.execute(
                    f"""
                    SELECT c.id, c.page_start, c.page_end, c.section, c.text,
                           c.extraction_method, c.ocr_confidence,
                           p.title, p.year, p.authors, p.doi, p.official_url,
                           p.stored_path
                    FROM chunks c JOIN papers p ON p.id = c.paper_id
                    WHERE c.id IN ({placeholders})
                    """,
                    selected_ids,
                ).fetchall()
                by_id = {int(row["id"]): row for row in rows}
                seen: set[tuple[str, int]] = set()
                for chunk_id in selected_ids:
                    row = by_id.get(chunk_id)
                    if row is None:
                        continue
                    dedupe_key = (str(row["title"]), int(row["page_start"]))
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    records.append(
                        {
                            "chunk_id": chunk_id,
                            "score": round(float(score_map.get(chunk_id, 0.0)), 6),
                            "title": row["title"],
                            "year": row["year"],
                            "authors": row["authors"],
                            "page_start": row["page_start"],
                            "page_end": row["page_end"],
                            "section": row["section"],
                            "doi": row["doi"],
                            "official_url": row["official_url"],
                            "stored_path": row["stored_path"],
                            "extraction_method": row["extraction_method"],
                            "ocr_confidence": row["ocr_confidence"],
                            "excerpt": _excerpt(str(row["text"]), query),
                        }
                    )
                    if len(records) >= limit:
                        break

        retrieval_seconds = time.perf_counter() - retrieval_started
        total_seconds = time.perf_counter() - started
        warning = ""
        if any(item["extraction_method"] == "ocr" for item in records):
            warning = "部分证据来自扫描件OCR；涉及精确公式时请核对所标页码的原PDF。"
        if any(term in query.casefold() for term in ('公式', '定理', '证明', '常数', 'theorem', 'proof', 'constant')):
            warning = '这些原始片段尚未逐式核验；文字层也可能丢失根号、分数线或不等号，不能据此断言精确公式。'
        if embedding_error:
            warning = (warning + " 当前语义检索不可用，已降级为关键词检索。").strip()

        citations = [
            f"[{index}] {item['title']} ({item['year']}), p.{item['page_start']}"
            for index, item in enumerate(records, start=1)
        ]
        evidence_status, matched_terms = assess_relevance(query, records)
        return {
            "success": bool(records),
            "query": query,
            "evidence_status": evidence_status,
            "relevance_terms": matched_terms,
            "count": len(records),
            "summary": "请仅依据以下论文片段回答，并在结论后保留[1]、[2]形式的来源编号。",
            "warning": warning,
            "citations": citations,
            "timing_seconds": {
                "embedding": round(embedding_seconds, 4),
                "retrieval": round(retrieval_seconds, 4),
                "total": round(total_seconds, 4),
            },
            "result": records,
        }
