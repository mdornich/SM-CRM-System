"""Local human-in-the-loop CRM review UI.

This is intentionally small and stdlib-only: a local browser form over the
SQLite review queue. The page groups extracted facts by person so the operator
can review a relationship candidate, edit the proposed CRM fields, and approve
only the records that should land in Twenty.
"""

from __future__ import annotations

import html
from collections.abc import Iterable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from relationship_intel.config import Settings
from relationship_intel.crm.sync import sync_to_crm
from relationship_intel.pipeline import make_adapter, open_repo, rebuild_review_queue
from relationship_intel.store.models import CRMReviewItem

STATUSES = ("pending", "approved", "rejected", "obsidian_only")
FINAL_STATUSES = ("approved", "rejected", "obsidian_only")
STATUS_LABELS = {
    "pending": "Needs review",
    "approved": "Send to Twenty",
    "rejected": "Reject",
    "obsidian_only": "Keep in vault only",
}
CRM_OBJECT_LABELS = {
    "company": "Company",
    "person": "Contact",
    "person_note": "Relationship note",
    "person_task": "Follow-up task",
    "opportunity": "Opportunity",
}
FIELD_LABELS = {
    "body": "Note",
    "company_id": "Company ID",
    "company_name": "Company",
    "domain": "Domain",
    "due_window": "Due window",
    "email": "Email",
    "industry": "Industry",
    "lead_type": "Lead type",
    "name": "Name",
    "next_action": "Next action",
    "next_action_due": "Next action due",
    "owner": "Owner",
    "person_id": "Person ID",
    "phone": "Phone",
    "stage": "Stage",
    "succession_signal_score": "Signal score",
    "timing_window": "Timing",
    "title": "Title",
    "urgency": "Urgency",
}
FIELD_ORDER = (
    "name",
    "company_name",
    "title",
    "email",
    "phone",
    "domain",
    "industry",
    "stage",
    "lead_type",
    "succession_signal_score",
    "urgency",
    "timing_window",
    "next_action",
    "next_action_due",
    "due_window",
    "owner",
    "body",
)


def review_summary(settings: Settings) -> dict:
    repo = open_repo(settings)
    rebuild_review_queue(repo)
    items = repo.review_items()
    by_status = {status: 0 for status in STATUSES}
    for item in items:
        by_status[item.status] = by_status.get(item.status, 0) + 1
    return {"count": len(items), "by_status": by_status}


