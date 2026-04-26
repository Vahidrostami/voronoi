"""LLM call provenance helpers.

This module does not capture LLM calls by itself.  External experiment runners
or agent-side tooling call ``write_provenance`` with the metadata they want to
preserve, and Voronoi writes one JSON record per call plus a small manifest for
discovery.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = "1.0"
PROVENANCE_DIR = Path(".swarm") / "llm_provenance"
PROVENANCE_MANIFEST = "manifest.json"


def write_provenance(workspace_path: str | Path, record: dict[str, Any]) -> Path:
    """Write an LLM provenance record and update the provenance manifest.

    ``record`` must be JSON-serializable.  The returned path is the absolute
    path to the per-call JSON file under ``.swarm/llm_provenance/``.
    """
    if not isinstance(record, dict):
        raise TypeError("record must be a dict")

    workspace = Path(workspace_path)
    provenance_dir = workspace / PROVENANCE_DIR
    provenance_dir.mkdir(parents=True, exist_ok=True)

    content_bytes = _canonical_json_bytes(record)
    content_sha256 = hashlib.sha256(content_bytes).hexdigest()
    recorded_at = _utc_now()
    source_id = _source_id(record)
    record_name = f"{uuid.uuid4().hex}.json"
    record_path = provenance_dir / record_name
    rel_path = _relative_record_path(record_name)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "recorded_at_utc": recorded_at,
        "source_id": source_id,
        "content_sha256": content_sha256,
        "metadata": record,
    }
    _write_json_atomic(record_path, payload)

    with _manifest_lock(provenance_dir):
        manifest = _load_manifest(provenance_dir)
        manifest["updated_at_utc"] = _utc_now()
        manifest.setdefault("records", []).append({
            "path": rel_path,
            "source_id": source_id,
            "content_sha256": content_sha256,
            "recorded_at_utc": recorded_at,
        })
        _write_json_atomic(provenance_dir / PROVENANCE_MANIFEST, manifest)

    return record_path


def discover_provenance(workspace_path: str | Path) -> list[Path]:
    """Return provenance record paths for a workspace.

    The manifest is authoritative when present and valid.  If it is absent or
    malformed, discovery falls back to listing JSON files in the provenance
    directory, excluding the manifest itself.
    """
    workspace = Path(workspace_path)
    provenance_dir = workspace / PROVENANCE_DIR
    if not provenance_dir.is_dir():
        return []

    manifest_path = provenance_dir / PROVENANCE_MANIFEST
    manifest = _read_json(manifest_path)
    if isinstance(manifest, dict) and isinstance(manifest.get("records"), list):
        paths: list[Path] = []
        for item in manifest["records"]:
            if not isinstance(item, dict):
                continue
            rel = item.get("path")
            if not isinstance(rel, str):
                continue
            resolved = _resolve_workspace_relative(workspace, rel)
            if resolved is not None and resolved.is_file():
                paths.append(resolved)
        if paths:
            return sorted(paths)

    return sorted(
        path for path in provenance_dir.glob("*.json")
        if path.name != PROVENANCE_MANIFEST and path.is_file()
    )


def _load_manifest(provenance_dir: Path) -> dict[str, Any]:
    manifest = _read_json(provenance_dir / PROVENANCE_MANIFEST)
    if isinstance(manifest, dict) and isinstance(manifest.get("records"), list):
        return manifest
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at_utc": _utc_now(),
        "records": [],
    }


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def _manifest_lock(provenance_dir: Path) -> Iterator[None]:
    lock_dir = provenance_dir / ".manifest.lock"
    deadline = time.monotonic() + 5.0
    acquired = False
    while not acquired:
        try:
            lock_dir.mkdir()
            acquired = True
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out acquiring {lock_dir}")
            time.sleep(0.01)
    try:
        yield
    finally:
        try:
            lock_dir.rmdir()
        except FileNotFoundError:
            pass


def _canonical_json_bytes(record: dict[str, Any]) -> bytes:
    return json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _source_id(record: dict[str, Any]) -> str:
    for key in ("source_id", "call_id", "prompt_sha256", "id"):
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return uuid.uuid4().hex


def _relative_record_path(record_name: str) -> str:
    return str(PROVENANCE_DIR / record_name)


def _resolve_workspace_relative(workspace: Path, rel_path: str) -> Path | None:
    candidate = (workspace / rel_path).resolve()
    root = workspace.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate
