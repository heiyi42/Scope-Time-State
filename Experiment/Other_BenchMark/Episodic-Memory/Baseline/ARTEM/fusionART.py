"""Minimal multi-channel Fusion ART implementation used by ARTEM.

This module is an independent, clean-room reimplementation of the two missing
runtime components in the public ARTEM repository.  It follows the standard
multi-channel fuzzy ART equations and the match equation published in the
ARTEM paper:

    choice_j = sum_k gamma_k * |I_k ^ w_jk| / (alpha_k + |w_jk|)
    match_jk = |I_k ^ w_jk| / |I_k|
    w_jk <- beta_k * (I_k ^ w_jk) + (1-beta_k) * w_jk

where ``^`` is the component-wise minimum and ``|.|`` is the L1 norm.

The public ``eventRetriever.py`` only relies on a small API surface:
``FusionART``, ``setActivityF1``, ``resSearch``, ``autoLearn``, ``uncommitted``,
``codes`` and per-field ``matchValField`` callables.  The implementation below
keeps that interface while adding validation and deterministic behaviour.

It is not claimed to be the authors' unreleased customized STEM source code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Mapping, MutableMapping, Optional, Sequence

import numpy as np

ArrayLike = Sequence[float] | np.ndarray
FieldFunction = Callable[[ArrayLike, ArrayLike], float]

_EPS = 1e-12


def _as_1d_finite_array(value: ArrayLike, expected_length: int, *, name: str) -> np.ndarray:
    """Convert one channel to a finite, one-dimensional float array."""
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 1:
        array = array.reshape(-1)
    if array.size != expected_length:
        raise ValueError(
            f"{name} has length {array.size}; expected {expected_length}."
        )
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} contains NaN or infinite values.")
    return array


def _as_1d_float_array(value: ArrayLike, expected_length: int, *, name: str) -> np.ndarray:
    """Convert one learned/stored channel to a normalized float array.

    Stored STEM events and recognition-node weights must remain in ``[0, 1]``.
    Query activities are validated separately because an absent-memory time cue
    may normalize just outside the corpus range; the official retrieval script
    explicitly permits that case so it can return no matching event.
    """
    array = _as_1d_finite_array(value, expected_length, name=name)

    # Small floating-point drift is harmless, but materially out-of-range
    # learned values indicate incorrectly normalized event data.
    tolerance = 1e-7
    if np.any(array < -tolerance) or np.any(array > 1.0 + tolerance):
        low = float(array.min())
        high = float(array.max())
        raise ValueError(
            f"{name} must be normalized to [0, 1]; observed range [{low}, {high}]."
        )
    return np.clip(array, 0.0, 1.0)


def fuzzy_intersection(left: ArrayLike, right: ArrayLike) -> np.ndarray:
    """Return the component-wise fuzzy AND of two equal-length vectors."""
    left_array = np.asarray(left, dtype=np.float64).reshape(-1)
    right_array = np.asarray(right, dtype=np.float64).reshape(-1)
    if left_array.shape != right_array.shape:
        raise ValueError(
            f"Fuzzy intersection requires equal shapes; got "
            f"{left_array.shape} and {right_array.shape}."
        )
    return np.minimum(left_array, right_array)


def fuzzy_match(input_vector: ArrayLike, weight_vector: ArrayLike) -> float:
    """Compute ``|I ^ w| / |I|`` with a well-defined empty-channel case.

    Inactive channels are ignored through ``gamma``.  For an *active* scalar
    time cue, however, zero is also a legitimate globally normalized timestamp.
    Therefore a zero input matches a zero stored value, but not a nonzero one.
    This avoids 0/0 NaNs without turning the earliest timestamp into a wildcard.
    """
    input_array = np.asarray(input_vector, dtype=np.float64).reshape(-1)
    weight_array = np.asarray(weight_vector, dtype=np.float64).reshape(-1)
    if input_array.shape != weight_array.shape:
        raise ValueError(
            f"Match requires equal shapes; got {input_array.shape} and "
            f"{weight_array.shape}."
        )
    denominator = float(np.sum(np.abs(input_array)))
    if denominator <= _EPS:
        return 1.0 if float(np.sum(np.abs(weight_array))) <= _EPS else 0.0
    numerator = float(np.sum(fuzzy_intersection(input_array, weight_array)))
    return float(np.clip(numerator / denominator, 0.0, 1.0))


def fuzzy_choice(
    input_vector: ArrayLike,
    weight_vector: ArrayLike,
    alpha: float,
) -> float:
    """Compute the standard fuzzy ART choice value for one channel."""
    input_array = np.asarray(input_vector, dtype=np.float64).reshape(-1)
    weight_array = np.asarray(weight_vector, dtype=np.float64).reshape(-1)
    if input_array.shape != weight_array.shape:
        raise ValueError(
            f"Choice requires equal shapes; got {input_array.shape} and "
            f"{weight_array.shape}."
        )
    numerator = float(np.sum(fuzzy_intersection(input_array, weight_array)))
    denominator = float(alpha) + float(np.sum(np.abs(weight_array)))
    if denominator <= _EPS:
        return 0.0
    return numerator / denominator


def fuzzy_learn(
    input_vector: ArrayLike,
    weight_vector: ArrayLike,
    beta: float,
) -> np.ndarray:
    """Apply the standard fast/slow fuzzy ART learning rule."""
    input_array = np.asarray(input_vector, dtype=np.float64).reshape(-1)
    weight_array = np.asarray(weight_vector, dtype=np.float64).reshape(-1)
    if input_array.shape != weight_array.shape:
        raise ValueError(
            f"Learning requires equal shapes; got {input_array.shape} and "
            f"{weight_array.shape}."
        )
    beta_value = float(beta)
    if not 0.0 <= beta_value <= 1.0:
        raise ValueError(f"beta must be in [0, 1], got {beta_value}.")
    intersection = fuzzy_intersection(input_array, weight_array)
    return beta_value * intersection + (1.0 - beta_value) * weight_array


class FusionART:
    """A deterministic multi-channel Fusion ART network.

    Parameters mirror the constructor used in ARTEM's ``eventRetriever.py``.
    The network always keeps one uncommitted node initialized with all-one
    weights.  Committing that node automatically appends a fresh uncommitted
    node, matching the usual ART category-allocation mechanism.
    """

    SERIALIZATION_VERSION = 1

    def __init__(
        self,
        numspace: int,
        lengths: Sequence[int],
        beta: Sequence[float] | float,
        alpha: Sequence[float] | float,
        gamma: Sequence[float] | float,
        rho: Sequence[float] | float,
    ) -> None:
        self.numspace = int(numspace)
        if self.numspace <= 0:
            raise ValueError("numspace must be a positive integer.")

        self.lengths = self._expand_int_parameter(lengths, "lengths")
        if any(length <= 0 for length in self.lengths):
            raise ValueError(f"All channel lengths must be positive: {self.lengths}")

        self.beta = self._expand_float_parameter(beta, "beta")
        self.alpha = self._expand_float_parameter(alpha, "alpha")
        self.gamma = self._expand_float_parameter(gamma, "gamma")
        self.rho = self._expand_float_parameter(rho, "rho")

        if any(not 0.0 <= value <= 1.0 for value in self.beta):
            raise ValueError(f"All beta values must be in [0, 1]: {self.beta}")
        if any(value <= 0.0 for value in self.alpha):
            raise ValueError(f"All alpha values must be > 0: {self.alpha}")
        if any(value < 0.0 for value in self.gamma):
            raise ValueError(f"All gamma values must be >= 0: {self.gamma}")
        if any(not 0.0 <= value <= 1.0 for value in self.rho):
            raise ValueError(f"All rho values must be in [0, 1]: {self.rho}")

        self.activityF1: List[np.ndarray] = [
            np.zeros(length, dtype=np.float64) for length in self.lengths
        ]

        # These lists are deliberately public.  ARTEM directly calls
        # ``fa.matchValField[k](...)`` and ARTxtralib overrides channel models.
        self.choiceValField: List[FieldFunction] = []
        self.matchValField: List[FieldFunction] = []
        self.learnValField: List[Callable[[ArrayLike, ArrayLike], np.ndarray]] = []
        self.field_models: List[str] = ["fuzzy_art"] * self.numspace
        self._install_default_field_functions()

        self.codes: List[MutableMapping[str, Any]] = [self._new_uncommitted_code()]

        # Search diagnostics are useful for testing and do not affect learning.
        self.last_choice_values: List[float] = []
        self.last_match_values: dict[int, List[float]] = {}
        self.last_search_order: List[int] = []
        self.last_winner: Optional[int] = None

    def _expand_int_parameter(self, value: Sequence[int], name: str) -> List[int]:
        if isinstance(value, (str, bytes)):
            raise TypeError(f"{name} must be a sequence of integers.")
        result = [int(item) for item in value]
        if len(result) != self.numspace:
            raise ValueError(
                f"{name} must contain {self.numspace} values; got {len(result)}."
            )
        return result

    def _expand_float_parameter(
        self,
        value: Sequence[float] | float,
        name: str,
    ) -> List[float]:
        if np.isscalar(value):
            return [float(value)] * self.numspace
        result = [float(item) for item in value]
        if len(result) != self.numspace:
            raise ValueError(
                f"{name} must contain {self.numspace} values; got {len(result)}."
            )
        return result

    def _install_default_field_functions(self) -> None:
        self.choiceValField = []
        self.matchValField = []
        self.learnValField = []
        for channel in range(self.numspace):
            self._set_fuzzy_field_functions(channel)

    def _set_fuzzy_field_functions(self, channel: int) -> None:
        """Install standard fuzzy ART functions for one channel."""
        self._validate_channel_index(channel)
        alpha_value = self.alpha[channel]
        beta_value = self.beta[channel]

        choice = lambda input_vector, weight_vector, a=alpha_value: fuzzy_choice(
            input_vector, weight_vector, a
        )
        match = lambda input_vector, weight_vector: fuzzy_match(
            input_vector, weight_vector
        )
        learn = lambda input_vector, weight_vector, b=beta_value: fuzzy_learn(
            input_vector, weight_vector, b
        )

        if channel < len(self.choiceValField):
            self.choiceValField[channel] = choice
            self.matchValField[channel] = match
            self.learnValField[channel] = learn
        else:
            self.choiceValField.append(choice)
            self.matchValField.append(match)
            self.learnValField.append(learn)

    def set_field_model(self, channel: int, model: str = "fuzzy_art") -> None:
        """Configure a channel model while retaining ARTEM's public interface.

        ARTEM invokes ``ART2ACModelOverride`` for semantic channels.  The paper
        nevertheless defines their retrieval match with the fuzzy-intersection
        equation, so the compatibility model intentionally uses that published
        equation.  The model label is retained in serialized metadata.
        """
        self._validate_channel_index(channel)
        normalized_model = str(model).strip().lower().replace("-", "_")
        accepted = {"fuzzy_art", "fuzzy", "art2ac", "art2a_c", "art2a"}
        if normalized_model not in accepted:
            raise ValueError(
                f"Unsupported field model {model!r}; accepted values: "
                f"{sorted(accepted)}"
            )
        self._set_fuzzy_field_functions(channel)
        self.field_models[channel] = (
            "art2ac_paper_match" if normalized_model in {"art2ac", "art2a_c", "art2a"}
            else "fuzzy_art"
        )

    def _validate_channel_index(self, channel: int) -> None:
        if not 0 <= int(channel) < self.numspace:
            raise IndexError(
                f"Channel index {channel} is outside [0, {self.numspace - 1}]."
            )

    def _new_uncommitted_code(self) -> MutableMapping[str, Any]:
        return {
            "weights": [np.ones(length, dtype=np.float64) for length in self.lengths],
            "committed": False,
            "support": 0,
        }

    def _ensure_single_uncommitted_code(self) -> None:
        """Normalize loaded/modified state to exactly one trailing free node."""
        committed_codes = [code for code in self.codes if bool(code.get("committed", True))]
        self.codes = committed_codes + [self._new_uncommitted_code()]

    def setActivityF1(self, activity: Sequence[ArrayLike]) -> None:
        """Set the four-channel F1 input activity used by search and learning."""
        if len(activity) != self.numspace:
            raise ValueError(
                f"Expected {self.numspace} input channels, got {len(activity)}."
            )
        # Event vectors are expected in [0, 1], but retrieval-time temporal
        # cues can legitimately normalize outside the stored corpus range.
        # Keep such finite query values unchanged: they should simply fail the
        # vigilance/exact-time test rather than aborting the whole QA item.
        self.activityF1 = [
            _as_1d_finite_array(
                channel_value,
                self.lengths[channel],
                name=f"activityF1[{channel}]",
            ).copy()
            for channel, channel_value in enumerate(activity)
        ]

    # A snake_case alias helps external callers without changing official code.
    set_activity_f1 = setActivityF1

    def uncommitted(self, index: int) -> bool:
        """Return whether a recognition node is the uncommitted category."""
        if not 0 <= int(index) < len(self.codes):
            raise IndexError(f"Code index {index} is outside [0, {len(self.codes) - 1}].")
        return not bool(self.codes[int(index)].get("committed", True))

    def _choice_for_code(self, index: int) -> float:
        weights = self.codes[index]["weights"]
        total = 0.0
        for channel in range(self.numspace):
            gamma_value = self.gamma[channel]
            if gamma_value <= 0.0:
                continue
            total += gamma_value * self.choiceValField[channel](
                self.activityF1[channel], weights[channel]
            )
        return float(total)

    def _matches_for_code(self, index: int) -> List[float]:
        weights = self.codes[index]["weights"]
        return [
            float(
                self.matchValField[channel](
                    self.activityF1[channel], weights[channel]
                )
            )
            for channel in range(self.numspace)
        ]

    def resSearch(self) -> int:
        """Perform vigilance-guided resonance search and return the winner index."""
        if not self.codes:
            self.codes = [self._new_uncommitted_code()]
        if not any(not bool(code.get("committed", True)) for code in self.codes):
            self.codes.append(self._new_uncommitted_code())

        self.last_choice_values = [
            self._choice_for_code(index) for index in range(len(self.codes))
        ]
        self.last_match_values = {}
        self.last_search_order = []
        self.last_winner = None

        available = set(range(len(self.codes)))
        while available:
            # Deterministic tie break: lower recognition-node index wins.
            winner = max(
                available,
                key=lambda index: (self.last_choice_values[index], -index),
            )
            available.remove(winner)
            self.last_search_order.append(winner)

            if self.uncommitted(winner):
                self.last_match_values[winner] = [1.0] * self.numspace
                self.last_winner = winner
                return winner

            matches = self._matches_for_code(winner)
            self.last_match_values[winner] = matches
            resonance = all(
                self.gamma[channel] <= 0.0
                or matches[channel] + _EPS >= self.rho[channel]
                for channel in range(self.numspace)
            )
            if resonance:
                self.last_winner = winner
                return winner

        # This should only be reachable after malformed external state changes.
        self.codes.append(self._new_uncommitted_code())
        self.last_winner = len(self.codes) - 1
        return self.last_winner

    res_search = resSearch

    def autoLearn(self, winner: int) -> int:
        """Learn the current F1 activity at ``winner`` and return its index."""
        index = int(winner)
        if not 0 <= index < len(self.codes):
            raise IndexError(
                f"Winner index {winner} is outside [0, {len(self.codes) - 1}]."
            )

        # Learning is stricter than querying: only normalized event vectors may
        # be committed to STEM.  This catches malformed input even though
        # ``setActivityF1`` intentionally accepts out-of-corpus query times.
        normalized_activity = [
            _as_1d_float_array(
                self.activityF1[channel],
                self.lengths[channel],
                name=f"activityF1[{channel}] for learning",
            )
            for channel in range(self.numspace)
        ]

        code = self.codes[index]
        was_uncommitted = self.uncommitted(index)
        new_weights: List[np.ndarray] = []
        for channel in range(self.numspace):
            learned = self.learnValField[channel](
                normalized_activity[channel], code["weights"][channel]
            )
            learned_array = _as_1d_float_array(
                learned,
                self.lengths[channel],
                name=f"learned weights[{channel}]",
            )
            new_weights.append(learned_array.copy())

        code["weights"] = new_weights
        code["committed"] = True
        code["support"] = int(code.get("support", 0)) + 1

        if was_uncommitted:
            # A freshly committed category is followed by one free category.
            self.codes.append(self._new_uncommitted_code())
        else:
            self._ensure_single_uncommitted_code()

        self.last_winner = index
        return index

    auto_learn = autoLearn

    @property
    def committed_count(self) -> int:
        return sum(not self.uncommitted(index) for index in range(len(self.codes)))

    def to_state_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable network state."""
        return {
            "format": "fusionART-cleanroom",
            "version": self.SERIALIZATION_VERSION,
            "numspace": self.numspace,
            "lengths": list(self.lengths),
            "beta": list(self.beta),
            "alpha": list(self.alpha),
            "gamma": list(self.gamma),
            "rho": list(self.rho),
            "field_models": list(self.field_models),
            "activityF1": [channel.tolist() for channel in self.activityF1],
            "codes": [
                {
                    "weights": [
                        np.asarray(weight, dtype=np.float64).reshape(-1).tolist()
                        for weight in code["weights"]
                    ],
                    "committed": bool(code.get("committed", True)),
                    "support": int(code.get("support", 0)),
                }
                for code in self.codes
            ],
        }

    state_dict = to_state_dict

    def load_state_dict(self, state: Mapping[str, Any], *, strict: bool = True) -> None:
        """Load a state produced by :meth:`to_state_dict` into this object."""
        required = {"numspace", "lengths", "beta", "alpha", "gamma", "rho", "codes"}
        missing = required.difference(state)
        if missing:
            raise ValueError(f"Network state is missing fields: {sorted(missing)}")

        state_numspace = int(state["numspace"])
        state_lengths = [int(item) for item in state["lengths"]]
        if strict and (state_numspace != self.numspace or state_lengths != self.lengths):
            raise ValueError(
                "Network topology mismatch: file has "
                f"numspace={state_numspace}, lengths={state_lengths}; current network "
                f"has numspace={self.numspace}, lengths={self.lengths}."
            )

        # Reconfigure all scalar/list parameters from the saved model.  This is
        # useful even in strict mode because callers construct a blank network
        # and expect loadFusionARTNetwork to restore its training parameters.
        self.numspace = state_numspace
        self.lengths = state_lengths
        self.beta = [float(item) for item in state["beta"]]
        self.alpha = [float(item) for item in state["alpha"]]
        self.gamma = [float(item) for item in state["gamma"]]
        self.rho = [float(item) for item in state["rho"]]

        self.field_models = ["fuzzy_art"] * self.numspace
        self._install_default_field_functions()
        saved_models = list(state.get("field_models", []))
        for channel in range(self.numspace):
            if channel < len(saved_models) and str(saved_models[channel]).startswith("art2ac"):
                self.set_field_model(channel, "art2ac")

        loaded_codes: List[MutableMapping[str, Any]] = []
        for code_index, raw_code in enumerate(state["codes"]):
            raw_weights = raw_code.get("weights")
            if raw_weights is None or len(raw_weights) != self.numspace:
                raise ValueError(
                    f"Code {code_index} must contain {self.numspace} weight fields."
                )
            weights = [
                _as_1d_float_array(
                    raw_weights[channel],
                    self.lengths[channel],
                    name=f"codes[{code_index}].weights[{channel}]",
                ).copy()
                for channel in range(self.numspace)
            ]
            loaded_codes.append(
                {
                    "weights": weights,
                    "committed": bool(raw_code.get("committed", True)),
                    "support": int(raw_code.get("support", 0)),
                }
            )
        self.codes = loaded_codes
        self._ensure_single_uncommitted_code()

        raw_activity = state.get("activityF1")
        if raw_activity is not None:
            self.setActivityF1(raw_activity)
        else:
            self.activityF1 = [
                np.zeros(length, dtype=np.float64) for length in self.lengths
            ]

        self.last_choice_values = []
        self.last_match_values = {}
        self.last_search_order = []
        self.last_winner = None

    def __len__(self) -> int:
        """Return the number of committed recognition nodes."""
        return self.committed_count

    def __repr__(self) -> str:
        return (
            f"FusionART(numspace={self.numspace}, lengths={self.lengths}, "
            f"committed_codes={self.committed_count})"
        )


__all__ = [
    "FusionART",
    "fuzzy_choice",
    "fuzzy_intersection",
    "fuzzy_learn",
    "fuzzy_match",
]
