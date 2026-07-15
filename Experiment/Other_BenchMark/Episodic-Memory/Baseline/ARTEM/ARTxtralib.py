"""Compatibility helpers for the public ARTEM retrieval script.

The ARTEM repository imports three helpers from an unreleased ``ARTxtralib``:
``ART2ACModelOverride``, ``saveFusionARTNetwork`` and
``loadFusionARTNetwork``.  This clean-room module supplies those interfaces for
use with :mod:`fusionART`.

The semantic-channel override follows the fuzzy-intersection match equation
published by ARTEM.  Network persistence uses a human-readable, versioned JSON
format and writes atomically where the operating system permits it.
"""

from __future__ import annotations

import json
import os
import pickle
import tempfile
from pathlib import Path
from typing import Any, Mapping

from fusionART import FusionART


def ART2ACModelOverride(fa: FusionART, k: int) -> FusionART:
    """Configure channel ``k`` for ARTEM's continuous semantic representation.

    The name is preserved for source compatibility with ``eventRetriever.py``.
    ARTEM's published retrieval equation is the fuzzy-intersection match
    ``|I ^ w| / |I|``; :class:`fusionART.FusionART` installs that equation for
    this channel and records an ``art2ac_paper_match`` metadata label.
    """
    if not isinstance(fa, FusionART):
        raise TypeError(
            "ART2ACModelOverride expects a fusionART.FusionART instance, "
            f"got {type(fa).__name__}."
        )
    fa.set_field_model(int(k), "art2ac")
    return fa


def _resolve_network_file(path: str | os.PathLike[str], *, for_write: bool) -> Path:
    """Resolve a file path while also accepting an existing directory."""
    target = Path(path).expanduser()
    if target.exists() and target.is_dir():
        return target / "fusionart_network.json"
    if not for_write and not target.exists():
        # Be forgiving when a caller supplied a directory-like path before it
        # was created by a previous implementation.
        directory_candidate = target / "fusionart_network.json"
        if directory_candidate.exists():
            return directory_candidate
    return target


def saveFusionARTNetwork(
    fa: FusionART,
    filepath: str | os.PathLike[str],
) -> str:
    """Serialize ``fa`` to ``filepath`` and return the resolved file path."""
    if not isinstance(fa, FusionART):
        raise TypeError(
            "saveFusionARTNetwork expects a fusionART.FusionART instance, "
            f"got {type(fa).__name__}."
        )

    target = _resolve_network_file(filepath, for_write=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    state = fa.to_state_dict()

    # Atomic replacement avoids leaving a partially written network after an
    # interrupted run. NamedTemporaryFile is created in the same directory so
    # os.replace remains atomic on common local filesystems.
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(target.parent),
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            json.dump(state, temporary, indent=2, ensure_ascii=False)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, target)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.remove(temporary_name)

    return str(target)


def _read_network_state(path: Path) -> Mapping[str, Any]:
    """Read the JSON format, with a narrow fallback for legacy pickle files."""
    try:
        with path.open("r", encoding="utf-8") as stream:
            state = json.load(stream)
        if not isinstance(state, Mapping):
            raise ValueError("Serialized Fusion ART state must be a JSON object.")
        return state
    except (UnicodeDecodeError, json.JSONDecodeError):
        # Some historical ART helper libraries used pickle.  Supporting a
        # trusted, locally produced pickle makes migration easier, but JSON is
        # always used for new saves.  Never load untrusted pickle files.
        with path.open("rb") as stream:
            legacy = pickle.load(stream)
        if isinstance(legacy, FusionART):
            return legacy.to_state_dict()
        if isinstance(legacy, Mapping):
            return legacy
        raise ValueError(
            f"Unsupported legacy Fusion ART payload type: {type(legacy).__name__}."
        )


def loadFusionARTNetwork(
    fa: FusionART,
    filepath: str | os.PathLike[str],
) -> FusionART:
    """Load a saved network into ``fa`` in place and return ``fa``."""
    if not isinstance(fa, FusionART):
        raise TypeError(
            "loadFusionARTNetwork expects a fusionART.FusionART instance, "
            f"got {type(fa).__name__}."
        )

    target = _resolve_network_file(filepath, for_write=False)
    if not target.exists():
        raise FileNotFoundError(f"Fusion ART network file not found: {target}")
    if target.is_dir():
        raise IsADirectoryError(
            f"Expected a Fusion ART network file but received a directory: {target}"
        )

    state = _read_network_state(target)

    # ``eventRetriever.py`` constructs a fresh network with query-specific
    # gamma/rho values before loading the trained recognition codes.  Preserve
    # those runtime retrieval controls; the serialized values describe the
    # encoding run and should not overwrite the current query configuration.
    runtime_gamma = list(fa.gamma)
    runtime_rho = list(fa.rho)
    fa.load_state_dict(state, strict=True)
    fa.gamma = runtime_gamma
    fa.rho = runtime_rho
    return fa


# Snake-case aliases are convenient for new code; official ARTEM continues to
# use the original camel-case function names above.
art2ac_model_override = ART2ACModelOverride
save_fusion_art_network = saveFusionARTNetwork
load_fusion_art_network = loadFusionARTNetwork


__all__ = [
    "ART2ACModelOverride",
    "loadFusionARTNetwork",
    "saveFusionARTNetwork",
    "art2ac_model_override",
    "load_fusion_art_network",
    "save_fusion_art_network",
]
