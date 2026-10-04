from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from sts.state.models import ClaimThreadFeature
from sts.graph.types import Claim


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")
_STOP_WORDS = {
    "and",
    "about",
    "after",
    "again",
    "also",
    "answer",
    "april",
    "august",
    "been",
    "before",
    "being",
    "caroline",
    "could",
    "december",
    "february",
    "from",
    "have",
    "into",
    "january",
    "july",
    "june",
    "march",
    "maya",
    "melanie",
    "more",
    "may",
    "november",
    "october",
    "question",
    "said",
    "september",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "they",
    "this",
    "through",
    "told",
    "very",
    "what",
    "when",
    "where",
    "which",
    "while",
    "with",
    "would",
}


def _normalize_term(value: str) -> str:
    return " ".join(value.casefold().split())


@dataclass(frozen=True)
class StateIdentity:
    subject: str | None
    dimension: str
    topic_terms: tuple[str, ...]
    title: str
    coverage: float
    separation: float
    is_mixed: bool
    representative_claim_ids: tuple[str, ...]


class StateIdentityBuilder:
    """Build a sibling-aware identity from frozen State membership."""

    def build(
        self,
        communities: Sequence[set[str]],
        claims: Mapping[str, Claim],
        features: Mapping[str, ClaimThreadFeature],
        content_vectors: Mapping[str, np.ndarray],
    ) -> list[StateIdentity]:
        candidate_claims = [
            self._candidate_claims(community, claims, features)
            for community in communities
        ]
        document_frequency = Counter()
        for per_claim in candidate_claims:
            document_frequency.update(
                set().union(*per_claim.values()) if per_claim else set()
            )

        identities = []
        state_count = len(communities)
        for index, community in enumerate(communities):
            per_claim = candidate_claims[index]
            coverage_by_term: dict[str, set[str]] = defaultdict(set)
            keyword_terms = set()
            for claim_id, terms in per_claim.items():
                for term in terms:
                    coverage_by_term[term].add(claim_id)
                keyword_terms.update(
                    _normalize_term(term)
                    for term in (claims[claim_id].keywords or [])
                    if term
                )

            scored_terms = []
            for term, covered_claims in coverage_by_term.items():
                coverage = len(covered_claims) / max(len(community), 1)
                sibling_idf = math.log(
                    (state_count + 1)
                    / (document_frequency[term] + 1)
                ) + 1.0
                keyword_boost = 1.75 if term in keyword_terms else 1.0
                scored_terms.append(
                    (coverage * sibling_idf * keyword_boost, term)
                )
            scored_terms.sort(key=lambda item: (-item[0], item[1]))
            topic_terms = self._select_terms(scored_terms)
            if not topic_terms:
                topic_terms = ("claim thread",)

            coverage = max(
                (
                    len(coverage_by_term.get(term, set()))
                    / max(len(community), 1)
                    for term in topic_terms
                ),
                default=0.0,
            )
            sibling_terms = [
                set().union(*candidate_claims[sibling].values())
                if candidate_claims[sibling]
                else set()
                for sibling in range(state_count)
                if sibling != index
            ]
            selected = set(topic_terms)
            max_overlap = max(
                (
                    len(selected & sibling)
                    / max(len(selected | sibling), 1)
                    for sibling in sibling_terms
                ),
                default=0.0,
            )
            separation = 1.0 - max_overlap
            subject = self._subject(community, claims, features)
            dimension = " / ".join(topic_terms)
            title = (
                f"{subject} · {dimension}" if subject else dimension
            )
            representatives = self._representatives(
                community, content_vectors
            )
            identities.append(
                StateIdentity(
                    subject=subject,
                    dimension=dimension,
                    topic_terms=topic_terms,
                    title=title,
                    coverage=coverage,
                    separation=separation,
                    is_mixed=len(community) >= 4 and coverage < 0.5,
                    representative_claim_ids=representatives,
                )
            )
        return identities

    def _candidate_claims(
        self,
        community: set[str],
        claims: Mapping[str, Claim],
        features: Mapping[str, ClaimThreadFeature],
    ) -> dict[str, set[str]]:
        result = {}
        for claim_id in community:
            claim = claims[claim_id]
            excluded = set(features[claim_id].participants)
            keyword_terms = {
                _normalize_term(term)
                for term in claim.keywords or []
                if self._valid_term(term, excluded)
            }
            terms = set(keyword_terms)
            terms.update(features[claim_id].topic_entities)
            if not terms:
                terms.update(
                    token.casefold()
                    for token in _TOKEN_RE.findall(claim.content)
                    if self._valid_term(token, excluded)
                )
            result[claim_id] = terms
        return result

    @staticmethod
    def _valid_term(term: str, excluded: set[str]) -> bool:
        normalized = _normalize_term(term)
        return bool(
            normalized
            and normalized not in excluded
            and normalized not in _STOP_WORDS
            and not any(character.isdigit() for character in normalized)
            and not any(
                token in _STOP_WORDS
                for token in normalized.split()
            )
        )

    @staticmethod
    def _select_terms(
        scored_terms: list[tuple[float, str]],
    ) -> tuple[str, ...]:
        selected = []
        for _, term in scored_terms:
            term_tokens = set(term.split())
            if any(
                term_tokens <= set(existing.split())
                or set(existing.split()) <= term_tokens
                for existing in selected
            ):
                continue
            selected.append(term)
            if len(selected) == 3:
                break
        return tuple(selected)

    @staticmethod
    def _subject(
        community: set[str],
        claims: Mapping[str, Claim],
        features: Mapping[str, ClaimThreadFeature],
    ) -> str | None:
        mentions = Counter()
        display = {}
        for claim_id in community:
            content = claims[claim_id].content.casefold()
            for participant in features[claim_id].participants:
                if "_" in participant or any(
                    character.isdigit() for character in participant
                ):
                    continue
                count = len(
                    re.findall(rf"\b{re.escape(participant)}\b", content)
                )
                if count:
                    mentions[participant] += count
                    display[participant] = participant.title()
        if not mentions:
            return None
        subject, _ = mentions.most_common(1)[0]
        return display[subject]

    @staticmethod
    def _representatives(
        community: set[str],
        content_vectors: Mapping[str, np.ndarray],
    ) -> tuple[str, ...]:
        claim_ids = sorted(community)
        if len(claim_ids) <= 4:
            return tuple(claim_ids)
        matrix = np.asarray(
            [content_vectors[claim_id] for claim_id in claim_ids],
            dtype=float,
        )
        centroid = matrix.mean(axis=0)
        norm = np.linalg.norm(centroid)
        if norm:
            centroid = centroid / norm
        ranked = sorted(
            zip(claim_ids, matrix @ centroid),
            key=lambda item: (-float(item[1]), item[0]),
        )
        return tuple(claim_id for claim_id, _ in ranked[:4])
    "december",
    "february",
    "january",
    "july",
    "june",
    "march",
    "november",
    "october",
    "september",
    "the",
