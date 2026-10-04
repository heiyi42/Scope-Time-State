"""
STSGraph Index Building

Features:
1. Read graph files
2. Build indexes for claims
3. Build indexes for events
4. Build indexes for scopes
5. Build indexes for Claim-derived States
6. Save index results

Data flow:
graphs → claim indexing → event indexing → scope indexing → save
"""

import sys
import json
import pickle
import asyncio
from pathlib import Path
from typing import Dict, List, Any, Optional

import nltk
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer
from nltk.tokenize import word_tokenize
from rank_bm25 import BM25Okapi
from rich.progress import (
    Progress, SpinnerColumn, TextColumn, BarColumn,
    TimeElapsedColumn, TimeRemainingColumn
)
from rich.console import Console

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sts.config import ExperimentConfig
from sts.providers.embeddings import EmbeddingProvider

console = Console()


def ensure_nltk_data():
    """Ensure NLTK data is downloaded"""
    try:
        nltk.data.find("tokenizers/punkt")
    except LookupError:
        nltk.download("punkt", quiet=True)

    try:
        nltk.data.find("corpora/stopwords")
    except LookupError:
        nltk.download("stopwords", quiet=True)


def tokenize(text: str, stemmer: PorterStemmer, stop_words: set) -> List[str]:
    """
    NLTK-based tokenization with stemming and stop word filtering

    Args:
        text: Text to tokenize
        stemmer: Stemmer
        stop_words: Set of stop words

    Returns:
        List of processed tokens
    """
    if not text:
        return []

    tokens = word_tokenize(text.lower())

    processed_tokens = [
        stemmer.stem(token)
        for token in tokens
        if token.isalpha() and len(token) >= 2 and token not in stop_words
    ]

    return processed_tokens


def build_claim_searchable_text(claim: Dict[str, Any]) -> str:
    """
    Build weighted searchable text for one STS Claim.

    Weighting strategy:
    - content: repeated 3 times (core information)
    - query_patterns: repeated 2 times (query patterns)
    - keywords and temporal/spatial fields: repeated 1 time

    Args:
        claim: Claim dictionary

    Returns:
        Searchable text
    """
    parts = []

    # Core content (highest weight)
    content = claim.get("content", "")
    if content:
        parts.extend([content] * 3)

    # Query patterns (medium weight)
    if claim.get("query_patterns"):
        query_text = " ".join(claim["query_patterns"])
        parts.extend([query_text] * 2)

    # Keywords
    keywords = claim.get("keywords") or []
    if keywords:
        if isinstance(keywords, list):
            parts.append(" ".join(keywords))
        else:
            parts.append(str(keywords))

    # Auxiliary information (lower weight)
    if claim.get("temporal"):
        parts.append(str(claim["temporal"]))
    if claim.get("spatial"):
        parts.append(str(claim["spatial"]))

    return " ".join(str(part) for part in parts if part)


def build_event_searchable_text(event: Dict[str, Any]) -> str:
    """
    Build searchable text for an event (with weighting)

    Weighting strategy:
    - subject: repeated 3 times (title has highest weight)
    - summary: repeated 2 times (summary has medium weight)
    - event: repeated 1 time (content has base weight)

    Args:
        event: Event dictionary

    Returns:
        Searchable text
    """
    parts = []

    # Title (highest weight)
    if event.get("subject"):
        parts.extend([event["subject"]] * 3)

    # Summary (medium weight)
    if event.get("summary"):
        parts.extend([event["summary"]] * 2)

    # Full content
    if event.get("event_description"):
        parts.append(event["event_description"])

    # Keywords
    if event.get("keywords"):
        if isinstance(event["keywords"], list):
            parts.append(" ".join(event["keywords"]))
        else:
            parts.append(str(event["keywords"]))

    return " ".join(str(part) for part in parts if part)


def build_scope_searchable_text(scope: Dict[str, Any]) -> str:
    """
    Build searchable text for a scope (with weighting)

    Weighting strategy:
    - title: repeated 3 times (title has highest weight)
    - keywords: repeated 2 times (keywords have medium weight)
    - summary: repeated 1 time (summary has base weight)

    Args:
        scope: Scope dictionary

    Returns:
        Searchable text
    """
    parts = []

    # Title (highest weight)
    if scope.get("title"):
        parts.extend([scope["title"]] * 3)

    # Keywords (medium weight)
    if scope.get("keywords"):
        keywords_text = " ".join(scope["keywords"])
        parts.extend([keywords_text] * 2)

    # Summary
    if scope.get("summary"):
        parts.append(scope["summary"])

    return " ".join(str(part) for part in parts if part)


