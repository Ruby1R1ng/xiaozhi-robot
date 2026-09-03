"""Print raw keyword/vector ranks for benchmark misses."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import knowledge_base as module


CASES = (
    ("鲁棒随机自适应控制器", "A robust stochastic adaptive controller"),
    ("Astrom-Wittenmark self-tuning regulator and ELS trackers", "Astrom-Wittenmark"),
    ("连续时间 ELS 方法", "continuous-time ELS"),
    ("自适应非线性镇定有哪些结果", "adaptive nonlinear stabilization"),
)


def main() -> None:
    database = Path(sys.argv[1] if len(sys.argv) > 1 else "data/guolei_full/knowledge.sqlite3")
    knowledge = module.KnowledgeBase(database)
    with module.connect_database(database) as connection:
        for query, target in CASES:
            vector = knowledge.embedder.embed(query)
            vector_rows = connection.execute(
                """
                SELECT p.title, c.section
                FROM chunk_vectors v
                JOIN chunks c ON c.id = v.rowid
                JOIN papers p ON p.id = c.paper_id
                WHERE v.embedding MATCH ? AND k = 500
                ORDER BY v.distance
                """,
                (json.dumps(vector, separators=(",", ":")),),
            ).fetchall()
            expression = module._fts_query(query)
            keyword_rows = (
                connection.execute(
                    """
                    SELECT p.title
                    FROM chunks_fts f
                    JOIN chunks c ON c.id = f.rowid
                    JOIN papers p ON p.id = c.paper_id
                    WHERE chunks_fts MATCH ?
                    ORDER BY bm25(chunks_fts, 1.0, 2.5, 1.5)
                    LIMIT 500
                    """,
                    (expression,),
                ).fetchall()
                if expression
                else []
            )
            payload = {
                "query": query,
                "target": target,
                "vector_rank": next(
                    (index for index, row in enumerate(vector_rows, 1) if target.casefold() in row["title"].casefold()),
                    None,
                ),
                "keyword_rank": next(
                    (index for index, row in enumerate(keyword_rows, 1) if target.casefold() in row["title"].casefold()),
                    None,
                ),
                "vector_top10": [row["title"] for row in vector_rows[:10]],
                "keyword_top10": [row["title"] for row in keyword_rows[:10]],
            }
            print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
