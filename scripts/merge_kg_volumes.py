#!/usr/bin/env python3
"""Merge multiple per-volume KG outputs (manifest.json or graph.json) into one unified cross-volume atlas site.

Works generically across any number of volumes (e.g., vol1 + vol2 + vol3) with zero book-specific rules:
- Isolates artifact/evidence/page IDs and asset filenames per volume to avoid collisions.
- Unifies shared semantic concepts (period, made_of, decorated_with, uses_technique) across volumes so
  multi-volume timelines, clustering, multi-hop paths, and DeepSeek Agent reasoning span all books seamlessly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any
from kg_v2.identity import normalize_name
from kg_v2.plate_images import attach_plate_images, source_pdf
from kg_v2.identity_manifest import apply_manifest_identity, combine_identities, is_artifact_row

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "scripts" / "atlas_viewer.html"
REASONER_JS = ROOT / "src" / "kg-reasoner.js"

UNUSABLE_ISSUES = {
    "unresolved_subject",
    "unresolved_object",
    "conflicting_values",
    "quantity_dimension_mismatch",
    "quantity_owner_not_artifact",
    "field_value_type_conflict",
    "relation_subject_type",
    "relation_object_type",
}
ALLOWED_PREDS = {"period", "made_of", "decorated_with", "uses_technique", "artifact_type",
                 "belongs_to_culture", "has_composition", "decorated_part", "decoration_role",
                 "excavated_at", "discovered_at", "collected_at", "held_by", "has_shape", "decorated_with_material"}


def map_interpretations(records, prefix, volume, pages, map_id=None):
    page_index = {page.get('volumePage', page['page']): page for page in pages}
    result = []
    for record in records:
        original = record.get('volumePage', record['page'])
        page = page_index.get(original)
        if page is None:
            raise ValueError(f'Missing interpretation source page: {volume} {original}')
        result.append({**record, 'id': map_id(record['id']) if map_id else f"{prefix}:{record['id']}",
            'page': page['page'], 'volumePage': original, 'volume': volume,
            'pageUrl': page['previewUrl'], 'locator': f'{volume} · PDF 第 {original} 页'})
    return result


def parse_volume_spec(spec: str, index: int) -> tuple[str, Path]:
    """Accept either 'path/to/vol' or 'label=path/to/vol'."""
    if "=" in spec:
        label, raw_path = spec.split("=", 1)
        label = label.strip() or f"vol{index}"
        path = Path(raw_path.strip())
    else:
        path = Path(spec.strip())
        label = path.parent.name if path.name == "site" else path.name
        label = re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fff-]", "", label) or f"vol{index}"
    return label, path.resolve()


def locate_volume_data(vol_dir: Path) -> tuple[str, Path, Path]:
    """Find manifest.json or graph.json inside a volume directory."""
    candidates = [
        ("manifest", vol_dir / "manifest.json", vol_dir),
        ("manifest", vol_dir / "site" / "manifest.json", vol_dir / "site"),
        ("graph", vol_dir / "graph.json", vol_dir),
    ]
    for kind, data_path, base_dir in candidates:
        if data_path.is_file():
            return kind, data_path, base_dir
    raise FileNotFoundError(f"目录 {vol_dir} 中未找到 manifest.json、site/manifest.json 或 graph.json")


def stage_asset(src_file: Path, dest_assets: Path, dest_name: str, mode: str) -> str:
    """Copy or symlink an asset file into merged/assets/ safely."""
    dest = dest_assets / dest_name
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    if mode == "symlink":
        try:
            rel_or_abs = os.path.relpath(src_file, dest.parent)
            dest.symlink_to(rel_or_abs)
        except OSError:
            shutil.copy2(src_file, dest)
    else:
        shutil.copy2(src_file, dest)
    return f"assets/{dest_name}"


def clamp_bbox(bbox: Any, img_size: tuple[int, int] | None = None) -> list[float] | None:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    vals = [float(v) for v in bbox]
    # Normalize pixel coordinates if any value > 1.0 and image_size is known
    if any(v > 1.0 for v in vals) and img_size and img_size[0] > 0 and img_size[1] > 0:
        w, h = img_size
        vals = [vals[0] / w, vals[1] / h, vals[2] / w, vals[3] / h]
    x1, y1, x2, y2 = [max(0.0, min(1.0, v)) for v in vals]
    if x2 <= x1 or y2 <= y1:
        return None
    return [round(x1, 6), round(y1, 6), round(x2, 6), round(y2, 6)]


def ingest_manifest_volume(
    prefix: str,
    vol_label: str,
    data_path: Path,
    base_dir: Path,
    dest_assets: Path,
    mode: str,
    page_offset: int,
) -> dict[str, Any]:
    raw = json.loads(data_path.read_text(encoding="utf-8"))
    identity = raw.get('artifactIdentity')
    source_scope = (identity or {}).get('volume') or prefix

    def source_id(value):
        if value is None:
            return None
        value = str(value)
        return value if value.startswith(source_scope + ':') else f'{source_scope}:{value}'

    vol_title = raw.get("title") or vol_label
    source_name = raw.get('sourceName') or vol_title
    asset_cache: dict[str, str] = {}

    def map_url(url: str | None) -> str:
        if not url:
            return ""
        if url in asset_cache:
            return asset_cache[url]
        src = (base_dir / url).resolve()
        if not src.is_file():
            return ""
        # Figure crops on different pages often all have the name r01.jpg.
        # Include the path digest so staging a later page never overwrites them.
        safe_name = f"{prefix}-{hashlib.sha256(url.encode()).hexdigest()[:12]}-{Path(url).name}"
        mapped = stage_asset(src, dest_assets, safe_name, mode)
        asset_cache[url] = mapped
        return mapped

    # Map original page numbers to contiguous merged page numbers
    orig_pages = raw.get("pages") or []
    original_previews = {int(p.get('page', n)): p.get('previewUrl', '')
                         for n, p in enumerate(orig_pages, 1)}
    page_num_map: dict[int, int] = {}
    pages_out: list[dict[str, Any]] = []
    for idx, p in enumerate(orig_pages, 1):
        orig_p = int(p.get("page", idx))
        new_p = page_offset + idx
        page_num_map[orig_p] = new_p
        pages_out.append({
            "page": new_p,
            "volume": vol_label,
            "volumeTitle": vol_title,
            "sourceName": source_name,
            "volumePage": orig_p,
            "previewUrl": map_url(p.get("previewUrl")),
            "lines": p.get("lines", 0),
            "entries": p.get("entries", 0),
        })

    def map_page(orig_p: Any) -> int:
        op = int(orig_p or 1)
        if op in page_num_map:
            return page_num_map[op]
        return page_offset + op

    def map_support(ev: dict[str, Any]) -> dict[str, Any]:
        orig_p = int(ev.get('page') or ev.get('ordinal') or 1)
        result = {**ev, 'volume': vol_label, 'sourceName': source_name,
                'page': map_page(orig_p), 'volumePage': orig_p,
                'previewUrl': map_url(ev.get('previewUrl')),
                'captionUrl': map_url(ev.get('captionUrl'))}
        for field in ('id', 'recordId', 'sourceRecordId', 'sourceStatementId', 'evidenceId'):
            if result.get(field):
                result[field] = source_id(result[field])
        return result

    def map_candidates(candidates):
        return [{**candidate, **{field: map_url(candidate[field])
                 for field in ('imageUrl', 'detailUrl', 'captionUrl', 'previewUrl') if candidate.get(field)}}
                for candidate in (candidates or [])]

    evidence_out: list[dict[str, Any]] = []
    for ev in raw.get("evidence", []):
        orig_p = int(ev.get("ordinal") or ev.get('page') or 1)
        loc = ev.get("locator") or f"第 {orig_p} 页"
        evidence_out.append({
            **ev,
            "id": source_id(ev['id']),
            "volume": vol_label,
            "sourceName": source_name,
            "ordinal": map_page(orig_p),
            "page": map_page(orig_p),
            "volumePage": orig_p,
            "locator": f"{vol_label} · {loc}",
            "previewUrl": map_url(ev.get("previewUrl")),
            "captionUrl": map_url(ev.get("captionUrl")) if ev.get('captionUrl') != ev.get('previewUrl') else '',
            "bbox": clamp_bbox(ev.get("bbox")),
        })

    rows_out: list[dict[str, Any]] = []
    for r in raw.get('sourceRows', raw.get("rows", [])):
        orig_p = int(r.get("page", 1))
        loc = r.get("locator") or f"第 {orig_p} 页"
        proof_loc = r.get("proofLocator") or loc
        object_label = normalize_name(str(r['object']))
        binding = dict(r.get('binding') or {})
        if binding.get('recordId'):
            binding['recordId'] = source_id(binding['recordId'])
        rows_out.append({
            **r,
            "id": source_id(r['id']),
            "artifactId": source_id(r.get('artifactId')),
            "evidenceId": source_id(r['evidenceId']),
            "sourceRecordId": source_id(r.get('sourceRecordId') or r.get('recordId') or r.get('artifactId')),
            "object": object_label,
            "objectId": f"merged:{r['predicate']}:{object_label}",
            "volume": vol_label,
            "sourceName": source_name,
            "page": map_page(orig_p),
            "volumePage": orig_p,
            "locator": f"{vol_label} · {loc}",
            "proofLocator": f"{vol_label} · {proof_loc}",
            "imageUrl": map_url(r.get("imageUrl")),
            "detailUrl": map_url(r.get("detailUrl")),
            "captionUrl": map_url(r.get("captionUrl")) if r.get('captionUrl') != original_previews.get(orig_p) else '',
            "pageUrl": map_url(r.get("pageUrl") or original_previews.get(orig_p)),
            "binding": binding,
            "supportingEvidence": [map_support(ev) for ev in r.get('supportingEvidence', [])],
        })
        if r.get('subjectId'):
            rows_out[-1]['subjectId'] = source_id(r['subjectId'])
        if r.get('subjectKey'):
            kind, _, key = r['subjectKey'].partition(':')
            rows_out[-1]['subjectKey'] = f'{kind}:{source_id(key)}'
        if r.get('recordId'):
            rows_out[-1]['recordId'] = source_id(r['recordId'])
        if r.get('sourceEntityId'):
            rows_out[-1]['sourceEntityId'] = source_id(r['sourceEntityId'])
        if r.get('evidenceIds'):
            rows_out[-1]['evidenceIds'] = [source_id(value) for value in r['evidenceIds']]
        if r.get('imageCandidates'):
            rows_out[-1]['imageCandidates'] = map_candidates(r['imageCandidates'])

    raw_items = raw.get('sourceItems', raw.get("items")) or list({r["artifactId"]: r for r in raw.get("rows", [])
                                                               if is_artifact_row(r) and r.get('artifactId')}.values())
    items_out: list[dict[str, Any]] = []
    for it in raw_items:
        orig_p = int(it.get("page", 1))
        loc = it.get("locator") or f"第 {orig_p} 页"
        items_out.append({
            **it,
            "artifactId": source_id(it['artifactId']),
            "evidenceId": source_id(it['evidenceId']),
            "sourceRecordId": source_id(it.get('sourceRecordId') or it.get('recordId') or it['artifactId']),
            "volume": vol_label,
            "sourceName": source_name,
            "page": map_page(orig_p),
            "volumePage": orig_p,
            "locator": f"{vol_label} · {loc}",
            "imageUrl": map_url(it.get("imageUrl")),
            "detailUrl": map_url(it.get("detailUrl")),
            "captionUrl": map_url(it.get("captionUrl")) if it.get('captionUrl') != original_previews.get(orig_p) else '',
            "pageUrl": map_url(it.get("pageUrl") or original_previews.get(orig_p)),
            "imageKind": it.get('imageKind') or ('artifact' if it.get('imageUrl') and
                            it.get('imageUrl') != original_previews.get(orig_p) else 'page'),
        })
        for field in ('id', 'recordId'):
            if it.get(field):
                items_out[-1][field] = source_id(it[field])
        if it.get('sourceEntityId'):
            items_out[-1]['sourceEntityId'] = source_id(it['sourceEntityId'])
        if it.get('imageCandidates'):
            items_out[-1]['imageCandidates'] = map_candidates(it['imageCandidates'])

    chunk = {
        "volume": vol_label,
        "title": vol_title,
        "format": "manifest",
        "interpretations": map_interpretations(raw.get('interpretations', []), prefix, vol_label, pages_out, source_id),
        "runId": raw.get('runId'),
        "summary": raw.get('summary', {}),
        "pages": pages_out,
        "items": items_out,
        "rows": rows_out,
        "evidence": evidence_out,
    }
    if identity:
        apply_manifest_identity(chunk, identity, source_scope)
    return chunk


def ingest_graph_volume(
    prefix: str,
    vol_label: str,
    data_path: Path,
    base_dir: Path,
    dest_assets: Path,
    mode: str,
    page_offset: int,
) -> dict[str, Any]:
    """Convert a reliable_pipeline.py graph.json volume into unified manifest entries."""
    graph = json.loads(data_path.read_text(encoding="utf-8"))
    identity = graph.get('artifactIdentity')
    source_scope = (identity or {}).get('volume') or prefix
    source_meta_path = base_dir / "source.json"
    source_meta = json.loads(source_meta_path.read_text(encoding="utf-8")) if source_meta_path.is_file() else {}
    vol_title = (
        graph.get("sourceContext", {}).get("title")
        or source_meta.get("name")
        or vol_label
    )

    # Index page images & sizes from documents + images/ directory
    doc_sizes: dict[int, tuple[int, int]] = {}
    page_set: set[int] = set()
    for doc in graph.get("documents", []):
        p = int(doc.get("page", 0))
        if p > 0:
            page_set.add(p)
            sz = doc.get("imageSize") or doc.get("image_size")
            if isinstance(sz, (list, tuple)) and len(sz) == 2:
                doc_sizes[p] = (int(sz[0]), int(sz[1]))
    for rec in graph.get("records", []):
        if rec.get("page"):
            page_set.add(int(rec["page"]))

    page_url_map: dict[int, str] = {}
    page_num_map: dict[int, int] = {}
    pages_out: list[dict[str, Any]] = []
    sorted_pages = sorted(page_set)
    for idx, orig_p in enumerate(sorted_pages, 1):
        new_p = page_offset + idx
        page_num_map[orig_p] = new_p
        img_url = ""
        for candidate in (
            base_dir / "images" / f"v1-p{orig_p:04d}.source.jpg",
            base_dir / "images" / f"v1-p{orig_p:04d}.source.png",
            base_dir / "images" / f"v1-p{orig_p:04d}.source.jpeg",
            base_dir / "images" / f"v1-p{orig_p:04d}.png",
            base_dir / "images" / f"p{orig_p:04d}.png",
            base_dir / "images" / f"p{orig_p}.jpg",
            base_dir / "pages" / f"p{orig_p}.jpg",
        ):
            if candidate.is_file():
                img_url = stage_asset(candidate, dest_assets, f"{prefix}-p{orig_p:04d}{candidate.suffix}", mode)
                break
        page_url_map[orig_p] = img_url
        pages_out.append({
            "page": new_p,
            "volume": vol_label,
            "volumeTitle": vol_title,
            "volumePage": orig_p,
            "previewUrl": img_url,
            "lines": 0,
            "entries": 0,
        })

    entities = {e["id"]: e for e in graph.get("entities", [])}
    events = {e["id"]: e for e in graph.get("events", [])}
    records = {r["id"]: r for r in graph.get("records", [])}
    artifact_owners = {
        e["id"]: e["recordId"]
        for e in graph.get("entities", [])
        if e.get("kind") == "artifact" and e.get("recordId")
    }
    artifact_by_record = {record_id: entity_id for entity_id, record_id in artifact_owners.items()}
    motif_concepts: dict[str, dict[str, Any]] = {}
    for concept in (graph.get("identityReview") or {}).get("concepts", []):
        if concept.get("kind") == "motif":
            for mid in concept.get("memberIds", []):
                motif_concepts[mid] = concept

    # Build items & base evidence from records
    items_out: list[dict[str, Any]] = []
    evidence_out: list[dict[str, Any]] = []
    rec_item_map: dict[str, dict[str, Any]] = {}
    page_counts: dict[int, int] = {}

    for rec in graph.get("records", []):
        orig_p = int(rec.get("page", 1))
        new_p = page_num_map.get(orig_p, page_offset + orig_p)
        page_counts[new_p] = page_counts.get(new_p, 0) + 1
        aid = f"{prefix}:{rec['id']}"
        loc = f"{vol_label} · PDF 第 {orig_p} 页 · 图 {rec.get('item', '')}".strip(" ·")
        preview = page_url_map.get(orig_p, "")
        bbox = clamp_bbox(rec.get("bbox"), doc_sizes.get(orig_p))

        item_obj = {
            "artifactId": aid,
            "sourceRecordId": f"{source_scope}:{rec['id']}",
            "sourceId": prefix,
            "sourceName": vol_title,
            "volume": vol_label,
            "artifact": rec.get("label") or rec["id"],
            "item": rec.get('item'),
            "page": new_p,
            "volumePage": orig_p,
            "locator": loc,
            "proofLocator": loc,
            "quote": rec.get("text", ""),
            "evidenceId": aid,
            "status": "管线抽取",
            "imageUrl": preview,
            "detailUrl": preview,
            "detailLabel": "原页图版",
            "captionUrl": "",
            "pageUrl": preview,
            "imageKind": "page",
            "findspot": "",
        }
        if rec['id'] in artifact_by_record:
            item_obj['sourceEntityId'] = f"{source_scope}:{artifact_by_record[rec['id']]}"
        items_out.append(item_obj)
        rec_item_map[rec["id"]] = item_obj
        evidence_out.append({
            "id": aid,
            "sourceId": prefix,
            "corpusId": prefix,
            "corpusName": vol_title,
            "sourceName": vol_title,
            "volume": vol_label,
            "extension": "pdf",
            "kind": "page",
            "ordinal": new_p,
            "volumePage": orig_p,
            "locator": loc,
            "text": rec.get("text", ""),
            "method": rec.get("engine") or "kg_v2",
            "previewUrl": preview,
            "captionUrl": "",
            "bbox": bbox,
        })

    for p in pages_out:
        p["entries"] = page_counts.get(p["page"], 0)

    # Convert typed assertions into merged rows
    rows_out: list[dict[str, Any]] = []
    seen_row_keys: set[tuple[str, str, str]] = set()
    for fact in graph.get("assertions", []):
        if fact.get("reviewStatus") == "rejected":
            continue
        if any(iss in UNUSABLE_ISSUES for iss in (fact.get("issues") or [])):
            continue
        owner = artifact_owners.get(fact.get("subject", ""))
        if not owner or owner not in rec_item_map:
            continue
        ev_list = fact.get("evidence") or []
        if not ev_list:
            continue

        obj = fact.get("object") or {}
        val = ""
        if obj.get("kind") == "entity":
            oid = obj.get("id", "")
            if fact.get("predicate") == "decorated_with" and oid in motif_concepts:
                val = motif_concepts[oid].get("name", "")
            else:
                val = entities.get(oid, {}).get("label", "")
        elif obj.get("kind") == "event":
            ev_obj = events.get(obj.get("id", ""), {})
            val = "、".join(
                entities.get(p["entityId"], {}).get("label", "")
                for p in ev_obj.get("participants", [])
                if p.get("role") != "object" and entities.get(p["entityId"], {}).get("label")
            )
        else:
            val = obj.get("raw") or obj.get("value") or ""

        val = str(val).strip()
        if not val:
            continue

        item_obj = rec_item_map[owner]
        if fact.get("label") in {"出土", "出土地点"} and not item_obj["findspot"]:
            item_obj["findspot"] = val

        pred = fact.get("predicate", "")
        if pred not in ALLOWED_PREDS:
            continue
        dedup_key = (item_obj["artifactId"], pred, val)
        if not identity and dedup_key in seen_row_keys:
            continue
        seen_row_keys.add(dedup_key)

        ev0 = ev_list[0]
        ev_page = int(ev0.get("page") or item_obj["volumePage"])
        rows_out.append({
            **item_obj,
            "id": f"{prefix}:{fact['id']}",
            "predicate": pred,
            "object": val,
            "objectId": f"merged:{pred}:{val}",
            "quote": ev0.get("text") or item_obj["quote"],
            "proofLocator": f"{vol_label} · PDF 第 {ev_page} 页",
            "supportingEvidence": [{**ev, 'volume': vol_label, 'sourceName': vol_title,
                'page': page_num_map.get(int(ev.get('page') or item_obj['volumePage']),
                                         page_offset + int(ev.get('page') or item_obj['volumePage'])),
                'volumePage': int(ev.get('page') or item_obj['volumePage']),
                'previewUrl': page_url_map.get(int(ev.get('page') or item_obj['volumePage']), ''),
                'normalizedBbox': clamp_bbox(ev.get('bbox'), doc_sizes.get(int(ev.get('page') or item_obj['volumePage'])))}
                for ev in ev_list],
            "issues": fact.get('issues', []),
            "origin": fact.get('origin'),
            "projectionStatus": fact.get('projectionStatus'),
            "supersededBy": [f'{prefix}:{sid}' for sid in fact.get('supersededBy', [])],
            "correction": fact.get('correction'),
            "reviewStatus": fact.get('reviewStatus'),
            "binding": {**(fact.get('binding') or {}), 'recordId': f'{source_scope}:{owner}'},
        })

    chunk = {
        "volume": vol_label,
        "title": vol_title,
        "format": "graph",
        "interpretations": map_interpretations(graph.get('interpretations', []), prefix, vol_label, pages_out),
        "pages": pages_out,
        "items": items_out,
        "rows": rows_out,
        "evidence": evidence_out,
    }
    plate_manifest = base_dir / 'plate-images' / 'manifest.json'
    if plate_manifest.is_file():
        attach_plate_images(chunk, plate_manifest, source_pdf(data_path), dest_assets.parent)
    if identity:
        apply_manifest_identity(chunk, identity, source_scope)
    return chunk


def merge_volumes(
    volume_specs: list[str],
    output_dir: Path,
    title: str = "中国纹样全集 · 跨卷总图谱",
    mode: str = "symlink",
    build_html: bool = True,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    dest_assets = output_dir / "assets"
    dest_assets.mkdir(parents=True, exist_ok=True)

    all_pages: list[dict[str, Any]] = []
    all_items: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    all_evidence: list[dict[str, Any]] = []
    volumes_meta: list[dict[str, Any]] = []
    identities = []
    all_interpretations = []

    page_offset = 0
    for idx, spec in enumerate(volume_specs, 1):
        vol_label, vol_dir = parse_volume_spec(spec, idx)
        prefix = f"v{idx}"
        kind, data_path, base_dir = locate_volume_data(vol_dir)
        if kind == "manifest":
            chunk = ingest_manifest_volume(prefix, vol_label, data_path, base_dir, dest_assets, mode, page_offset)
        else:
            chunk = ingest_graph_volume(prefix, vol_label, data_path, base_dir, dest_assets, mode, page_offset)

        all_pages.extend(chunk["pages"])
        all_items.extend(chunk.get('sourceItems', chunk["items"]))
        all_rows.extend(chunk.get('sourceRows', chunk["rows"]))
        all_evidence.extend(chunk["evidence"])
        all_interpretations.extend(chunk.get('interpretations', []))
        if chunk.get('artifactIdentity'):
            identities.append(chunk['artifactIdentity'])
        volumes_meta.append({
            "prefix": prefix,
            "label": vol_label,
            "title": chunk["title"],
            "format": chunk["format"],
            "source": str(data_path),
            "pages": len(chunk["pages"]),
            "items": len(chunk["items"]),
            "rows": len(chunk["rows"]),
            "runId": chunk.get('runId'),
            "sourceRecords": chunk.get('summary', {}).get('sourceRecords', len(chunk['items'])),
        })
        page_offset += len(chunk["pages"])

    # Sanity checks: zero duplicate IDs across the merged corpus
    assert len({r["id"] for r in all_rows}) == len(all_rows), "Duplicate row ID detected in merged output"
    assert len({e["id"] for e in all_evidence}) == len(all_evidence), "Duplicate evidence ID detected in merged output"
    assert len({it['artifactId'] for it in all_items}) == len(all_items), 'Duplicate artifact ID detected in merged output'
    artifact_ids = {it['artifactId'] for it in all_items}
    evidence_ids = {ev['id'] for ev in all_evidence}
    assert all((not is_artifact_row(r) or r['artifactId'] in artifact_ids) and r['evidenceId'] in evidence_ids
               for r in all_rows), 'Dangling merged reference'

    merged = {
        "title": title,
        "status": "机器候选 · 尚未人工确认",
        "runId": 'merged-' + hashlib.sha256(json.dumps([[v.get('runId') for v in volumes_meta],
            [[r['id'], r['predicate'], r['object']] for r in all_rows]], ensure_ascii=False).encode()).hexdigest()[:20],
        "summary": {"sourcePages": len(all_pages), "sourceRecords": sum(v['sourceRecords'] for v in volumes_meta),
                    "graphItems": len(all_items), "graphEdges": len(all_rows), "volumes": len(volumes_meta),
                    "artifactCrops": sum(it.get('imageKind') == 'artifact' for it in all_items)},
        "volumes": volumes_meta,
        "pages": all_pages,
        "items": all_items,
        "rows": all_rows,
        "evidence": all_evidence,
        "interpretations": all_interpretations,
    }
    apply_manifest_identity(merged, combine_identities(identities))
    merged['summary'].update(interpretations=len(all_interpretations),
                             graphEdges=len(merged['rows'])+2*len(all_interpretations))
    artifact_ids = {item['artifactId'] for item in merged['items']}
    assert len(artifact_ids) == len(merged['items']), 'Duplicate canonical artifact ID detected'
    assert all(not is_artifact_row(row) or row['artifactId'] in artifact_ids for row in merged['rows']), 'Dangling canonical reference'
    if identities:
        merged['runId'] = 'merged-' + hashlib.sha256(json.dumps([
            [v.get('runId') for v in volumes_meta],
            [[r['id'], r.get('artifactId'), r['predicate'], r['object']] for r in merged['rows']],
            {key: merged['artifactIdentity'].get(key) for key in ('version', 'sourceToCanonical', 'recordToCanonical')},
        ], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
    manifest_out = output_dir / "manifest.json"
    manifest_text = json.dumps(merged, ensure_ascii=False, separators=(',', ':'))
    manifest_out.write_text(manifest_text, encoding="utf-8")

    if build_html and TEMPLATE.is_file() and REASONER_JS.is_file():
        template = TEMPLATE.read_text(encoding="utf-8")
        reasoner_src = re.sub(r"(?m)^export\s+", "", REASONER_JS.read_text(encoding="utf-8"))
        html = template.replace("__REASONER_JS__", reasoner_src, 1).replace(
            "__MANIFEST_JSON__", manifest_text.replace("<", "\\u003c"), 1
        )
        (output_dir / "index.html").write_text(html, encoding="utf-8")

    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--volumes",
        nargs="+",
        required=True,
        help="Volume directories (or label=path), e.g. 第一册=data/local-kg/vol1 第二册=data/local-kg/vol2 第三册=data/local-kg/vol3",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/local-kg/merged/site",
        help="Output site directory for merged manifest.json, assets/, and index.html",
    )
    parser.add_argument("--title", default="中国纹样全集 · 三册总图谱", help="Merged atlas title")
    parser.add_argument("--mode", choices=["symlink", "copy"], default="symlink", help="How to stage image assets")
    parser.add_argument("--no-html", action="store_true", help="Skip generating standalone index.html")
    args = parser.parse_args()

    merged = merge_volumes(
        args.volumes,
        args.output.resolve(),
        title=args.title,
        mode=args.mode,
        build_html=not args.no_html,
    )
    periods = len({r["object"] for r in merged["rows"] if r["predicate"] == "period"})
    materials = len({r["object"] for r in merged["rows"] if r["predicate"] == "made_of"})
    motifs = len({r["object"] for r in merged["rows"] if r["predicate"] == "decorated_with"})
    print(
        f"Merged {len(merged['volumes'])} volumes → {args.output / 'manifest.json'}\n"
        f"  {len(merged['pages'])} pages · {len(merged['items'])} items · {len(merged['rows'])} edges\n"
        f"  {periods} eras · {materials} materials · {motifs} motifs"
    )
    for v in merged["volumes"]:
        print(f"  - [{v['prefix']}] {v['label']} ({v['format']}): {v['pages']} pages, {v['items']} items, {v['rows']} edges")


if __name__ == "__main__":
    main()
