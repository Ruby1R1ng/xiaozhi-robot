"""Build a page-cited SQLite knowledge base from the Guo Lei paper archive."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

import httpx
import sqlite_vec


SAMPLE_MARKERS = (
    "Consistency of parameter estimates for discrete-time linear systems",
    "A robust stochastic adaptive controller",
    "The Astrom-Wittenmark self-tuning regulator revisited",
    "A note on continuous-time ELS",
    "A limit to the capability of feedback",
    "Synchronization of multi-agent systems without connectivity assumption",
    "Some results on adaptive nonlinear stabilization",
    "Controllability of Nash Equilibrium in Game-Based Control Systems",
    "Global EPD regulation of uncertain nonlinear systems",
    "Estimation and Prediction for Large Models with Saturated Output Observation",
)


@dataclass
class PaperManifest:
    sequence: str
    archive_path: str
    stored_path: str
    sha256: str
    title: str
    year: int
    page_count: int
    text_char_count: int
    extraction_class: str


def _run(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, check=True, capture_output=True)


def _pdfinfo_pages(pdf_path: Path) -> int:
    output = _run(["pdfinfo", str(pdf_path)]).stdout.decode("utf-8", errors="replace")
    match = re.search(r"^Pages:\s+(\d+)", output, flags=re.MULTILINE)
    if not match:
        raise RuntimeError(f"Could not determine page count: {pdf_path}")
    return int(match.group(1))


def extract_pdf_pages(pdf_path: Path) -> list[str]:
    output = _run(
        ["pdftotext", "-enc", "UTF-8", "-layout", str(pdf_path), "-"]
    ).stdout.decode("utf-8", errors="replace")
    pages = output.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    expected = _pdfinfo_pages(pdf_path)
    while len(pages) < expected:
        pages.append("")
    return pages[:expected]


def _clean_page(text: str) -> str:
    value = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"(?<=[A-Za-z])-\n(?=[a-z])", "", value)
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", value):
        compact = re.sub(r"\s*\n\s*", " ", paragraph)
        compact = re.sub(r"[ \t]+", " ", compact).strip()
        if compact:
            paragraphs.append(compact)
    return "\n\n".join(paragraphs)


def _classify_pages(pages: list[str]) -> tuple[str, int]:
    cleaned = [_clean_page(page) for page in pages]
    character_count = sum(len(page) for page in cleaned)
    useful_pages = sum(len(page) >= 120 for page in cleaned)
    if not pages or character_count < max(500, len(pages) * 80):
        return "image_only", character_count
    if useful_pages < max(1, len(pages) // 2):
        return "sparse_text", character_count
    return "text_layer", character_count


def _metadata_from_filename(filename: str) -> tuple[str, int, str]:
    basename = Path(filename).name
    stem = re.sub(r"\.pdf$", "", basename, flags=re.IGNORECASE).strip()
    sequence_match = re.match(r"\s*(\d+(?:\.[a-z])?)", stem, flags=re.IGNORECASE)
    sequence = sequence_match.group(1) if sequence_match else "0"
    title_match = re.search(r"[“\"]\s*(.+?)\s*[”\"]", stem)
    if title_match:
        title = title_match.group(1)
    else:
        title = re.sub(r"^\s*\d+(?:\.[a-z])?\.?\s*", "", stem, flags=re.IGNORECASE)
        title = title.split(",", 1)[0]
    title = re.sub(r"\s+", " ", title).strip(" .“”\"")
    years = [
        int(value)
        for value in re.findall(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", stem)
        if int(value) >= 1980
    ]
    # Bibliographic filenames commonly contain page ranges before the publication year.
    year = years[-1] if years else 0
    return title, year, sequence


def _safe_sequence(sequence: str, fallback: int) -> str:
    normalized = re.sub(r"[^0-9A-Za-z]+", "_", sequence).strip("_")
    return normalized if normalized and normalized != "0" else f"x{fallback:03d}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _decoded_zip_name(info: zipfile.ZipInfo) -> str:
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("gb18030")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def prepare_archive(archive_path: Path, output_root: Path, *, sample: bool) -> list[PaperManifest]:
    papers_dir = output_root / "papers"
    ocr_input_dir = output_root / "ocr_input"
    papers_dir.mkdir(parents=True, exist_ok=True)
    ocr_input_dir.mkdir(parents=True, exist_ok=True)
    manifests: list[PaperManifest] = []
    with zipfile.ZipFile(archive_path) as archive:
        entries = [
            (info, _decoded_zip_name(info))
            for info in archive.infolist()
            if not info.is_dir() and info.filename.casefold().endswith(".pdf")
        ]
        if sample:
            entries = [
                (info, decoded_name)
                for info, decoded_name in entries
                if any(marker.casefold() in decoded_name.casefold() for marker in SAMPLE_MARKERS)
            ]
            missing = [
                marker
                for marker in SAMPLE_MARKERS
                if not any(marker.casefold() in decoded_name.casefold() for _, decoded_name in entries)
            ]
            if missing:
                raise RuntimeError(f"Sample papers not found in archive: {missing}")

        for fallback, (info, decoded_name) in enumerate(entries, start=1):
            title, year, sequence = _metadata_from_filename(decoded_name)
            output_name = f"paper_{_safe_sequence(sequence, fallback)}_{year or 'unknown'}.pdf"
            destination = papers_dir / output_name
            with archive.open(info) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)
            pages = extract_pdf_pages(destination)
            extraction_class, character_count = _classify_pages(pages)
            if extraction_class != "text_layer":
                shutil.copy2(destination, ocr_input_dir / output_name)
            manifests.append(
                PaperManifest(
                    sequence=sequence,
                    archive_path=decoded_name,
                    stored_path=destination.relative_to(output_root).as_posix(),
                    sha256=_sha256(destination),
                    title=title,
                    year=year,
                    page_count=len(pages),
                    text_char_count=character_count,
                    extraction_class=extraction_class,
                )
            )
            print(
                f"prepared {len(manifests):03d}/{len(entries):03d} "
                f"{extraction_class:12s} {year:4d} {title}",
                flush=True,
            )

    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps([asdict(item) for item in manifests], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifests


def _strip_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _normalized_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def crossref_metadata(title: str) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "query.title": title,
            "rows": 1,
            "select": "DOI,title,URL,abstract,published,author,container-title",
        }
    )
    request = urllib.request.Request(
        f"https://api.crossref.org/works?{query}",
        headers={"User-Agent": "GuoLeiKnowledgeBase/1.0 (private scholarly index)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            items = json.load(response).get("message", {}).get("items", [])
    except Exception as exc:
        print(f"Crossref lookup failed for {title}: {type(exc).__name__}", file=sys.stderr)
        return {}
    if not items:
        return {}
    item = items[0]
    matched_title = " ".join(item.get("title") or [])
    similarity = SequenceMatcher(
        None, _normalized_title(title), _normalized_title(matched_title)
    ).ratio()
    if similarity < 0.78:
        return {}
    authors = []
    for author in item.get("author") or []:
        name = " ".join(part for part in (author.get("given"), author.get("family")) if part)
        if name:
            authors.append(name)
    published_year = 0
    for field in ("published-print", "published-online", "published", "issued"):
        date_parts = (item.get(field) or {}).get("date-parts") or []
        if date_parts and date_parts[0]:
            try:
                published_year = int(date_parts[0][0])
            except (TypeError, ValueError):
                published_year = 0
            if published_year:
                break
    return {
        "doi": item.get("DOI") or "",
        "official_url": item.get("URL") or "",
        "abstract": _strip_html(item.get("abstract") or ""),
        "authors": ", ".join(authors),
        "venue": " ".join(item.get("container-title") or []),
        "crossref_title": matched_title,
        "match_similarity": round(similarity, 4),
        "year": published_year,
    }


def _mineru_block_text(block: dict[str, Any]) -> str:
    block_type = str(block.get("type") or block.get("category_type") or "").casefold()
    candidates = (
        block.get("text"),
        block.get("content"),
        block.get("latex"),
        block.get("html"),
    )
    text = next((value for value in candidates if isinstance(value, str) and value.strip()), "")
    if not text:
        return ""
    if "equation" in block_type or "formula" in block_type:
        return f"[Formula] {text.strip()}"
    if "table" in block_type:
        return f"[Table] {text.strip()}"
    return text.strip()


def load_mineru_pages(ocr_root: Path, pdf_path: Path, page_count: int) -> list[str] | None:
    matches = [
        path
        for path in ocr_root.rglob("*_content_list.json")
        if pdf_path.stem.casefold() in str(path).casefold()
    ]
    if not matches:
        return None
    data = json.loads(matches[0].read_text(encoding="utf-8"))
    pages: list[list[str]] = [[] for _ in range(page_count)]
    if isinstance(data, dict):
        data = data.get("content_list") or data.get("data") or []
    for block in data if isinstance(data, list) else []:
        if not isinstance(block, dict):
            continue
        page_index = block.get("page_idx", block.get("page_id", block.get("page", 0)))
        try:
            page_index = int(page_index)
        except (TypeError, ValueError):
            page_index = 0
        if page_index >= page_count and 1 <= page_index <= page_count:
            page_index -= 1
        if not 0 <= page_index < page_count:
            continue
        text = _mineru_block_text(block)
        if text:
            pages[page_index].append(text)
    result = ["\n\n".join(parts) for parts in pages]
    minimum_characters = max(80, page_count * 40)
    return result if sum(len(page) for page in result) >= minimum_characters else None


def _split_text(text: str, *, target: int = 1500, overlap: int = 220) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + target)
        if end < len(text):
            boundary = max(
                text.rfind(". ", start + target // 2, end),
                text.rfind("; ", start + target // 2, end),
                text.rfind("\n\n", start + target // 2, end),
            )
            if boundary > start:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def _connect_writable(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.enable_load_extension(True)
    sqlite_vec.load(connection)
    connection.enable_load_extension(False)
    return connection


def _create_schema(connection: sqlite3.Connection, embedding_dimension: int) -> None:
    connection.executescript(
        f"""
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE papers (
            id INTEGER PRIMARY KEY,
            sequence TEXT NOT NULL,
            archive_path TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            title TEXT NOT NULL,
            year INTEGER NOT NULL,
            authors TEXT NOT NULL DEFAULT '',
            venue TEXT NOT NULL DEFAULT '',
            doi TEXT NOT NULL DEFAULT '',
            official_url TEXT NOT NULL DEFAULT '',
            abstract TEXT NOT NULL DEFAULT '',
            extraction_method TEXT NOT NULL,
            page_count INTEGER NOT NULL,
            text_char_count INTEGER NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY,
            paper_id INTEGER NOT NULL REFERENCES papers(id),
            page_start INTEGER NOT NULL,
            page_end INTEGER NOT NULL,
            section TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL,
            context_text TEXT NOT NULL,
            extraction_method TEXT NOT NULL,
            ocr_confidence REAL
        );
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            text, title, abstract,
            tokenize='unicode61 remove_diacritics 2'
        );
        CREATE VIRTUAL TABLE chunk_vectors USING vec0(embedding float[{embedding_dimension}]);
        CREATE VIRTUAL TABLE paper_vectors USING vec0(embedding float[{embedding_dimension}]);
        CREATE INDEX chunks_paper_page ON chunks(paper_id, page_start);
        CREATE INDEX papers_sha256 ON papers(sha256);
        """
    )


class LocalEmbedder:
    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.model = SentenceTransformer(model_name, trust_remote_code=True)

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(
            texts,
            batch_size=16,
            show_progress_bar=True,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return vectors.astype("float32").tolist()


class SiliconFlowBatchEmbedder:
    """Build corpus embeddings with the same provider used by the server."""

    def __init__(self, model_name: str, cache_path: Path) -> None:
        self.model_name = model_name
        self.api_key = os.getenv("SILICONFLOW_API_KEY", "").strip()
        if not self.api_key:
            raise RuntimeError("SILICONFLOW_API_KEY is required for siliconflow embedding")
        self.base_url = os.getenv(
            "SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"
        ).strip().rstrip("/")
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=60,
        )
        self.cache = sqlite3.connect(cache_path)
        self.cache.execute(
            "CREATE TABLE IF NOT EXISTS embeddings "
            "(cache_key TEXT PRIMARY KEY, dimension INTEGER NOT NULL, vector BLOB NOT NULL)"
        )
        self.cache.commit()

    def _cache_key(self, text: str) -> str:
        material = f"{self.model_name}\n{text}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    def _cached(self, cache_key: str) -> list[float] | None:
        row = self.cache.execute(
            "SELECT dimension, vector FROM embeddings WHERE cache_key = ?", (cache_key,)
        ).fetchone()
        if row is None:
            return None
        dimension, payload = int(row[0]), bytes(row[1])
        return list(struct.unpack(f"<{dimension}f", payload))

    def _store_cached(self, cache_key: str, vector: list[float]) -> None:
        payload = struct.pack(f"<{len(vector)}f", *vector)
        self.cache.execute(
            "INSERT OR REPLACE INTO embeddings(cache_key, dimension, vector) VALUES (?, ?, ?)",
            (cache_key, len(vector), sqlite3.Binary(payload)),
        )

    def encode(self, texts: list[str]) -> list[list[float]]:
        result: list[list[float]] = []
        batch_size = 32
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            keys = [self._cache_key(text) for text in batch]
            cached = [self._cached(key) for key in keys]
            if all(vector is not None for vector in cached):
                result.extend(vector for vector in cached if vector is not None)
                print(
                    f"embedded {min(start + len(batch), len(texts)):05d}/{len(texts):05d} cached",
                    flush=True,
                )
                continue
            missing_positions = [index for index, vector in enumerate(cached) if vector is None]
            request_inputs = [batch[index] for index in missing_positions]
            last_error: Exception | None = None
            for attempt in range(4):
                try:
                    response = self.client.post(
                        "/embeddings",
                        json={
                            "model": self.model_name,
                            "input": request_inputs,
                            "encoding_format": "float",
                        },
                    )
                    response.raise_for_status()
                    rows = sorted(response.json().get("data") or [], key=lambda row: row["index"])
                    if len(rows) != len(request_inputs):
                        raise RuntimeError("SiliconFlow returned an incomplete embedding batch")
                    batch_vectors = list(cached)
                    for position, row in zip(missing_positions, rows):
                        vector = [float(value) for value in row.get("embedding") or []]
                        if not vector:
                            raise RuntimeError("SiliconFlow returned an empty embedding vector")
                        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
                        normalized = [value / norm for value in vector]
                        batch_vectors[position] = normalized
                        self._store_cached(keys[position], normalized)
                    self.cache.commit()
                    result.extend(vector for vector in batch_vectors if vector is not None)
                    break
                except (httpx.HTTPError, RuntimeError, KeyError) as exc:
                    last_error = exc
                    if attempt == 3:
                        raise
                    time.sleep(2**attempt)
            print(
                f"embedded {min(start + len(batch), len(texts)):05d}/{len(texts):05d}",
                flush=True,
            )
            del last_error
        return result


def build_database(
    output_root: Path,
    *,
    ocr_root: Path,
    database_path: Path,
    model_name: str,
    embedding_provider: str,
) -> dict[str, Any]:
    manifests = [PaperManifest(**item) for item in json.loads((output_root / "manifest.json").read_text(encoding="utf-8"))]
    metadata_cache_path = output_root / "metadata_cache.json"
    try:
        metadata_cache = json.loads(metadata_cache_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        metadata_cache = {}
    paper_payloads = []
    missing_ocr = []
    for index, manifest in enumerate(manifests, start=1):
        pdf_path = output_root / manifest.stored_path
        pages = extract_pdf_pages(pdf_path)
        extraction_method = "text_layer"
        if manifest.extraction_class != "text_layer":
            ocr_pages = load_mineru_pages(ocr_root, pdf_path, manifest.page_count)
            if ocr_pages is None:
                missing_ocr.append(str(pdf_path))
                continue
            pages = ocr_pages
            extraction_method = "ocr"
        cleaned_pages = [_clean_page(page) for page in pages]
        metadata_key = _normalized_title(manifest.title)
        if metadata_key in metadata_cache:
            metadata = metadata_cache[metadata_key]
        else:
            metadata = crossref_metadata(manifest.title)
            metadata_cache[metadata_key] = metadata
            metadata_cache_path.write_text(
                json.dumps(metadata_cache, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            time.sleep(0.05)
        paper_payloads.append((manifest, metadata, extraction_method, cleaned_pages))
        print(f"loaded {index:03d}/{len(manifests):03d} {extraction_method:10s} {manifest.title}")
    if missing_ocr:
        joined = "\n".join(missing_ocr)
        raise RuntimeError(f"MinerU output is missing for scanned papers:\n{joined}")

    contexts = []
    chunk_payloads = []
    for paper_index, (manifest, metadata, extraction_method, pages) in enumerate(paper_payloads, start=1):
        paper_year = int(metadata.get("year") or manifest.year or 0)
        overview_text = "\n\n".join(
            part
            for part in (
                f"Title: {manifest.title}",
                f"Abstract: {metadata.get('abstract', '')}" if metadata.get("abstract") else "",
                pages[0][:1200] if pages else "",
            )
            if part
        )
        if overview_text:
            overview_embedding_text = "\n".join(
                part
                for part in (
                    f"Paper title: {manifest.title}",
                    f"Abstract: {metadata.get('abstract', '')}" if metadata.get("abstract") else "",
                )
                if part
            )
            overview_context = (
                f"Paper overview: {manifest.title}. Year: {paper_year}. Page: 1. "
                f"Source type: {extraction_method}.\n{overview_embedding_text}"
            )
            contexts.append(overview_context)
            chunk_payloads.append(
                (paper_index, 1, 1, "paper_overview", overview_text, overview_context, extraction_method)
            )
        for page_number, page in enumerate(pages, start=1):
            for text in _split_text(page):
                context = (
                    f"Paper: {manifest.title}. Year: {paper_year}. "
                    f"Page: {page_number}. Source type: {extraction_method}.\n{text}"
                )
                contexts.append(context)
                chunk_payloads.append(
                    (paper_index, page_number, page_number, "", text, context, extraction_method)
                )
    if not contexts:
        raise RuntimeError("No searchable chunks were extracted")

    embedder = (
        SiliconFlowBatchEmbedder(model_name, output_root / "embedding_cache.sqlite3")
        if embedding_provider == "siliconflow"
        else LocalEmbedder(model_name)
    )
    vectors = embedder.encode(contexts)
    dimension = len(vectors[0])
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if database_path.exists():
        database_path.unlink()
    with _connect_writable(database_path) as connection:
        _create_schema(connection, dimension)
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            [
                ("embedding_model", model_name),
                ("embedding_dimension", str(dimension)),
                ("created_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
            ],
        )
        for paper_id, (manifest, metadata, extraction_method, pages) in enumerate(paper_payloads, start=1):
            paper_year = int(metadata.get("year") or manifest.year or 0)
            connection.execute(
                """
                INSERT INTO papers(
                    id, sequence, archive_path, stored_path, sha256, title, year,
                    authors, venue, doi, official_url, abstract, extraction_method,
                    page_count, text_char_count, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_id, manifest.sequence, manifest.archive_path, manifest.stored_path,
                    manifest.sha256, manifest.title, paper_year,
                    metadata.get("authors", ""), metadata.get("venue", ""),
                    metadata.get("doi", ""), metadata.get("official_url", ""),
                    metadata.get("abstract", ""), extraction_method, len(pages),
                    sum(len(page) for page in pages), json.dumps(metadata, ensure_ascii=False),
                ),
            )
        for chunk_id, (payload, vector) in enumerate(zip(chunk_payloads, vectors), start=1):
            paper_id, page_start, page_end, section, text, context, extraction_method = payload
            cursor = connection.execute(
                """
                INSERT INTO chunks(
                    id, paper_id, page_start, page_end, section, text, context_text,
                    extraction_method, ocr_confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk_id, paper_id, page_start, page_end, section, text, context,
                    extraction_method, None if extraction_method == "text_layer" else 0.75,
                ),
            )
            del cursor
            paper = paper_payloads[paper_id - 1]
            manifest, metadata = paper[0], paper[1]
            connection.execute(
                "INSERT INTO chunks_fts(rowid, text, title, abstract) VALUES (?, ?, ?, ?)",
                (chunk_id, text, manifest.title, metadata.get("abstract", "")),
            )
            connection.execute(
                "INSERT INTO chunk_vectors(rowid, embedding) VALUES (?, ?)",
                (chunk_id, json.dumps(vector, separators=(",", ":"))),
            )
            if section == "paper_overview":
                connection.execute(
                    "INSERT INTO paper_vectors(rowid, embedding) VALUES (?, ?)",
                    (paper_id, json.dumps(vector, separators=(",", ":"))),
                )
        connection.commit()

    result = {
        "papers": len(paper_payloads),
        "chunks": len(chunk_payloads),
        "pages": sum(len(item[3]) for item in paper_payloads),
        "ocr_papers": sum(item[2] == "ocr" for item in paper_payloads),
        "text_layer_papers": sum(item[2] == "text_layer" for item in paper_payloads),
        "embedding_model": model_name,
        "embedding_provider": embedding_provider,
        "embedding_dimension": dimension,
        "database_path": str(database_path),
    }
    (output_root / "build_report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="Extract and classify papers")
    prepare.add_argument("--archive", type=Path, required=True)
    prepare.add_argument("--output", type=Path, default=Path("data/guolei"))
    prepare.add_argument("--sample", action="store_true")

    build = subparsers.add_parser("build", help="Build the searchable SQLite database")
    build.add_argument("--output", type=Path, default=Path("data/guolei"))
    build.add_argument("--ocr-root", type=Path, default=Path("data/guolei/ocr"))
    build.add_argument("--database", type=Path, default=Path("data/guolei/knowledge.sqlite3"))
    build.add_argument("--model", default="BAAI/bge-m3")
    build.add_argument(
        "--embedding-provider",
        choices=("local", "siliconflow"),
        default="local",
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    if args.command == "prepare":
        manifests = prepare_archive(args.archive.resolve(), args.output.resolve(), sample=args.sample)
        counts: dict[str, int] = {}
        for item in manifests:
            counts[item.extraction_class] = counts.get(item.extraction_class, 0) + 1
        print(json.dumps({"papers": len(manifests), "classes": counts}, ensure_ascii=False, indent=2))
    elif args.command == "build":
        result = build_database(
            args.output.resolve(),
            ocr_root=args.ocr_root.resolve(),
            database_path=args.database.resolve(),
            model_name=args.model,
            embedding_provider=args.embedding_provider,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