def build_state_searchable_text(
    state: Dict[str, Any],
    claims: Optional[Dict[str, Any]] = None,
) -> str:
    """Build searchable text for a Claim-derived State."""
    parts = []
    if state.get("subject"):
        parts.append(str(state["subject"]))
    if state.get("dimension"):
        parts.extend([str(state["dimension"])] * 2)
    topic_terms = state.get("topic_terms") or []
    if topic_terms:
        topic_text = " ".join(str(term) for term in topic_terms)
        parts.extend([topic_text] * 2)
    if state.get("title"):
        parts.append(state["title"])
    if state.get("summary"):
        parts.append(state["summary"])
    if claims:
        for claim_id in state.get("representative_claim_ids", [])[:4]:
            claim = claims.get(claim_id, {})
            if claim.get("content"):
                parts.append(str(claim["content"]))
    if state.get("start_time"):
        parts.append(str(state["start_time"]))
    if state.get("end_time"):
        parts.append(str(state["end_time"]))
    return " ".join(str(part) for part in parts if part)


def build_bm25_index_for_single_conv(
    conv_id: int,
    data_dir: Path,
    bm25_save_dir: Path,
    stemmer: PorterStemmer,
    stop_words: set,
    skip_existing: bool = True
) -> tuple[bool, str]:
    """
    Build BM25 index for a single conversation's graph data

    Args:
        conv_id: Conversation ID
        data_dir: STSGraph data directory
        bm25_save_dir: BM25 index save directory
        stemmer: Stemmer
        stop_words: Set of stop words
        skip_existing: Whether to skip existing index files

    Returns:
        (success, status: "completed"/"skipped"/"failed")
    """
    try:
        # Check if output file already exists (checkpoint resume)
        output_path = bm25_save_dir / f"graph_bm25_index_conv_{conv_id}.pkl"
        if skip_existing and output_path.exists():
            try:
                with output_path.open("rb") as existing_file:
                    existing = pickle.load(existing_file)
                if any(
                    doc.get("type") == "state"
                    for doc in existing.get("docs", [])
                ):
                    return (True, "skipped")
            except (OSError, EOFError, pickle.UnpicklingError):
                pass

        graph_file = data_dir / f"graph_conv_{conv_id}.json"
        if not graph_file.exists():
            return (False, "failed")

        # Read graph data
        with open(graph_file, "r", encoding="utf-8") as f:
            graph = json.load(f)

        # ===== 1. Build index for claims =====
        claims = graph.get("claims", {})
        claim_corpus = []
        claim_docs = []

        for claim_id, claim_data in claims.items():
            claim_docs.append({
                "id": claim_id,
                "type": "claim",
                "data": claim_data
            })
            searchable_text = build_claim_searchable_text(claim_data)
            tokenized_text = tokenize(searchable_text, stemmer, stop_words)
            claim_corpus.append(tokenized_text)

        # ===== 2. Build index for events =====
        events = graph.get("events", {})
        event_corpus = []
        event_docs = []

        for event_id, event_data in events.items():
            event_docs.append({
                "id": event_id,
                "type": "event",
                "data": event_data
            })
            searchable_text = build_event_searchable_text(event_data)
            tokenized_text = tokenize(searchable_text, stemmer, stop_words)
            event_corpus.append(tokenized_text)

        # ===== 3. Build index for scopes =====
        scopes = graph.get("scopes", {})
        scope_corpus = []
        scope_docs = []

        for scope_id, scope_data in scopes.items():
            scope_docs.append({
                "id": scope_id,
                "type": "scope",
                "data": scope_data
            })
            searchable_text = build_scope_searchable_text(scope_data)
            tokenized_text = tokenize(searchable_text, stemmer, stop_words)
            scope_corpus.append(tokenized_text)

        # ===== 4. Build index for States =====
        states = graph.get("states", {})
        claims = graph.get("claims", {})
        state_corpus = []
        state_docs = []
        for state_id, state_data in states.items():
            state_docs.append({
                "id": state_id,
                "type": "state",
                "data": state_data,
            })
            searchable_text = build_state_searchable_text(
                state_data, claims
            )
            state_corpus.append(
                tokenize(searchable_text, stemmer, stop_words)
            )

        # ===== 5. Build unified BM25 index =====
        all_corpus = (
            claim_corpus + event_corpus + scope_corpus + state_corpus
        )
        all_docs = claim_docs + event_docs + scope_docs + state_docs

        if not all_corpus:
            console.print(f"  [yellow][!] Conversation {conv_id}: no documents, skipping index creation[/yellow]")
            return False

        bm25 = BM25Okapi(all_corpus)

        # ===== 6. Save index =====
        index_data = {
            "bm25": bm25,
            "docs": all_docs,
            "claim_count": len(claim_docs),
            "event_count": len(event_docs),
            "scope_count": len(scope_docs),
            "state_count": len(state_docs),
        }

        with open(output_path, "wb") as f:
            pickle.dump(index_data, f)

        return (True, "completed")

    except Exception as e:
        console.print(f"  [red][X] Conversation {conv_id}: BM25 index building failed - {e}[/red]")
        return (False, "failed")


