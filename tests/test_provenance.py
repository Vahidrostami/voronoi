"""Tests for LLM provenance helpers."""

from __future__ import annotations

import hashlib
import json

import pytest

from voronoi.server.provenance import (
    PROVENANCE_MANIFEST,
    discover_provenance,
    write_provenance,
)


def _canonical_sha256(record: dict) -> str:
    payload = json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_write_provenance_creates_record_and_manifest(tmp_path):
    record = {
        "source_id": "K4_seed102__L4-A__run03__discovery",
        "model_id": "gpt-5-mini",
        "prompt_sha256": "3bc6fdb0",
        "response_text": '{"chosen_action":"5pct_feature"}',
    }

    record_path = write_provenance(tmp_path, record)

    assert record_path.is_file()
    payload = json.loads(record_path.read_text())
    assert payload["schema_version"] == "1.0"
    assert payload["source_id"] == record["source_id"]
    assert payload["content_sha256"] == _canonical_sha256(record)
    assert payload["metadata"] == record
    assert payload["recorded_at_utc"]

    manifest_path = tmp_path / ".swarm" / "llm_provenance" / PROVENANCE_MANIFEST
    manifest = json.loads(manifest_path.read_text())
    assert manifest["schema_version"] == "1.0"
    assert manifest["updated_at_utc"]
    assert manifest["records"] == [{
        "path": f".swarm/llm_provenance/{record_path.name}",
        "source_id": record["source_id"],
        "content_sha256": _canonical_sha256(record),
        "recorded_at_utc": payload["recorded_at_utc"],
    }]


def test_write_provenance_uses_prompt_hash_as_source_id(tmp_path):
    record = {
        "model_id": "gpt-5-mini",
        "prompt_sha256": "3bc6fdb059601f8222e15c6bd8aadc83b6ad46abd2de48c760f59269eafaca9f",
        "response_sha256": "71cbdd3f036ba5a45c5d3ae069d390863a44fc2056431e5cdef2c87e0702981b",
    }

    record_path = write_provenance(tmp_path, record)
    payload = json.loads(record_path.read_text())

    assert payload["source_id"] == record["prompt_sha256"]


def test_discover_provenance_uses_manifest_records(tmp_path):
    first = write_provenance(tmp_path, {"source_id": "call-1", "model_id": "m"})
    second = write_provenance(tmp_path, {"source_id": "call-2", "model_id": "m"})

    assert discover_provenance(tmp_path) == sorted([first, second])


def test_discover_provenance_falls_back_to_json_files(tmp_path):
    provenance_dir = tmp_path / ".swarm" / "llm_provenance"
    provenance_dir.mkdir(parents=True)
    manual = provenance_dir / "manual.json"
    manual.write_text(json.dumps({"source_id": "manual"}))
    (provenance_dir / PROVENANCE_MANIFEST).write_text("{not json")

    assert discover_provenance(tmp_path) == [manual]


def test_write_provenance_requires_json_serializable_record(tmp_path):
    with pytest.raises(TypeError):
        write_provenance(tmp_path, {"bad": {object()}})
