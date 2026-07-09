"""Import official EverMemBench eval classes when available.

Adapters live under ``Baseline/*`` so they can be packaged with the benchmark
wrapper. When they are loaded by the upstream official CLI, prefer the official
``eval.src`` modules. When inspected standalone from ``Baseline/``, fall back to
the copied support modules in this directory.
"""

try:
    from eval.src.adapters.base import BaseAdapter
    from eval.src.core.data_models import AddResult, Dataset, GroupChatMessage, SearchResult
    from eval.src.utils.config import load_yaml
    from eval.src.utils.logger import get_console, print_success, print_warning
except ImportError:
    from common.official_eval.base import BaseAdapter
    from common.official_eval.config import load_yaml
    from common.official_eval.data_models import AddResult, Dataset, GroupChatMessage, SearchResult
    from common.official_eval.logger import get_console, print_success, print_warning

__all__ = [
    "AddResult",
    "BaseAdapter",
    "Dataset",
    "GroupChatMessage",
    "SearchResult",
    "get_console",
    "load_yaml",
    "print_success",
    "print_warning",
]