async def build_bm25_index_for_graph(
    config: ExperimentConfig,
    data_dir: Path,
    bm25_save_dir: Path,
    progress: Progress = None,
    max_workers: int = 10,
    skip_existing: bool = True
):
    """
    Build BM25 indexes for graph data in parallel

    Args:
        config: Experiment configuration
        data_dir: STSGraph data directory
        bm25_save_dir: BM25 index save directory
        progress: Rich progress bar object
        max_workers: Maximum concurrency
        skip_existing: Whether to skip existing index files (checkpoint resume)
    """
    console.print("\n[bold cyan]" + "="*80 + "[/bold cyan]")
    console.print("[bold cyan]Starting STSGraph BM25 Index Building (Parallel Mode)[/bold cyan]")
    console.print("[bold cyan]" + "="*80 + "[/bold cyan]\n")
    console.print(f"[bold]Skip existing:[/bold] {'Yes' if skip_existing else 'No'}\n")

    # Initialize NLTK
    console.print("Ensuring NLTK data is available...")
    ensure_nltk_data()
    stemmer = PorterStemmer()
    stop_words = set(stopwords.words("english"))

    # Create semaphore for concurrency control
    semaphore = asyncio.Semaphore(max_workers)

    async def process_with_semaphore(conv_id: int, task_id: int):
        """Processing function with semaphore-controlled concurrency"""
        async with semaphore:
            if progress:
                progress.start_task(task_id)
                progress.update(task_id, status="processing")

            # Execute CPU-intensive operations in thread pool
            loop = asyncio.get_event_loop()
            success, status = await loop.run_in_executor(
                None,
                build_bm25_index_for_single_conv,
                conv_id,
                data_dir,
                bm25_save_dir,
                stemmer,
                stop_words,
                skip_existing
            )

            if progress:
                if status == "skipped":
                    progress.update(task_id, status="[cyan]exists[/cyan]", completed=1)
                elif status == "completed":
                    progress.update(task_id, status="[green]done[/green]", completed=1)
                else:
                    progress.update(task_id, status="[yellow]skipped[/yellow]", completed=1)

            return (conv_id, success, status)

    # If progress bar is available, use progress bar processing
    if progress:
        # Create tasks for each conversation
        tasks = []
        for i in range(config.num_conv):
            task_id = progress.add_task(
                f"[cyan]BM25 Index - Conversation {i}[/cyan]",
                total=1,
                status="waiting",
                start=False
            )
            tasks.append((i, task_id))

        # Parallel processing
        coroutines = [process_with_semaphore(conv_id, task_id) for conv_id, task_id in tasks]
        results = await asyncio.gather(*coroutines, return_exceptions=True)
    else:
        # No progress bar mode (simple print)
        coroutines = []
        for i in range(config.num_conv):
            async def simple_process(conv_id):
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(
                    None,
                    build_bm25_index_for_single_conv,
                    conv_id,
                    data_dir,
                    bm25_save_dir,
                    stemmer,
                    stop_words,
                    skip_existing
                )
            coroutines.append(simple_process(i))
        results = await asyncio.gather(*coroutines, return_exceptions=True)

    # Summarize results
    completed_count = 0
    skipped_count = 0
    failed_count = 0
    for r in results:
        if isinstance(r, tuple) and len(r) >= 3:
            status = r[2]
            if status == "skipped":
                skipped_count += 1
            elif status == "completed":
                completed_count += 1
            else:
                failed_count += 1
        elif isinstance(r, Exception):
            failed_count += 1

    console.print("\n[bold green][OK] BM25 index building complete[/bold green]")
    console.print(f"    New: {completed_count}, Skipped: {skipped_count}, Failed: {failed_count}")


