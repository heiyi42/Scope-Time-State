"""
CLI entry point for multi-person group chat evaluation.

Supported fair systems: embedding_rag, mem0_local, memobase, graphiti_local,
memos_local

Stages:
    add      - Ingest conversation data into memory system
    search   - Retrieve memories for QA questions
    answer   - Generate answers using LLM
    evaluate - Assess answer quality

Usage:
    # Smoke test - add first day only
    python -m eval.cli --dataset dataset/004/dialogue.json --system mem0_local --smoke --smoke-days 1

    # Add all days
    python -m eval.cli --dataset dataset/004/dialogue.json --system graphiti_local --stages add

    # Full pipeline: search -> answer -> evaluate
    python -m eval.cli --dataset dataset/004/dialogue.json --qa dataset/004/qa_004.json \
        --system mem0_local --user-id 004 --stages search answer evaluate

    # Test fair local/self-host systems
    for sys in embedding_rag mem0_local memobase memos_local graphiti_local; do
        python -m eval.cli --dataset dataset/004/dialogue.json --system $sys --smoke
    done
"""
import asyncio
import argparse
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
OUTER_EVERMEMBENCH_DIR = Path(__file__).resolve().parents[3]

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from eval.src.core.loaders import load_groupchat_dataset
from eval.src.core.pipeline import Pipeline
from eval.src.utils.config import load_yaml, get_config_path
from eval.src.utils.logger import get_console, print_error


# Fair local/self-host systems and their required environment variables.
# Hosted/cloud systems are intentionally not exposed by this CLI wrapper.
SUPPORTED_SYSTEMS = {
    "mem0_local": [],
    "memos_local": [],
    "memobase": ["MEMOBASE_BASE_URL", "MEMOBASE_API_TOKEN"],
    "graphiti_local": [],
    "embedding_rag": ["OPENAI_EMBEDDING_API_KEY"],
}


def validate_env_vars(system_name: str) -> bool:
    """
    Validate required environment variables for a system.
    
    Args:
        system_name: System name
        
    Returns:
        True if all required env vars are set
    """
    console = get_console()
    required_vars = SUPPORTED_SYSTEMS.get(system_name, [])
    missing_vars = []
    
    for var in required_vars:
        if not os.environ.get(var):
            missing_vars.append(var)
    
    if missing_vars:
        console.print(f"\n❌ Missing environment variables for {system_name}:", style="bold red")
        for var in missing_vars:
            console.print(f"   - {var}", style="red")
        console.print("\nPlease set these in your .env file or environment.", style="dim")
        return False
    
    return True


def create_adapter(system_name: str, output_dir: Path, base_url: str = None):
    """
    Create adapter for specified system.

    Args:
        system_name: System name (mem0_local, memobase, graphiti_local,
        memos_local, embedding_rag)
        output_dir: Output directory
        base_url: Optional base URL override for memory system

    Returns:
        Adapter instance
    """
    # If base_url is provided via CLI, set it as environment variable to override
    # This allows CLI arguments to satisfy env var requirements
    if base_url:
        if system_name == "memobase":
            os.environ["MEMOBASE_BASE_URL"] = base_url
        elif system_name == "memos_local":
            os.environ["MEMOS_LOCAL_BASE_URL"] = base_url
        elif system_name == "mem0_local":
            os.environ["MEM0_LOCAL_BASE_URL"] = base_url

    # Validate environment variables first
    if not validate_env_vars(system_name):
        raise ValueError(f"Missing required environment variables for {system_name}")

    if system_name == "embedding_rag":
        from eval.src.adapters.embedding_rag_adapter import EmbeddingRAGAdapter
        config_path = OUTER_EVERMEMBENCH_DIR / "Baseline/embedding_rag/config.yaml"
        return EmbeddingRAGAdapter(load_yaml(str(config_path)), output_dir)

    # Load system config for memory system adapters
    config_path = get_config_path(f"{system_name}.yaml")

    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    config = load_yaml(str(config_path))

    # Apply base_url override if provided
    # Adapters use different config keys: api_url (memos_local/mem0_local),
    # project_url (memobase)
    if base_url:
        config["base_url"] = base_url
        if system_name in {"memos_local", "mem0_local"}:
            config["api_url"] = base_url
        elif system_name == "memobase":
            config["project_url"] = base_url

    # Create adapter based on system
    if system_name == "mem0_local":
        from eval.src.adapters.mem0_local_adapter import Mem0LocalAdapter
        return Mem0LocalAdapter(config, output_dir)
    elif system_name == "memos_local":
        from eval.src.adapters.memos_local_adapter import MemosLocalAdapter
        return MemosLocalAdapter(config, output_dir)
    elif system_name == "memobase":
        from eval.src.adapters.memobase_adapter import MemobaseAdapter
        return MemobaseAdapter(config, output_dir)
    elif system_name == "graphiti_local":
        from eval.src.adapters.graphiti_local_adapter import GraphitiLocalAdapter
        return GraphitiLocalAdapter(config, output_dir)
    else:
        supported = ", ".join(SUPPORTED_SYSTEMS.keys())
        raise ValueError(f"Unknown system: {system_name}. Supported: {supported}")


