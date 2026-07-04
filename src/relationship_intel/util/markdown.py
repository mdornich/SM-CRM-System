"""Tiny deterministic Markdown/YAML emit helpers (stable ordering, no timestamps)."""

from __future__ import annotations


def yaml_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(str(v) for v in value) + "]"
    text = str(value)
    if any(ch in text for ch in ':#{}[]"\\\n') or text != text.strip():
        # Double-quoted YAML scalar with full escaping — an embedded newline
        # would otherwise corrupt the frontmatter block (and content_hash parse).
        escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    return text


def frontmatter_block(pairs: list[tuple[str, object]]) -> str:
    lines = ["---"]
    lines += [f"{key}: {yaml_value(value)}" for key, value in pairs]
    lines.append("---")
    return "\n".join(lines)


def section(heading: str, body_lines: list[str]) -> str:
    body = "\n".join(body_lines) if body_lines else "_none recorded_"
    return f"## {heading}\n\n{body}\n"


def bullets(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items]
