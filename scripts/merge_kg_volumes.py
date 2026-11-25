#!/usr/bin/env python3
"""Merge multiple per-volume KG outputs (manifest.json or graph.json) into one unified cross-volume atlas site.

Works generically across any number of volumes (e.g., vol1 + vol2 + vol3) with zero book-specific rules:
- Isolates artifact/evidence/page IDs and asset filenames per volume to avoid collisions.
- Unifies shared semantic concepts (period, made_of, decorated_with, uses_technique) across volumes so
  multi-volume timelines, clustering, multi-hop paths, and DeepSeek Agent reasoning span all books seamlessly.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

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
ALLOWED_PREDS = {"period", "made_of", "decorated_with", "uses_technique"}


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
    vol_title = raw.get("title") or vol_label
    asset_cache: dict[str, str] = {}

    def map_url(url: str | None) -> str:
        if not url:
            return ""
        if url in asset_cache:
            return asset_cache[url]
        src = (base_dir / url).resolve()
        if not src.is_file():
            return ""
        safe_name = f"{prefix}-{Path(url).name}"
        mapped = stage_asset(src, dest_assets, safe_name, mode)
        asset_cache[url] = mapped
        return mapped

    # Map original page numbers to contiguous merged page numbers
    orig_pages = raw.get("pages") or []
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

    evidence_out: list[dict[str, Any]] = []
    for ev in raw.get("evidence", []):
        orig_p = int(ev.get("ordinal", 1))
        loc = ev.get("locator") or f"第 {orig_p} 页"
        evidence_out.append({
            **ev,
            "id": f"{prefix}:{ev['id']}",
            "volume": vol_label,
            "sourceName": vol_title,
            "ordinal": map_page(orig_p),
            "volumePage": orig_p,
            "locator": f"{vol_label} · {loc}",
            "previewUrl": map_url(ev.get("previewUrl")),
            "captionUrl": map_url(ev.get("captionUrl")),
            "bbox": clamp_bbox(ev.get("bbox")),
        })

    rows_out: list[dict[str, Any]] = []
    for r in raw.get("rows", []):
        orig_p = int(r.get("page", 1))
        loc = r.get("locator") or f"第 {orig_p} 页"
        proof_loc = r.get("proofLocator") or loc
        rows_out.append({
            **r,
            "id": f"{prefix}:{r['id']}",
            "artifactId": f"{prefix}:{r['artifactId']}",
            "evidenceId": f"{prefix}:{r['evidenceId']}",
            "objectId": f"merged:{r['predicate']}:{r['object']}",
            "volume": vol_label,
            "sourceName": vol_title,
            "page": map_page(orig_p),
            "volumePage": orig_p,
            "locator": f"{vol_label} · {loc}",
            "proofLocator": f"{vol_label} · {proof_loc}",
            "imageUrl": map_url(r.get("imageUrl")),
            "detailUrl": map_url(r.get("detailUrl")),
            "captionUrl": map_url(r.get("captionUrl")),
        })

    raw_items = raw.get("items") or list({r["artifactId"]: r for r in raw.get("rows", [])}.values())
    items_out: list[dict[str, Any]] = []
    for it in raw_items:
        orig_p = int(it.get("page", 1))
        loc = it.get("locator") or f"第 {orig_p} 页"
        items_out.append({
            **it,
            "artifactId": f"{prefix}:{it['artifactId']}",
            "evidenceId": f"{prefix}:{it['evidenceId']}",
            "volume": vol_label,
            "sourceName": vol_title,
            "page": map_page(orig_p),
            "volumePage": orig_p,
            "locator": f"{vol_label} · {loc}",
            "imageUrl": map_url(it.get("imageUrl")),
            "detailUrl": map_url(it.get("detailUrl")),
            "captionUrl": map_url(it.get("captionUrl")),
        })

    return {
        "volume": vol_label,
        "title": vol_title,
        "format": "manifest",
        "pages": pages_out,
        "items": items_out,
        "rows": rows_out,
        "evidence": evidence_out,
    }


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
            "sourceId": prefix,
            "sourceName": vol_title,
            "volume": vol_label,
            "artifact": rec.get("label") or rec["id"],
            "item": f"图 {rec.get('item', '')}".strip(),
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
            "findspot": "",
        }
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
            continue

        pred = fact.get("predicate", "")
        if pred not in ALLOWED_PREDS:
            continue
        dedup_key = (item_obj["artifactId"], pred, val)
        if dedup_key in seen_row_keys:
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
        })

    return {
        "volume": vol_label,
        "title": vol_title,
        "format": "graph",
        "pages": pages_out,
        "items": items_out,
        "rows": rows_out,
        "evidence": evidence_out,
    }


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
        all_items.extend(chunk["items"])
        all_rows.extend(chunk["rows"])
        all_evidence.extend(chunk["evidence"])
        volumes_meta.append({
            "prefix": prefix,
            "label": vol_label,
            "title": chunk["title"],
            "format": chunk["format"],
            "source": str(data_path),
            "pages": len(chunk["pages"]),
            "items": len(chunk["items"]),
            "rows": len(chunk["rows"]),
        })
        page_offset += len(chunk["pages"])

    # Sanity checks: zero duplicate IDs across the merged corpus
    assert len({r["id"] for r in all_rows}) == len(all_rows), "Duplicate row ID detected in merged output"
    assert len({e["id"] for e in all_evidence}) == len(all_evidence), "Duplicate evidence ID detected in merged output"

    merged = {
        "title": title,
        "volumes": volumes_meta,
        "pages": all_pages,
        "items": all_items,
        "rows": all_rows,
        "evidence": all_evidence,
    }
    manifest_out = output_dir / "manifest.json"
    manifest_text = json.dumps(merged, ensure_ascii=False, indent=2)
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
