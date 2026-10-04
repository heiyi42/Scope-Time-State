import os
from pathlib import Path
from dotenv import load_dotenv

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _embedding_endpoint() -> str:
    openai_base = os.environ.get("OPENAI_EMBEDDING_BASE_URL")
    if openai_base:
        openai_base = openai_base.rstrip("/")
        return (
            openai_base + "/embeddings"
            if openai_base.endswith("/v1")
            else openai_base
        )
    return os.environ.get(
        "EMBEDDING_BASE_URL", "http://localhost:11810/v1"
    )


# ==================== Path Configuration ====================
DATA_DIR = PROJECT_ROOT / "data"
RESULTS_DIR = Path(
    os.environ.get("STS_RESULTS_DIR", PROJECT_ROOT / "results")
)
DEFAULT_DATASET_PATH = (
    PROJECT_ROOT
    / "data"
    / "locomo"
    / "locomo10.json"
)


class ExperimentConfig:
    # ==================== General ====================
    experiment_name: str = os.environ.get(
        "STS_EXPERIMENT_NAME", "STS-V2"
    )
    dataset_path: str = os.environ.get(
        "STS_DATASET_PATH",
        str(DEFAULT_DATASET_PATH),
    )
    num_conv: int = 10

    # ==================== Graph construction ====================
    enable_low_weight_repool: bool = (
        os.environ.get("STS_ENABLE_LOW_WEIGHT_REPOOL", "true").lower()
        == "true"
    )
    event_scope_weight_threshold: float = float(
        os.environ.get("STS_EVENT_SCOPE_WEIGHT_THRESHOLD", "0.6")
    )
    shuffle_scope_events: bool = (
        os.environ.get("STS_SHUFFLE_SCOPE_EVENTS", "true").lower()
        == "true"
    )
    scope_event_shuffle_seed: int = int(
        os.environ.get("STS_SCOPE_EVENT_SHUFFLE_SEED", "42")
    )
    scope_candidate_top_k: int = int(
        os.environ.get("STS_SCOPE_CANDIDATE_TOP_K", "10")
    )

    embedding_config: dict = {
        "model_name": os.environ.get(
            "OPENAI_EMBEDDING_MODEL", "Qwen3-Embedding-4B"
        ),
        "base_url": _embedding_endpoint(),
        "api_key": os.environ.get(
            "OPENAI_EMBEDDING_API_KEY",
            os.environ.get("OPENAI_API_KEY", ""),
        ),
    }
    embedding_max_retries: int = 10
    embedding_base_url: str = str(embedding_config["base_url"])
    embedding_model: str = str(embedding_config["model_name"])

    # ==================== Retrieval ====================
    retrieval_type: str = os.environ.get(
        "STS_RETRIEVAL_TYPE", "rrf"
    ).lower()
    include_source_events: bool = (
        os.environ.get("STS_INCLUDE_SOURCE_EVENTS", "true").lower()
        == "true"
    )
    include_claims: bool = (
        os.environ.get("STS_INCLUDE_CLAIMS", "true").lower()
        == "true"
    )

    retrieval_config: dict = {
        "scope_top_k": int(os.environ.get("STS_SCOPE_TOP_K", "9")),
        "state_top_k": int(os.environ.get("STS_STATE_TOP_K", "15")),
        "claim_top_k": int(os.environ.get("STS_CLAIM_TOP_K", "30")),
        "claim_seed_top_k": int(
            os.environ.get("STS_CLAIM_SEED_TOP_K", "15")
        ),
        "time_group_max_claims": int(
            os.environ.get("STS_TIME_GROUP_MAX_CLAIMS", "3")
        ),
        "time_group_max_claims_per_state": int(
            os.environ.get(
                "STS_TIME_GROUP_MAX_CLAIMS_PER_STATE", "6"
            )
        ),
    }
    scope_top_k: int = int(retrieval_config["scope_top_k"])
    state_top_k: int = int(retrieval_config["state_top_k"])
    claim_top_k: int = int(retrieval_config["claim_top_k"])
    claim_seed_top_k: int = int(retrieval_config["claim_seed_top_k"])
    time_group_max_claims: int = int(
        retrieval_config["time_group_max_claims"]
    )
    time_group_max_claims_per_state: int = int(
        retrieval_config["time_group_max_claims_per_state"]
    )

    temporal_enhancement: bool = True

    # ==================== Response generation ====================
    llm_service: str = "openai"

    llm_config: dict = {
        "openai": {
            "llm_provider": "openai",
            "model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
            "base_url": os.environ.get(
                "OPENAI_BASE_URL", "https://api.openai.com/v1"
            ),
            "api_key": os.environ.get("OPENAI_API_KEY", ""),
            "temperature": 0,
            "max_tokens": 16384,
        },
        "gemini": {
            "llm_provider": "openai",
            "model": "google/gemini-2.5-flash",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": os.environ.get("OPENROUTER_API_KEY", ""),
            "temperature": 0.3,
            "max_tokens": 16384,
        },
        "vllm": {
            "llm_provider": "openai",
            "model": "Qwen3-30B",
            "base_url": os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1"),
            "api_key": "unused",
            "temperature": 0,
            "max_tokens": 20000,
        }
    }

    judge_llm_config: dict = {
        "model": os.environ.get("OPENAI_JUDGE_MODEL", "gpt-4o-mini"),
        "base_url": os.environ.get(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        ),
        "api_key": os.environ.get("OPENAI_API_KEY", ""),
        "temperature": 0,
    }

    llm_max_retries: int = 10
    max_concurrent_requests: int = 10

    # ==================== Derived Paths ====================
    @classmethod
    def experiment_dir(cls) -> Path:
        configured = os.environ.get("STS_RESULT_DIR")
        return Path(configured) if configured else RESULTS_DIR / cls.experiment_name

    @classmethod
    def artifact_dir(cls) -> Path:
        configured = os.environ.get("STS_ARTIFACT_DIR")
        return Path(configured) if configured else cls.experiment_dir()

    @classmethod
    def events_dir(cls) -> Path:
        return cls.experiment_dir() / "events"

    @classmethod
    def graph_dir(cls) -> Path:
        return cls.artifact_dir() / "graphs"

    @classmethod
    def claims_dir(cls) -> Path:
        return cls.experiment_dir() / "claims"

    @classmethod
    def scopes_dir(cls) -> Path:
        return cls.experiment_dir() / "scopes"

    @classmethod
    def states_dir(cls) -> Path:
        return cls.experiment_dir() / "states"

    @classmethod
    def token_stats_dir(cls) -> Path:
        return cls.experiment_dir() / "token_stats"

    @classmethod
    def bm25_index_dir(cls) -> Path:
        return cls.artifact_dir() / "bm25_index"

    @classmethod
    def vectors_dir(cls) -> Path:
        return cls.artifact_dir() / "vectors"


def _build_experiment_name():
    parts = [ExperimentConfig.experiment_name]

    if ExperimentConfig.retrieval_type in ('vector', 'rrf'):
        parts.append(f"{ExperimentConfig.retrieval_type.upper()}")
        rc = ExperimentConfig.retrieval_config
        parts.append(
            f"{rc['scope_top_k']}-{rc['state_top_k']}-"
            f"{rc['claim_top_k']}"
        )
    else:
        parts.append(ExperimentConfig.retrieval_type)
    evidence_outputs = []
    if ExperimentConfig.include_source_events:
        evidence_outputs.append("events")
    if ExperimentConfig.include_claims:
        evidence_outputs.append("claims")
    parts.append("-".join(evidence_outputs) or "states")

    parts.append("cot")

    return "_".join(parts)

ExperimentConfig.experiment_name = _build_experiment_name()
