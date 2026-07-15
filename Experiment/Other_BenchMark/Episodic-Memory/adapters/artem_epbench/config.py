"""Fixed EPBench Long Book paths used by the ARTEM baseline."""

from pathlib import Path


ARTEM_DIR = Path(__file__).resolve().parent
EPBENCH_ROOT = ARTEM_DIR.parents[1]
REPO_ROOT = ARTEM_DIR.parents[4]
OFFICIAL_ARTEM_DIR = EPBENCH_ROOT / "Baseline" / "ARTEM"
EPBENCH_SOURCE_DIR = (
    EPBENCH_ROOT
    / "data"
    / "Udefault_Sdefault_seed0"
    / "books"
    / "model_claude-3-5-sonnet-20240620_itermax_10_"
    "Idefault_nbchapters_196_nbtokens_102870"
)
EPBENCH_BOOK_PATH = EPBENCH_SOURCE_DIR / "book.json"
EPBENCH_QA_PATH = EPBENCH_SOURCE_DIR / "df_qa.parquet"

DEFAULT_OUTPUT_ROOT = ARTEM_DIR / "output" / "epbench_long_book"
BOOK_ID = 1


def book_output_dir(output_root: Path | str = DEFAULT_OUTPUT_ROOT) -> Path:
    return Path(output_root).expanduser().resolve() / f"book{BOOK_ID}"


def validate_source_paths() -> None:
    missing = [
        path for path in (EPBENCH_BOOK_PATH, EPBENCH_QA_PATH) if not path.is_file()
    ]
    if missing:
        formatted = "\n".join(f"- {path}" for path in missing)
        raise FileNotFoundError(f"Missing fixed EPBench Long Book inputs:\n{formatted}")