def build_embedding_index_for_single_conv(
    conv_id: int,
    data_dir: Path,
    emb_save_dir: Path,
    embedding_provider: EmbeddingProvider,
    batch_size: int = 256,
    skip_existing: bool = True
) -> tuple[bool, str]:
    """
    Build vector embedding index for a single conversation's graph data

    Node embeddings are built directly from each node's searchable text.
    Relations do not modify or propagate into node vectors.

    Args:
        conv_id: Conversation ID
        data_dir: STSGraph data directory
        emb_save_dir: Vector index save directory
        embedding_provider: Embedding provider
        batch_size: Batch size
        skip_existing: Whether to skip existing index files

    Returns:
        (success, status: "completed"/"skipped"/"failed")
    """
    try:
        # Check if output file already exists (checkpoint resume)
        output_path = emb_save_dir / f"graph_embedding_index_conv_{conv_id}.pkl"
        if skip_existing and output_path.exists():
            try:
                with output_path.open("rb") as existing_file:
                    existing = pickle.load(existing_file)
                if (
                    any(item.get("type") == "state" for item in existing)
                    and all(item.get("field") == "raw" for item in existing)
                ):
                    return (True, "skipped")
            except (OSError, EOFError, pickle.UnpicklingError):
                pass

        graph_file = data_dir / f"graph_conv_{conv_id}.json"
        if not graph_file.exists():
            return (False, "failed")

        # Read graph data
        with open(graph_file, "r", encoding="utf-8") as f:
            graph = json.load(f)

        # ===== Step 1: Collect node texts and generate initial node embeddings =====
        print("  [Step 1] Generating initial node embeddings...")

        texts_to_embed = []
        node_text_map = []  # Record node info for each text

        # 1.1 Claim records
        claims = graph.get("claims", {})
        for claim_id, claim_data in claims.items():
            # Build complete text representation for each claim (consistent with BM25 index)
            parts = []

            # Core content
            if claim_data.get("content"):
                parts.append(claim_data["content"])

            # Query patterns (important! helps match user questions)
            if claim_data.get("query_patterns"):
                parts.append(" ".join(claim_data["query_patterns"]))

            # Keywords
            keywords = claim_data.get("keywords") or []
            if keywords:
                if isinstance(keywords, list):
                    parts.append(" ".join(keywords))
                else:
                    parts.append(str(keywords))

            # Temporal information
            if claim_data.get("temporal"):
                parts.append(str(claim_data["temporal"]))

            # Spatial information
            if claim_data.get("spatial"):
                parts.append(str(claim_data["spatial"]))

            claim_text = " ".join(parts)
            if claim_text.strip():
                texts_to_embed.append(claim_text)
                node_text_map.append({
                    "node_type": "claim",
                    "node_id": claim_id,
                    "data": claim_data
                })

        # 1.2 Event nodes
        events = graph.get("events", {})
        for event_id, event_data in events.items():
            # Merge subject, summary, and event as the complete text representation for the event
            parts = []
            if event_data.get("subject"):
                parts.append(event_data["subject"])
            if event_data.get("summary"):
                parts.append(event_data["summary"])
            if event_data.get("event_description"):
                parts.append(event_data["event_description"])

            if parts:
                event_text = " ".join(parts)
                texts_to_embed.append(event_text)
                node_text_map.append({
                    "node_type": "event",
                    "node_id": event_id,
                    "data": event_data
                })

        # 1.3 Scope nodes
        scopes = graph.get("scopes", {})
        for scope_id, scope_data in scopes.items():
            # Merge title and summary as the complete text representation for the scope
            parts = []
            if scope_data.get("title"):
                parts.append(scope_data["title"])
            if scope_data.get("summary"):
                parts.append(scope_data["summary"])

            if parts:
                scope_text = " ".join(parts)
                texts_to_embed.append(scope_text)
                node_text_map.append({
                    "node_type": "scope",
                    "node_id": scope_id,
                    "data": scope_data
                })

        # 1.4 State nodes
        states = graph.get("states", {})
        claims = graph.get("claims", {})
        for state_id, state_data in states.items():
            state_text = build_state_searchable_text(state_data, claims)
            if state_text:
                texts_to_embed.append(state_text)
                node_text_map.append({
                    "node_type": "state",
                    "node_id": state_id,
                    "data": state_data,
                })

        if not texts_to_embed:
            return (False, "failed")

        # Batch generate node embeddings
        all_node_embeddings = []
        for j in range(0, len(texts_to_embed), batch_size):
            batch_texts = texts_to_embed[j:j+batch_size]
            batch_embeddings = embedding_provider.embed(batch_texts)
            all_node_embeddings.extend(batch_embeddings)

        embedding_index = [
            {
                "type": node_info["node_type"],
                "id": node_info["node_id"],
                "field": "raw",
                "embedding": embedding,
                "data": node_info["data"],
            }
            for node_info, embedding in zip(
                node_text_map, all_node_embeddings
            )
        ]

        # Save standard format
        output_path = emb_save_dir / f"graph_embedding_index_conv_{conv_id}.pkl"
        emb_save_dir.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            pickle.dump(embedding_index, f)

        return (True, "completed")

    except Exception as e:
        console.print(f"  [red][X] Conversation {conv_id}: Embedding index building failed - {e}[/red]")
        return (False, "failed")