def serve_review_ui(settings: Settings, host: str = "127.0.0.1", port: int = 8765) -> None:
    repo = open_repo(settings)
    rebuild_review_queue(repo)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib hook
            parsed = urlparse(self.path)
            if parsed.path != "/":
                self.send_error(404)
                return
            self._send_html(_render_page(settings))

        def do_POST(self) -> None:  # noqa: N802 - stdlib hook
            length = int(self.headers.get("content-length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            form = parse_qs(body)
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/item":
                    _handle_item(settings, form)
                    self._redirect("/")
                elif parsed.path == "/bundle":
                    changed, sync_stats = _handle_bundle(settings, form)
                    message = f"Updated {changed} review items."
                    if sync_stats is not None:
                        message += f" Pushed to Twenty: {sync_stats}"
                    self._send_html(_render_page(settings, message=message))
                elif parsed.path == "/sync":
                    stats = _handle_sync(settings)
                    self._send_html(_render_page(settings, message=f"Synced: {stats}"))
                else:
                    self.send_error(404)
            except Exception as exc:  # noqa: BLE001 - local operator UI
                self._send_html(_render_page(settings, error=str(exc)), status=400)

        def log_message(self, fmt: str, *args) -> None:
            return

        def _redirect(self, location: str) -> None:
            self.send_response(303)
            self.send_header("Location", location)
            self.end_headers()

        def _send_html(self, content: str, status: int = 200) -> None:
            data = content.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Review UI running at http://{host}:{port}/")
    server.serve_forever()


def _handle_item(settings: Settings, form: dict[str, list[str]]) -> None:
    object_type = _one(form, "object_type")
    local_id = int(_one(form, "local_id"))
    status = _one(form, "status")
    if status not in STATUSES:
        raise ValueError(f"Unsupported status: {status}")
    payload = _payload_from_form(form)
    repo = open_repo(settings)
    repo.set_review_item(object_type, local_id, status, payload)


def _handle_bundle(settings: Settings, form: dict[str, list[str]]) -> tuple[int, dict | None]:
    status = _one(form, "status")
    if status not in FINAL_STATUSES:
        raise ValueError(f"Unsupported bundle status: {status}")
    # Push-on-approve: any Approve bundle click also fires sync to CRM for the
    # newly-approved subset (see docs/architecture.md §Human Approval; Option 1
    # of gh issue #6). Rejected / vault-only bundles never push.
    push_on_approve = _one_or_default(form, "push", "on") in {"on", "true", "1"}
    repo = open_repo(settings)
    changed = 0
    for raw in form.get("item", []):
        object_type, raw_id = raw.split(":", 1)
        local_id = int(raw_id)
        item = repo.review_item(object_type, local_id)
        if not item:
            continue
        repo.set_review_item(object_type, local_id, status, item.payload)
        changed += 1
    sync_stats: dict | None = None
    if status == "approved" and push_on_approve and changed > 0:
        sync_stats = _handle_sync(settings)
    return changed, sync_stats


def _one_or_default(form: dict[str, list[str]], key: str, default: str) -> str:
    values = form.get(key)
    return values[0] if values else default


def _handle_sync(settings: Settings) -> dict:
    repo = open_repo(settings)
    adapter = make_adapter(settings)
    return sync_to_crm(repo, adapter, settings.default_owner, approved_only=True)


def _one(form: dict[str, list[str]], key: str) -> str:
    values = form.get(key)
    if not values:
        raise ValueError(f"Missing form field: {key}")
    return values[0]


def _render_page(settings: Settings, message: str | None = None, error: str | None = None) -> str:
    repo = open_repo(settings)
    rebuild_review_queue(repo)
    items = repo.review_items()
    item_map = {(item.object_type, item.local_id): item for item in items}
    people = repo.people_records()
    companies = {company.id: company for company in repo.company_records()}
    opportunities = repo.opportunity_records()
    opportunities_by_person = {}
    for opp in opportunities:
        if opp.person_id is not None:
            opportunities_by_person.setdefault(opp.person_id, []).append(opp)
    linked_company_ids = {person.company_id for person in people if person.company_id is not None}

    person_rows = "\n".join(
        _render_person_bundle(
            person,
            item_map,
            companies,
            opportunities_by_person.get(person.id, []),
        )
        for person in people
        if ("person", person.id) in item_map
    )
    standalone_orgs = "\n".join(
        _render_standalone_company(item_map[("company", company.id)], company)
        for company in companies.values()
        if company.id not in linked_company_ids and ("company", company.id) in item_map
    )
    unlinked_opps = "\n".join(
        _render_standalone_opportunity(item_map[("opportunity", opp.id)], opp)
        for opp in opportunities
        if opp.person_id is None and ("opportunity", opp.id) in item_map
    )

    status_counts = {status: 0 for status in STATUSES}
    for item in items:
        status_counts[item.status] = status_counts.get(item.status, 0) + 1

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Relationship Intel Review</title>
  <style>{_css()}</style>
</head>
<body>
  <header class="topbar">
    <div>
      <p class="eyebrow">Human review gate</p>
      <h1>Relationship Intel Review</h1>
      <p class="summary">{_render_counts(status_counts)}</p>
    </div>
    <form method="post" action="/sync">
      <button class="primary" type="submit">Sync approved to Twenty</button>
    </form>
  </header>
  {f'<div class="message">{html.escape(message)}</div>' if message else ""}
  {f'<div class="error">{html.escape(error)}</div>' if error else ""}
  <main>
    <section class="queue">
      <div class="section-head">
        <h2>Extracted people</h2>
        <span>{len(people)} candidates</span>
      </div>
      {person_rows or '<p class="empty">No people are waiting for review.</p>'}
    </section>
    <section class="queue">
      <div class="section-head">
        <h2>Standalone organizations</h2>
        <span>not attached to a person</span>
      </div>
      {standalone_orgs or '<p class="empty">No standalone companies or organizations.</p>'}
    </section>
    <section class="queue">
      <div class="section-head">
        <h2>Unlinked opportunities</h2>
        <span>not attached to a person</span>
      </div>
      {unlinked_opps or '<p class="empty">No unlinked opportunities.</p>'}
    </section>
  </main>
</body>
</html>"""


def _render_person_bundle(person, item_map: dict, companies: dict, opportunities: list) -> str:
    person_item = item_map.get(("person", person.id))
    if not person_item:
        return ""
    company = companies.get(person.company_id) if person.company_id else None
    company_item = item_map.get(("company", person.company_id)) if person.company_id else None
    note_item = item_map.get(("person_note", person.id))
    task_item = item_map.get(("person_task", person.id))
    opportunity_items = [
        item_map[("opportunity", opp.id)]
        for opp in opportunities
        if ("opportunity", opp.id) in item_map
    ]
    review_items = [
        item
        for item in (person_item, company_item, note_item, task_item, *opportunity_items)
        if item
    ]
    profile = person.profile or {}
    company_name = person.company_name or person_item.payload.get("company_name") or "No company"
    headline = _person_headline(person, company, profile)
    warnings = _render_warnings(item.reason for item in review_items)
    crm_preview = _render_crm_preview(review_items)
    evidence = _render_evidence(person.evidence, person.transcripts)
    fields = "\n".join(
        _render_review_item(item, compact=item.object_type in {"person", "company"})
        for item in review_items
    )
    bundle_inputs = "\n".join(
        f'<input type="hidden" name="item" value="{html.escape(item.object_type)}:{item.local_id}">'
        for item in review_items
    )

    return f"""<article class="candidate">
  <div class="candidate-main">
    <div class="candidate-id">
      <h3>{html.escape(person.name)}</h3>
      <p>{html.escape(company_name)}{headline}</p>
    </div>
    <div class="candidate-status">
      {_status_pill(person_item.status)}
    </div>
  </div>
  <div class="candidate-grid">
    <div>
      <dl class="facts">
        {_fact("Title", person.title)}
        {_fact("Email", person.email)}
        {_fact("Lead type", profile.get("lead_type"))}
        {_fact("Stage", profile.get("stage"))}
        {_fact("Score", profile.get("succession_signal_score"))}
        {_fact("Timing", profile.get("timing_window"))}
        {_fact("Next action", profile.get("next_best_action"))}
      </dl>
      {warnings}
      {evidence}
    </div>
    <aside class="preview">
      <h4>Twenty write preview</h4>
      {crm_preview}
      <form class="bundle-actions" method="post" action="/bundle">
        {bundle_inputs}
        <button class="primary" name="status" value="approved" type="submit">
          Approve &amp; push to Twenty
        </button>
        <button name="status" value="obsidian_only" type="submit">Vault only</button>
        <button name="status" value="rejected" type="submit">Reject all</button>
      </form>
    </aside>
  </div>
  <details class="edit-panel">
    <summary>Edit proposed fields</summary>
    <div class="review-items">{fields}</div>
  </details>
</article>"""


def _render_standalone_company(item: CRMReviewItem, company) -> str:
    summary = _fact("Industry", company.industry) + _fact("Domain", company.domain)
    return f"""<article class="candidate slim">
  <div class="candidate-main">
    <div class="candidate-id">
      <h3>{html.escape(company.name)}</h3>
      <p>Standalone organization</p>
    </div>
    <div class="candidate-status">{_status_pill(item.status)}</div>
  </div>
  <dl class="facts">{summary}</dl>
  {_render_review_item(item, compact=True)}
</article>"""


def _render_standalone_opportunity(item: CRMReviewItem, opp) -> str:
    return f"""<article class="candidate slim">
  <div class="candidate-main">
    <div class="candidate-id">
      <h3>{html.escape(opp.name)}</h3>
      <p>{html.escape(opp.stage)} · {html.escape(opp.lead_type)}</p>
    </div>
    <div class="candidate-status">{_status_pill(item.status)}</div>
  </div>
  {_render_review_item(item)}
</article>"""


def _person_headline(person, company, profile: dict) -> str:
    parts = []
    if person.title:
        parts.append(person.title)
    if company and company.industry:
        parts.append(company.industry)
    lead = profile.get("lead_type")
    if lead:
        parts.append(str(lead).replace("_", " "))
    return f" · {html.escape(' · '.join(parts))}" if parts else ""


def _render_counts(status_counts: dict[str, int]) -> str:
    return " · ".join(
        f"{html.escape(STATUS_LABELS[status])}: {status_counts.get(status, 0)}"
        for status in STATUSES
    )


def _render_warnings(reasons: Iterable[str | None]) -> str:
    unique = []
    for reason in reasons:
        if reason and reason not in unique:
            unique.append(reason)
    if not unique:
        return '<div class="clean">No review warnings.</div>'
    return (
        '<ul class="warnings">'
        + "".join(f"<li>{html.escape(reason)}</li>" for reason in unique)
        + "</ul>"
    )


def _render_evidence(evidence: list[str], transcripts: list[tuple[str | None, str, str]]) -> str:
    if not evidence and not transcripts:
        return ""
    snippets = "".join(f"<li>{html.escape(snippet)}</li>" for snippet in evidence[:3])
    transcript_rows = "".join(
        f"<li>{html.escape(date or 'No date')} · {html.escape(title)}</li>"
        for date, title, _hash in transcripts[:3]
    )
    return f"""<details class="evidence">
  <summary>Evidence and source transcript</summary>
  {"<ul>" + snippets + "</ul>" if snippets else ""}
  {'<ul class="source-list">' + transcript_rows + "</ul>" if transcript_rows else ""}
</details>"""


def _render_crm_preview(items: list[CRMReviewItem]) -> str:
    rows = []
    for item in items:
        label = CRM_OBJECT_LABELS.get(item.object_type, item.object_type)
        rows.append(f"<li><span>{html.escape(label)}</span>{_status_pill(item.status)}</li>")
    return '<ul class="write-preview">' + "".join(rows) + "</ul>"


def _render_review_item(item: CRMReviewItem, compact: bool = False) -> str:
    status_options = "\n".join(
        f'<option value="{status}" {"selected" if status == item.status else ""}>'
        f"{html.escape(STATUS_LABELS[status])}</option>"
        for status in STATUSES
    )
    fields = _render_payload_fields(item.payload, compact=compact)
    title = CRM_OBJECT_LABELS.get(item.object_type, item.object_type)
    reason = f'<p class="reason">{html.escape(item.reason)}</p>' if item.reason else ""
    return f"""<form class="review-item" method="post" action="/item">
  <input type="hidden" name="object_type" value="{html.escape(item.object_type)}">
  <input type="hidden" name="local_id" value="{item.local_id}">
  <div class="review-item-head">
    <div>
      <h4>{html.escape(title)}</h4>
      <p>{html.escape(item.label)}</p>
      {reason}
    </div>
    <label>Status <select name="status">{status_options}</select></label>
  </div>
  <div class="fields">{fields}</div>
  <button type="submit">Save {html.escape(title.lower())}</button>
</form>"""


def _render_payload_fields(payload: dict, compact: bool = False) -> str:
    rows = []
    for key in _ordered_keys(payload):
        value = payload[key]
        label = FIELD_LABELS.get(key, _human_label(key))
        value_type = _value_type(value)
        value_text = "" if value is None else str(value)
        readonly = key.endswith("_id") or key in {"company_id", "person_id"}
        rows.append(
            f'<input type="hidden" name="field" value="{html.escape(key)}">'
            f'<input type="hidden" name="type__{html.escape(key)}" value="{value_type}">'
        )
        if key in {"body", "description"} or len(value_text) > 110:
            rows.append(
                f'<div class="field wide"><label>{html.escape(label)}</label>'
                f'<textarea name="value__{html.escape(key)}">{html.escape(value_text)}</textarea>'
                "</div>"
            )
        else:
            rows.append(
                f'<div class="field{" compact" if compact else ""}">'
                f"<label>{html.escape(label)}</label>"
                f'<input type="text" name="value__{html.escape(key)}" '
                f'value="{html.escape(value_text)}" {"readonly" if readonly else ""}></div>'
            )
    return "\n".join(rows)


def _ordered_keys(payload: dict) -> list[str]:
    ordered = [key for key in FIELD_ORDER if key in payload]
    ordered.extend(sorted(key for key in payload if key not in ordered))
    return ordered


def _fact(label: str, value) -> str:
    text = "Unknown" if value in (None, "") else str(value)
    return f"<div><dt>{html.escape(label)}</dt><dd>{html.escape(text)}</dd></div>"


def _status_pill(status: str) -> str:
    css_status = html.escape(status.replace("_", "-"))
    return (
        f'<span class="pill {css_status}">{html.escape(STATUS_LABELS.get(status, status))}</span>'
    )


def _payload_from_form(form: dict[str, list[str]]) -> dict:
    payload = {}
    for key in form.get("field", []):
        raw_value = _one(form, f"value__{key}")
        value_type = _one(form, f"type__{key}")
        payload[key] = _coerce_value(raw_value, value_type)
    return payload


def _coerce_value(value: str, value_type: str):
    if value == "" and value_type in {"none", "int", "float"}:
        return None
    if value_type == "int":
        return int(value)
    if value_type == "float":
        return float(value)
    if value_type == "bool":
        return value.lower() in {"1", "true", "yes", "on"}
    if value_type == "none":
        return value or None
    return value


def _value_type(value) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "str"


def _human_label(key: str) -> str:
    label = key.replace("_", " ")
    return label[:1].upper() + label[1:]


def _css() -> str:
    return """
    :root {
      color-scheme: light;
      --ink: #171a1f;
      --muted: #606873;
      --line: #cfd6df;
      --paper: #fbfcfd;
      --panel: #ffffff;
      --steel: #29485f;
      --blue: #2b6ea6;
      --green: #1f7a55;
      --amber: #9b5a00;
      --red: #a53e33;
      --violet: #6050a8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }
    .topbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 24px;
      padding: 22px 28px;
      border-bottom: 1px solid var(--line);
      background: #fff;
      position: sticky;
      top: 0;
      z-index: 2;
    }
    .eyebrow {
      margin: 0 0 2px;
      color: var(--steel);
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
    }
    h1, h2, h3, h4, p { margin-top: 0; }
    h1 { margin-bottom: 4px; font-size: 24px; }
    h2 { margin-bottom: 0; font-size: 18px; }
    h3 { margin-bottom: 2px; font-size: 20px; }
    h4 { margin-bottom: 2px; font-size: 14px; }
    .summary, .candidate-id p, .review-item-head p, .section-head span {
      color: var(--muted);
      margin-bottom: 0;
      font-size: 13px;
    }
    main { max-width: 1280px; margin: 0 auto; padding: 24px; }
    .message, .error {
      max-width: 1280px;
      margin: 16px auto 0;
      padding: 10px 14px;
      border: 1px solid;
      background: #fff;
    }
    .message { border-color: #9ac8aa; color: #185a3c; }
    .error { border-color: #dda19b; color: #8a2f26; }
    .section-head {
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 16px;
      margin: 24px 0 10px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 8px;
    }
    .candidate {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      margin: 12px 0;
      padding: 16px;
      box-shadow: 0 1px 2px rgba(15, 23, 42, .04);
    }
    .candidate-main, .review-item-head {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
    }
    .candidate-grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(300px, 360px);
      gap: 18px;
      margin-top: 14px;
    }
    .facts {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 10px;
      margin: 0;
    }
    dt {
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
    }
    dd { margin: 1px 0 0; font-size: 14px; }
    .preview {
      border-left: 3px solid var(--steel);
      padding-left: 14px;
    }
    .write-preview, .warnings, .evidence ul {
      margin: 8px 0 0;
      padding-left: 18px;
    }
    .write-preview li {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin: 7px 0;
    }
    .warnings {
      color: var(--amber);
      font-size: 13px;
    }
    .clean {
      color: var(--green);
      font-size: 13px;
      margin-top: 12px;
    }
    .reason {
      color: var(--amber);
      font-size: 12px;
      margin: 3px 0 0;
    }
    .evidence {
      margin-top: 12px;
      color: var(--muted);
      font-size: 13px;
    }
    .source-list { color: var(--steel); }
    .pill {
      display: inline-flex;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 8px;
      background: #f6f8fb;
      color: var(--steel);
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
    }
    .pill.approved { color: var(--green); border-color: #9ac8aa; background: #eff8f2; }
    .pill.rejected { color: var(--red); border-color: #dda19b; background: #fff3f1; }
    .pill.obsidian-only { color: var(--violet); border-color: #bdb5e5; background: #f5f2ff; }
    button, select, input, textarea {
      font: inherit;
      border: 1px solid var(--line);
      border-radius: 6px;
    }
    button {
      background: #fff;
      color: var(--steel);
      font-weight: 800;
      padding: 7px 10px;
      cursor: pointer;
    }
    button:hover, button:focus { border-color: var(--blue); color: var(--blue); }
    button.primary {
      background: var(--blue);
      border-color: var(--blue);
      color: #fff;
    }
    .bundle-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 14px;
    }
    .edit-panel {
      margin-top: 14px;
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }
    .edit-panel summary {
      cursor: pointer;
      color: var(--steel);
      font-weight: 800;
    }
    .review-items {
      display: grid;
      gap: 12px;
      margin-top: 12px;
    }
    .review-item {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fff;
    }
    .review-item-head label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
    }
    .fields {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
      margin: 12px 0;
    }
    .field label {
      display: block;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      margin-bottom: 4px;
      text-transform: uppercase;
    }
    input[type="text"], textarea, select {
      width: 100%;
      padding: 8px;
      background: #fff;
    }
    input[readonly] {
      color: var(--muted);
      background: #f6f8fb;
    }
    textarea {
      min-height: 104px;
      resize: vertical;
    }
    .wide { grid-column: 1 / -1; }
    .empty {
      color: var(--muted);
      margin: 12px 0 24px;
    }
    @media (max-width: 840px) {
      .topbar, .candidate-main, .review-item-head {
        flex-direction: column;
        align-items: stretch;
      }
      .candidate-grid {
        grid-template-columns: 1fr;
      }
      main { padding: 16px; }
    }
    """