def parse_args():
    """Parse command line arguments."""
    supported = list(SUPPORTED_SYSTEMS.keys())
    
    parser = argparse.ArgumentParser(
        description="Multi-Person Group Chat Evaluation Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Supported Fair Systems:
    mem0_local  - Mem0 self-host system (env: MEM0_LOCAL_BASE_URL, MEM0_LOCAL_API_KEY)
    memos_local - MemOS open-source local system (env: MEMOS_LOCAL_BASE_URL)
    memobase    - Memobase self-host/local system (env: MEMOBASE_BASE_URL, MEMOBASE_API_TOKEN)
    graphiti_local - Graphiti open-source local system (env: GRAPHITI_LLM_*, NEO4J_*)
    embedding_rag - Dense retrieval over dialogue chunks (env: OPENAI_EMBEDDING_API_KEY)

Examples:
    # Smoke test with first day
    python -m eval.cli --dataset dataset/004/dialogue.json --system mem0_local --smoke

    # Add all days
    python -m eval.cli --dataset dataset/004/dialogue.json --system graphiti_local --stages add

    # Custom user ID
    python -m eval.cli --dataset dataset/004/dialogue.json --system memos_local --user-id my_test_user

    # Full evaluation pipeline
    python -m eval.cli --dataset dataset/004/dialogue.json --qa dataset/004/qa_004.json \\
        --system mem0_local --user-id 004 --stages search answer evaluate --top-k 10

    # Test fair local/self-host systems
    for sys in embedding_rag mem0_local memobase memos_local graphiti_local; do
        python -m eval.cli --dataset dataset/004/dialogue.json --system $sys --smoke
    done
        """
    )
    
    # Required arguments
    parser.add_argument(
        "--dataset",
        type=str,
        help="Path to dataset JSON file (e.g., dataset/004/dialogue.json)"
    )
    
    parser.add_argument(
        "--system",
        type=str,
        required=True,
        choices=supported,
        help="Memory system to use"
    )
    
    # Optional arguments
    parser.add_argument(
        "--stages",
        type=str,
        nargs="+",
        default=["add"],
        choices=["add", "search", "answer", "evaluate"],
        help="Stages to run: add, search, answer, evaluate (default: add)"
    )
    
    parser.add_argument(
        "--qa",
        type=str,
        default=None,
        help="Path to QA JSON file (required for search/answer/evaluate stages)"
    )
    
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Number of memories to retrieve for search (default: from system config)"
    )
    
    parser.add_argument(
        "--user-id",
        type=str,
        default=None,
        help="User ID for memory system (default: auto-generated)"
    )
    
    parser.add_argument(
        "--output-dir",
        type=str,
        default="eval/results",
        help="Output directory (default: eval/results)"
    )

    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Resume add from this date (inclusive), format YYYY-MM-DD (e.g., 2025-05-22). "
             "Currently implemented for memobase; other systems may ignore it."
    )
    
    # Smoke test options
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Enable smoke test mode"
    )
    
    parser.add_argument(
        "--smoke-days",
        type=int,
        default=1,
        help="Number of days for smoke test (default: 1)"
    )

    parser.add_argument(
        "--smoke-date",
        type=str,
        default=None,
        help="Run smoke test for a specific date (YYYY-MM-DD), e.g. 2025-01-16. "
             "If set, overrides --smoke-days."
    )
    
    parser.add_argument(
        "--qa-limit",
        type=int,
        default=None,
        help="Limit number of QA questions to process (for testing)"
    )
    
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="Override base URL for local memory system"
    )

    return parser.parse_args()


async def main():
    """Main entry point."""
    args = parse_args()
    console = get_console()
    
    try:
        # Embedding RAG needs the dialogue index before retrieval and answering.
        if args.system == "embedding_rag":
            if any(stage in args.stages for stage in ("search", "answer")):
                if "add" not in args.stages:
                    args.stages = ["add"] + args.stages
            if "answer" in args.stages:
                if "search" not in args.stages:
                    idx = min(
                        args.stages.index("answer") if "answer" in args.stages else len(args.stages),
                        args.stages.index("evaluate") if "evaluate" in args.stages else len(args.stages)
                    )
                    args.stages.insert(idx, "search")
                console.print("\n[yellow]Embedding RAG: indexing dialogue chunks before retrieval[/yellow]")

        # Validate --dataset for stages that need it
        if "add" in args.stages and not args.dataset:
            print_error("--dataset argument required for add stage")
            sys.exit(1)

        # Load dataset only when needed
        dataset = None
        if args.dataset:
            dataset = load_groupchat_dataset(args.dataset)

        # Generate user_id if not provided
        user_id = args.user_id
        if user_id is None:
            import time
            if args.dataset:
                dataset_num = Path(args.dataset).parent.name
            else:
                dataset_num = "unknown"
            timestamp = int(time.time())
            user_id = f"groupchat_{dataset_num}_{args.system}_{timestamp}"

        # Create output directory
        output_dir = Path(args.output_dir) / args.system
        output_dir.mkdir(parents=True, exist_ok=True)

        # Create adapter
        adapter = create_adapter(args.system, output_dir, base_url=args.base_url)

        # Create pipeline
        pipeline = Pipeline(adapter, output_dir, system_name=args.system)

        # Determine smoke test settings
        smoke_days = None
        smoke_date = None
        if args.smoke:
            if args.smoke_date:
                smoke_date = args.smoke_date
                smoke_days = None
            else:
                smoke_days = args.smoke_days

        # Validate QA path for search/answer/evaluate stages
        if any(s in args.stages for s in ["search", "answer", "evaluate"]):
            if not args.qa:
                print_error("--qa argument required for search/answer/evaluate stages")
                sys.exit(1)

        # Validate LLM API key for answer/evaluate stages
        if any(s in args.stages for s in ["answer", "evaluate"]):
            pipeline_cfg = load_yaml(str(get_config_path("pipeline.yaml")))
            answer_key = pipeline_cfg.get("answer", {}).get("api_key")
            evaluate_key = pipeline_cfg.get("evaluate", {}).get("api_key")
            if not (os.environ.get("LLM_API_KEY") or answer_key or evaluate_key):
                print_error("LLM API key required for answer/evaluate stages")
                console.print(
                    "Set LLM_API_KEY, or use the local pipeline default with an OpenAI-compatible local server.",
                    style="dim",
                )
                sys.exit(1)

        # Run pipeline
        results = await pipeline.run(
            dataset=dataset,
            user_id=user_id,
            stages=args.stages,
            smoke_days=smoke_days,
            smoke_date=smoke_date,
            start_date=args.start_date,
            qa_path=args.qa,
            top_k=args.top_k,
            qa_limit=args.qa_limit,
        )
        
        # Exit with appropriate code
        if "add" in results:
            add_result = results["add"]
            if not add_result.success:
                sys.exit(1)
        
    except FileNotFoundError as e:
        print_error(str(e))
        sys.exit(1)
    except ValueError as e:
        print_error(str(e))
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