async def build_embedding_index_for_graph(
    config: ExperimentConfig,
    data_dir: Path,
    emb_save_dir: Path,
    progress: Progress = None,
    max_workers: int = 10,
    skip_existing: bool = True
):
    """
    Build vector embedding indexes for graph data in parallel

    Args:
        config: Experiment configuration
        data_dir: STSGraph data directory
        emb_save_dir: Vector index save directory
        progress: Rich progress bar object
        max_workers: Maximum concurrency
        skip_existing: Whether to skip existing index files (checkpoint resume)
    """
    console.print("\n[bold cyan]" + "="*80 + "[/bold cyan]")
    console.print("[bold cyan]Starting Raw Node Vector Index Building[/bold cyan]")
    console.print("[bold cyan]" + "="*80 + "[/bold cyan]\n")
    console.print(f"[bold]Skip existing:[/bold] {'Yes' if skip_existing else 'No'}\n")

    # Initialize embedding provider
    embedding_provider = EmbeddingProvider(
        base_url=config.embedding_config["base_url"],
        model_name=config.embedding_config["model_name"],
        api_key=config.embedding_config.get("api_key", ""),
    )
    BATCH_SIZE = 256

    # Create semaphore for concurrency control
    semaphore = asyncio.Semaphore(max_workers)

    async def process_with_semaphore(conv_id: int, task_id: int):
        """Processing function with semaphore-controlled concurrency"""
        async with semaphore:
            if progress:
                progress.start_task(task_id)
                progress.update(task_id, status="processing")

            # Execute IO-intensive operations in thread pool
            loop = asyncio.get_event_loop()
            success, status = await loop.run_in_executor(
                None,
                build_embedding_index_for_single_conv,
                conv_id,
                data_dir,
                emb_save_dir,
                embedding_provider,
                BATCH_SIZE,
                skip_existing
            )

            if progress:
                if status == "skipped":
                    progress.update(task_id, status="[cyan]exists[/cyan]", completed=1)
                elif status == "completed":
                    progress.update(task_id, status="[green]done[/green]", completed=1)
                else:
                    progress.update(task_id, status="[red]failed[/red]", completed=1)

            return (conv_id, success, status)

    # If progress bar is available, use progress bar processing
    if progress:
        # Create tasks for each conversation
        tasks = []
        for i in range(config.num_conv):
            task_id = progress.add_task(
                f"[cyan]Embedding Index - Conversation {i}[/cyan]",
                total=1,
                status="waiting",
                start=False
            )
            tasks.append((i, task_id))

        # Parallel processing
        coroutines = [process_with_semaphore(conv_id, task_id) for conv_id, task_id in tasks]
        results = await asyncio.gather(*coroutines, return_exceptions=True)
    else:
        # No progress bar mode
        coroutines = []
        for i in range(config.num_conv):
            async def simple_process(conv_id):
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(
                    None,
                    build_embedding_index_for_single_conv,
                    conv_id,
                    data_dir,
                    emb_save_dir,
                    embedding_provider,
                    BATCH_SIZE,
                    skip_existing
                )
            coroutines.append(simple_process(i))
        results = await asyncio.gather(*coroutines, return_exceptions=True)

    # Summarize results
    completed_count = 0
    skipped_count = 0
    failed_count = 0
    for r in results:
        if isinstance(r, tuple) and len(r) >= 3:
            status = r[2]
            if status == "skipped":
                skipped_count += 1
            elif status == "completed":
                completed_count += 1
            else:
                failed_count += 1
        elif isinstance(r, Exception):
            failed_count += 1

    console.print("\n[bold green][OK] Embedding index building complete[/bold green]")
    console.print(f"    New: {completed_count}, Skipped: {skipped_count}, Failed: {failed_count}")


