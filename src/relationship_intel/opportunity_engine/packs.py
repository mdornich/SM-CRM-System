"""Pure Product Pack protocol and registry. Packs receive facts, never DB handles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from relationship_intel.opportunity_engine.models import (
    Observation,
    Product,
    ProductPackVersion,
    ScoreDimensions,
    SignalDefinition,
    SignalObservation,
)


@dataclass(frozen=True)
class Assessment:
    signals: tuple[SignalObservation, ...]
    scores: ScoreDimensions
    classification: str
    eligible: bool
    reason: str
    scoring_version: str


class ProductPack(Protocol):
    product: Product
    version: ProductPackVersion
    definitions: tuple[SignalDefinition, ...]

    def assess(self, observations: tuple[Observation, ...]) -> Assessment: ...


def check_subject(observations: tuple[Observation, ...]) -> None:
    for field in ("account_id", "person_id"):
        subjects = {getattr(o, field) for o in observations} - {None}
        if len(subjects) > 1:
            raise ValueError("assess one resolved subject at a time")
    if len({o.id for o in observations}) != len(observations):
        raise ValueError("duplicate observation IDs")


class PackRegistry:
    def __init__(self):
        self._packs: dict[str, ProductPack] = {}

    def register(self, pack: ProductPack) -> None:
        if pack.version.id in self._packs:
            raise ValueError("Product Pack version already registered")
        if pack.version.product_id != pack.product.id:
            raise ValueError("pack product mismatch")
        if any(d.pack_version_id != pack.version.id for d in pack.definitions):
            raise ValueError("definition version mismatch")
        if len({d.id for d in pack.definitions}) != len(pack.definitions):
            raise ValueError("duplicate signal definition")
        if len({d.key for d in pack.definitions}) != len(pack.definitions):
            raise ValueError("duplicate signal key")
        self._packs[pack.version.id] = pack

    def get(self, version_id: str) -> ProductPack:
        return self._packs[version_id]
