"""JSON-file-backed mock CRM — fully functional today, implements the complete
interface (including get_pipeline_items) so the planner runs identically against
mock and real Twenty. Writes are skipped when content is unchanged, so a second
sync of unchanged data performs zero file writes (idempotency test 10)."""

from __future__ import annotations

import json
from pathlib import Path

from relationship_intel.crm.base import (
    AdapterStatus,
    CRMAdapter,
    CRMRef,
    NotePayload,
    PipelineItem,
    TaskPayload,
)


class MockCRMAdapter(CRMAdapter):
    provider = "mock"

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # -- storage helpers -------------------------------------------------------

    def _load(self, table: str) -> dict:
        path = self.root / f"{table}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _save(self, table: str, data: dict) -> None:
        path = self.root / f"{table}.json"
        content = json.dumps(data, indent=2, sort_keys=True) + "\n"
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")

    def _find_or_create(self, table: str, key: str, record: dict) -> tuple[CRMRef, bool]:
        data = self._load(table)
        created = key not in data
        if created:
            record = dict(record, id=f"{table}-{len(data) + 1}")
            data[key] = record
            self._save(table, data)
        else:
            merged = {**record, **{k: v for k, v in data[key].items() if v is not None}}
            merged["id"] = data[key]["id"]
            if merged != data[key]:
                data[key] = merged
                self._save(table, data)
        return CRMRef(self.provider, table.rstrip("s"), data[key]["id"]), created

    # -- interface -------------------------------------------------------------

    def find_or_create_contact(self, person: dict) -> CRMRef:
        key = (person.get("email") or person["name"]).lower()
        ref, _ = self._find_or_create("people", key, person)
        return ref

    def find_or_create_company(self, company: dict) -> CRMRef:
        key = (company.get("domain") or company["name"]).lower()
        ref, _ = self._find_or_create("companies", key, company)
        return ref

    def find_contact(self, person: dict) -> dict | None:
        # Read-only dedup lookup for the review UI (gh #15).
        email = (person.get("email") or "").lower()
        name = (person.get("name") or "").lower()
        for record in self._load("people").values():
            record_email = (record.get("email") or "").lower()
            record_name = (record.get("name") or "").lower()
            if email and record_email == email:
                return _existing_person_dict(record)
            if not email and name and record_name == name:
                return _existing_person_dict(record)
        return None

    def find_company(self, company: dict) -> dict | None:
        domain = (company.get("domain") or "").lower()
        name = (company.get("name") or "").lower()
        for record in self._load("companies").values():
            record_domain = (record.get("domain") or "").lower()
            record_name = (record.get("name") or "").lower()
            if domain and record_domain == domain:
                return _existing_company_dict(record)
            if not domain and name and record_name == name:
                return _existing_company_dict(record)
        return None

    def create_or_update_opportunity(self, opportunity: dict) -> CRMRef:
        key = opportunity["name"].lower()
        data = self._load("opportunities")
        if key in data:
            updated = {**data[key], **opportunity, "id": data[key]["id"]}
            if updated != data[key]:
                data[key] = updated
                self._save("opportunities", data)
            return CRMRef(self.provider, "opportunity", data[key]["id"])
        record = dict(opportunity, id=f"opportunities-{len(data) + 1}")
        data[key] = record
        self._save("opportunities", data)
        return CRMRef(self.provider, "opportunity", record["id"])

    def attach_note(self, ref: CRMRef, note: NotePayload) -> CRMRef:
        data = self._load("notes")
        key = f"{ref.object_type}:{ref.crm_id}:{note.title}".lower()
        if key not in data:
            data[key] = {
                "id": f"notes-{len(data) + 1}",
                "target": ref.crm_id,
                "title": note.title,
                "body": note.body,
            }
            self._save("notes", data)
        elif data[key]["body"] != note.body:
            # Re-delivery after a profile change updates the note in place.
            data[key]["body"] = note.body
            self._save("notes", data)
        return CRMRef(self.provider, "note", data[key]["id"])

    def create_task(self, ref: CRMRef, task: TaskPayload) -> CRMRef:
        data = self._load("tasks")
        key = f"{ref.object_type}:{ref.crm_id}:{task.title}".lower()
        if key not in data:
            data[key] = {
                "id": f"tasks-{len(data) + 1}",
                "target": ref.crm_id,
                "title": task.title,
                "body": task.body,
                "due_window": task.due_window,
                "assignee": task.assignee,
                "status": "TODO",
            }
            self._save("tasks", data)
        elif (
            data[key]["body"] != task.body
            or data[key]["due_window"] != task.due_window
            or data[key]["assignee"] != task.assignee
        ):
            # Re-delivery with the same title updates the task in place,
            # mirroring attach_note.
            data[key].update(body=task.body, due_window=task.due_window, assignee=task.assignee)
            self._save("tasks", data)
        return CRMRef(self.provider, "task", data[key]["id"])

    def tag_record(self, ref: CRMRef, tags: list[str]) -> None:
        data = self._load("tags")
        key = f"{ref.object_type}:{ref.crm_id}"
        existing = set(data.get(key, []))
        merged = sorted(existing | set(tags))
        if merged != data.get(key):
            data[key] = merged
            self._save("tags", data)

    def get_pipeline_items(self, owner: str | None = None) -> list[PipelineItem]:
        items = []
        for record in self._load("opportunities").values():
            if owner and record.get("owner") and record["owner"] != owner:
                continue
            items.append(
                PipelineItem(
                    person_name=record.get("person_name", ""),
                    company_name=record.get("company_name"),
                    stage=record.get("stage", "new"),
                    lead_type=record.get("lead_type", "unknown"),
                    succession_signal_score=int(record.get("succession_signal_score", 0)),
                    urgency=record.get("urgency", "unknown"),
                    timing_window=record.get("timing_window", "unknown"),
                    next_action=record.get("next_action"),
                    next_action_due=record.get("next_action_due"),
                    crm_ref=CRMRef(self.provider, "opportunity", record["id"]),
                )
            )
        return items

    def health_check(self) -> AdapterStatus:
        return AdapterStatus(ok=True, detail=f"mock store at {self.root}")


def _existing_person_dict(record: dict) -> dict:
    return {
        "crm_id": record["id"],
        "url": None,
        "name": record.get("name"),
        "email": record.get("email"),
        "company_name": record.get("company_name"),
    }


def _existing_company_dict(record: dict) -> dict:
    return {
        "crm_id": record["id"],
        "url": None,
        "name": record.get("name"),
        "domain": record.get("domain"),
    }