async def main():
    """Main function: build graph indexes in parallel"""
    config = ExperimentConfig()

    console.print("\n[bold cyan]" + "="*80 + "[/bold cyan]")
    console.print("[bold cyan]STS index building[/bold cyan]")
    console.print("[bold cyan]" + "="*80 + "[/bold cyan]\n")

    # Configure paths
    graph_dir = config.graph_dir()
    bm25_save_dir = config.bm25_index_dir()
    emb_save_dir = config.vectors_dir()

    # Create save directories
    bm25_save_dir.mkdir(parents=True, exist_ok=True)
    emb_save_dir.mkdir(parents=True, exist_ok=True)

    # Concurrency setting
    max_concurrent_tasks = 1

    # Checkpoint resume setting: whether to skip existing index files
    skip_existing = True  # True: skip existing files; False: force regeneration of all indexes

    console.print(f"[bold]Experiment name:[/bold] {config.experiment_name}")
    console.print(f"[bold]STSGraph directory:[/bold] {graph_dir}")
    console.print(f"[bold]BM25 index save directory:[/bold] {bm25_save_dir}")
    console.print(f"[bold]Vector index save directory:[/bold] {emb_save_dir}")
    console.print(f"[bold]Number of conversations:[/bold] {config.num_conv}")
    console.print(f"[bold]Concurrency:[/bold] {max_concurrent_tasks}")
    console.print(f"[bold]Checkpoint resume:[/bold] {'Enabled' if skip_existing else 'Disabled'}\n")

    # Create progress bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.completed:>3}/{task.total:<3}"),  # Right-align completed count, left-align total count
        TextColumn("•"),
        TimeElapsedColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        TextColumn("•"),
        TextColumn("[bold]{task.fields[status]}"),
        console=console,
        transient=False
    ) as progress:
        # Build BM25 index
        await build_bm25_index_for_graph(
            config,
            graph_dir,
            bm25_save_dir,
            progress=progress,
            max_workers=max_concurrent_tasks,
            skip_existing=skip_existing
        )

        # Build vector embedding index (if retrieval type requires vectors)
        retrieval_type = getattr(config, 'retrieval_type', 'rrf').lower()
        need_emb = retrieval_type in ('vector', 'rrf')
        if need_emb:
            await build_embedding_index_for_graph(
                config,
                graph_dir,
                emb_save_dir,
                progress=progress,
                max_workers=max_concurrent_tasks,
                skip_existing=skip_existing
            )

    console.print("\n[bold cyan]" + "="*80 + "[/bold cyan]")
    console.print("[bold cyan]All STSGraph Index Building Complete![/bold cyan]")
    console.print("[bold cyan]" + "="*80 + "[/bold cyan]\n")


if __name__ == "__main__":
    asyncio.run(main())
