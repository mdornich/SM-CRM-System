"""Validated immutable writes over the existing SQLite connection.

Use a dedicated connection from store.db.connect. Each put is atomic; transaction()
composes a whole evidence-to-hypothesis batch with rollback on any failure.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

from relationship_intel.opportunity_engine.models import (
    Evidence,
    Observation,
    OpportunityHypothesis,
    Product,
    ProductPackVersion,
    Record,
    SignalDefinition,
    SignalObservation,
)

_TABLES = {
    Product: "oe_products",
    ProductPackVersion: "oe_pack_versions",
    Evidence: "oe_evidence",
    Observation: "oe_observations",
    SignalDefinition: "oe_signal_definitions",
    SignalObservation: "oe_signal_observations",
    OpportunityHypothesis: "oe_hypotheses",
}
_JSON_FIELDS = {"policy", "value", "scores"}


class OpportunityRepository:
    def __init__(self, conn: sqlite3.Connection):
        if not conn.execute("PRAGMA foreign_keys").fetchone()[0]:
            raise ValueError("foreign keys must be enabled")
        self.conn = conn

    @contextmanager
    def transaction(self):
        self.conn.execute("SAVEPOINT oe_write")
        try:
            yield self
            self.conn.execute("RELEASE SAVEPOINT oe_write")
        except Exception:
            self.conn.execute("ROLLBACK TO SAVEPOINT oe_write")
            self.conn.execute("RELEASE SAVEPOINT oe_write")
            raise

    def get(self, model: type[Record], record_id: str):
        table = _TABLES[model]
        row = self.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(f"missing {model.__name__}: {record_id}")
        data = dict(row)
        for key in _JSON_FIELDS & data.keys():
            data[key] = json.loads(data[key])
        if model is OpportunityHypothesis:
            data["signal_ids"] = [
                r[0]
                for r in self.conn.execute(
                    "SELECT signal_id FROM oe_hypothesis_signals "
                    "WHERE hypothesis_id = ? ORDER BY position",
                    (record_id,),
                )
            ]
        if model is OpportunityHypothesis:
            data["observation_ids"] = [
                r[0]
                for r in self.conn.execute(
                    "SELECT observation_id FROM oe_hypothesis_observations "
                    "WHERE hypothesis_id = ? ORDER BY position",
                    (record_id,),
                )
            ]
        return model.model_validate(data)

    def put(self, record: Record) -> str:
        # Revalidate even model_construct/model_copy inputs at the persistence boundary.
        model = type(record)
        table = _TABLES[model]
        record = model.model_validate(record.model_dump(mode="json"))
        with self.transaction():
            try:
                prior = self.get(model, record.id)
            except KeyError:
                prior = None
            if prior is not None:
                if prior != record:
                    raise ValueError("immutable ID conflict; use a new version or record ID")
                return record.id
            if isinstance(record, Observation):
                source = self.get(Evidence, record.evidence_id)
                if record.predicate == "statement" and (
                    not isinstance(record.value, str) or record.value not in source.excerpt
                ):
                    raise ValueError("statement must occur in the source excerpt")
            if isinstance(record, OpportunityHypothesis):
                self._validate_hypothesis(record)
            data = record.model_dump(mode="json", exclude={"signal_ids", "observation_ids"})
            for key in _JSON_FIELDS & data.keys():
                data[key] = json.dumps(data[key], sort_keys=True, allow_nan=False)
            columns = ", ".join(data)
            placeholders = ", ".join("?" for _ in data)
            self.conn.execute(
                f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(data.values())
            )
            if isinstance(record, OpportunityHypothesis):
                self.conn.executemany(
                    "INSERT INTO oe_hypothesis_signals VALUES (?, ?, ?)",
                    [(record.id, signal, i) for i, signal in enumerate(record.signal_ids)],
                )
                self.conn.executemany(
                    "INSERT INTO oe_hypothesis_observations VALUES (?, ?, ?)",
                    [(record.id, oid, i) for i, oid in enumerate(record.observation_ids)],
                )
        return record.id

    def _validate_hypothesis(self, hypothesis: OpportunityHypothesis):
        self.get(ProductPackVersion, hypothesis.pack_version_id)
        for signal_id in hypothesis.signal_ids:
            signal = self.get(SignalObservation, signal_id)
            definition = self.get(SignalDefinition, signal.definition_id)
            if signal.observation_id not in hypothesis.observation_ids:
                raise ValueError("signal must cite a supporting observation")
            if definition.pack_version_id != hypothesis.pack_version_id:
                raise ValueError("signal belongs to a different Product Pack version")
        for observation_id in hypothesis.observation_ids:
            observation = self.get(Observation, observation_id)
            # An account-only fact can support a person+account hypothesis. An
            # attributed person fact cannot silently support someone else's hypothesis.
            for field in ("account_id", "person_id"):
                subject = getattr(observation, field)
                if subject is not None and subject != getattr(hypothesis, field):
                    raise ValueError("signal subject does not match hypothesis")

    def hypotheses(self, *, account_id: int | None = None, person_id: int | None = None):
        clauses, values = [], []
        for field, value in (("account_id", account_id), ("person_id", person_id)):
            if value is not None:
                clauses.append(f"{field} = ?")
                values.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.conn.execute("SELECT id FROM oe_hypotheses" + where + " ORDER BY id", values)
        return [self.get(OpportunityHypothesis, row[0]) for row in rows.fetchall()]
