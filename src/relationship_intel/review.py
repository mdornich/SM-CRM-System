"""Local human-in-the-loop CRM review UI.

This is intentionally small and stdlib-only: a local browser form over the
SQLite review queue. It edits structured payload fields and syncs only approved
items.
"""

from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from relationship_intel.config import Settings
from relationship_intel.crm.sync import sync_to_crm
from relationship_intel.pipeline import make_adapter, open_repo, rebuild_review_queue

STATUSES = ("pending", "approved", "rejected", "obsidian_only")


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
    rows = "\n".join(_render_item(item) for item in items)
    status_counts = {status: 0 for status in STATUSES}
    for item in items:
        status_counts[item.status] = status_counts.get(item.status, 0) + 1
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Relationship Intel Review</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; }}
    header {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; }}
    .summary {{ color: #444; }}
    .message {{ background: #e9f7ef; border: 1px solid #8fd19e; padding: 10px; margin: 14px 0; }}
    .error {{ background: #fdecea; border: 1px solid #f5a5a0; padding: 10px; margin: 14px 0; }}
    article {{ border: 1px solid #d0d7de; border-radius: 8px; margin: 14px 0; padding: 14px; }}
    .meta {{ color: #57606a; font-size: 13px; margin: 4px 0 10px; }}
    .reason {{ color: #9a3412; font-size: 13px; }}
    .fields {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 12px;
      margin-top: 12px;
    }}
    .field label {{ display: block; font-weight: 600; font-size: 13px; margin-bottom: 4px; }}
    input[type="text"], textarea {{
      box-sizing: border-box;
      border: 1px solid #d0d7de;
      border-radius: 6px;
      padding: 8px;
    }}
    input[type="text"] {{ width: 100%; }}
    textarea {{
      width: 100%;
      min-height: 110px;
      font-family: inherit;
      line-height: 1.4;
    }}
    button, select {{ font: inherit; padding: 6px 10px; }}
    .controls {{ display: flex; gap: 10px; align-items: center; margin-top: 8px; }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>CRM Review Queue</h1>
      <div class="summary">{html.escape(str(status_counts))}</div>
    </div>
    <form method="post" action="/sync">
      <button type="submit">Sync Approved to Twenty</button>
    </form>
  </header>
  {f'<div class="message">{html.escape(message)}</div>' if message else ""}
  {f'<div class="error">{html.escape(error)}</div>' if error else ""}
  {rows or "<p>No review items.</p>"}
</body>
</html>"""


def _render_item(item) -> str:
    status_options = "\n".join(
        f'<option value="{status}" {"selected" if status == item.status else ""}>{status}</option>'
        for status in STATUSES
    )
    fields = _render_payload_fields(item.payload)
    return f"""<article>
  <h2>{html.escape(item.label)}</h2>
  <div class="meta">{html.escape(item.object_type)} #{item.local_id}</div>
  {f'<div class="reason">Review reason: {html.escape(item.reason)}</div>' if item.reason else ""}
  <form method="post" action="/item">
    <input type="hidden" name="object_type" value="{html.escape(item.object_type)}">
    <input type="hidden" name="local_id" value="{item.local_id}">
    <label>Status <select name="status">{status_options}</select></label>
    <div class="fields">{fields}</div>
    <div class="controls">
      <button type="submit">Save</button>
    </div>
  </form>
</article>"""


def _render_payload_fields(payload: dict) -> str:
    rows = []
    for key, value in sorted(payload.items()):
        label = _human_label(key)
        value_type = _value_type(value)
        value_text = "" if value is None else str(value)
        rows.append(
            f'<input type="hidden" name="field" value="{html.escape(key)}">'
            f'<input type="hidden" name="type__{html.escape(key)}" value="{value_type}">'
        )
        if key in {"body", "description"} or len(value_text) > 90:
            rows.append(
                f'<div class="field"><label>{html.escape(label)}</label>'
                f'<textarea name="value__{html.escape(key)}">{html.escape(value_text)}</textarea>'
                "</div>"
            )
        else:
            rows.append(
                f'<div class="field"><label>{html.escape(label)}</label>'
                f'<input type="text" name="value__{html.escape(key)}" '
                f'value="{html.escape(value_text)}"></div>'
            )
    return "\n".join(rows)


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
