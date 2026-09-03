"""Benchmark the real 10-paper sample knowledge base."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from knowledge_base import KnowledgeBase


CASES = (
    ("离散时间线性系统参数估计的一致性", "Consistency of parameter estimates"),
    ("鲁棒随机自适应控制器", "A robust stochastic adaptive controller"),
    ("Astrom-Wittenmark self-tuning regulator and ELS trackers", "Astrom-Wittenmark"),
    ("连续时间 ELS 方法", "continuous-time ELS"),
    ("反馈能力存在什么极限", "limit to the capability of feedback"),
    ("无需连通性假设的多智能体同步", "Synchronization of multi-agent systems"),
    ("自适应非线性镇定有哪些结果", "adaptive nonlinear stabilization"),
    ("博弈控制系统纳什均衡的可控性", "Controllability of Nash Equilibrium"),
    ("没有全局标准型的不确定非线性系统 EPD 调节", "Global EPD regulation"),
    ("饱和输出观测下的大模型估计与预测", "Saturated Output Observation"),
)


class LocalQueryEmbedder:
    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name, trust_remote_code=True)

    def embed(self, text: str) -> list[float]:
        vector = self.model.encode(
            [text], normalize_embeddings=True, convert_to_numpy=True
        )[0]
        return vector.astype("float32").tolist()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * fraction))
    return ordered[index]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/guolei/knowledge.sqlite3"))
    parser.add_argument("--model", default="BAAI/bge-m3")
    parser.add_argument(
        "--embedding-provider",
        choices=("siliconflow", "local"),
        default="siliconflow",
    )
    parser.add_argument("--report", type=Path, default=Path("data/guolei/benchmark_report.json"))
    args = parser.parse_args()

    embedder = LocalQueryEmbedder(args.model) if args.embedding_provider == "local" else None
    knowledge = KnowledgeBase(args.database.resolve(), embedder=embedder)
    outcomes = []
    for query, expected in CASES:
        response = knowledge.search(query, limit=3)
        titles = [item["title"] for item in response.get("result", [])]
        matched = any(expected.casefold() in title.casefold() for title in titles)
        citations_valid = bool(titles) and all(
            item.get("page_start", 0) >= 1 and item.get("extraction_method")
            for item in response.get("result", [])
        )
        outcome = {
            "query": query,
            "expected": expected,
            "matched_top3": matched,
            "citations_valid": citations_valid,
            "top_titles": titles,
            "timing_seconds": response.get("timing_seconds", {}),
        }
        outcomes.append(outcome)
        print(json.dumps(outcome, ensure_ascii=False))

    retrieval_times = [item["timing_seconds"]["retrieval"] for item in outcomes]
    total_times = [item["timing_seconds"]["total"] for item in outcomes]
    recall = sum(item["matched_top3"] for item in outcomes) / len(outcomes)
    citation_rate = sum(item["citations_valid"] for item in outcomes) / len(outcomes)
    report = {
        "cases": len(outcomes),
        "top3_recall": round(recall, 4),
        "citation_valid_rate": round(citation_rate, 4),
        "retrieval_median_seconds": round(statistics.median(retrieval_times), 4),
        "retrieval_p95_seconds": round(percentile(retrieval_times, 0.95), 4),
        "total_median_seconds": round(statistics.median(total_times), 4),
        "total_p95_seconds": round(percentile(total_times, 0.95), 4),
        "acceptance": {
            "top3_recall_at_least_90_percent": recall >= 0.9,
            "citations_100_percent": citation_rate == 1.0,
            "retrieval_p95_under_1_second": percentile(retrieval_times, 0.95) < 1.0,
        },
        "outcomes": outcomes,
    }
    report["passed"] = all(report["acceptance"].values())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
