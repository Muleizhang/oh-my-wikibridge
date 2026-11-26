#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if (( $# > 1 )) || [[ $# == 1 && $1 != --no-network-namespace ]]; then
    printf 'Usage: bash scripts/rebuild_atlas.sh [--no-network-namespace]\n' >&2
    exit 2
fi

layout="${WIKIBRIDGE_LAYOUT_PYTHON:-$PWD/.venv/rebuild-layout/bin/python}"
nlp="${WIKIBRIDGE_LTP_PYTHON:-$PWD/.venv/rebuild/bin/python}"
dimensions="${WIKIBRIDGE_DIMENSIONS_PYTHON:-$nlp}"
export WIKIBRIDGE_LAYOUT_PYTHON="$layout" WIKIBRIDGE_LTP_PYTHON="$nlp"
for interpreter in "$layout" "$nlp" "$dimensions"; do
    [[ -x $interpreter && $interpreter == /* ]] || { printf 'Invalid Python path: %s\n' "$interpreter" >&2; exit 2; }
done

sha256sum --check source/SHA256SUMS
for tool in tesseract pdftoppm node; do
    command -v "$tool" >/dev/null || { printf 'Missing command: %s\n' "$tool" >&2; exit 2; }
done
languages=$(tesseract --list-langs)
for language in chi_sim eng; do
    grep -qx "$language" <<< "$languages" || { printf 'Missing Tesseract language: %s\n' "$language" >&2; exit 2; }
done

offline=()
if (( $# == 0 )); then
    offline=(unshare -n --)
    "${offline[@]}" true || { printf 'See --no-network-namespace in docs/reliable-pipeline.md\n' >&2; exit 2; }
fi
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True

data=data/local-kg
site=$data/merged/site
export WIKIBRIDGE_KG_DATABASE_ROOT="${WIKIBRIDGE_KG_DATABASE_ROOT:-$PWD/$data/database}"
books=(第一册 第二册 第三册)
roots=("$data" "$data/vol2" "$data/vol3")
atlases=("$data/atlas-vol1" "$data/vol2/star-atlas" "$data/vol3/star-atlas")
for i in 0 1 2; do
    WIKIBRIDGE_KG_DATA="${roots[i]}" "$nlp" scripts/prepare_kg_v2_data.py --all-pages --source "source/${books[i]}.pdf"
    WIKIBRIDGE_KG_DATA="${roots[i]}" "$nlp" scripts/reliable_pipeline.py "$@"
done

"$nlp" scripts/prepare_book_atlas.py source/第一册.pdf --output "$data/plate-images"
export_atlases() {
    local i root
    for i in 0 1 2; do
        root=${roots[i]}
        "$nlp" scripts/export_atlas_kg.py --graph "$root/graph.json" --page-images "$root/page-images.json" \
            --image-dir "$root/images" --output "${atlases[i]}"
    done
    "$nlp" scripts/merge_kg_volumes.py --mode copy \
        --volumes "第一册=${atlases[0]}" "第二册=${atlases[1]}" "第三册=${atlases[2]}"
}

export_atlases
"$nlp" scripts/enrich_artifact_types.py --write --persist
"${offline[@]}" "$dimensions" scripts/enrich_simple_dimensions.py --write --persist
"${offline[@]}" "$dimensions" scripts/enrich_interpretations.py --write --persist
export_atlases

"${offline[@]}" "$layout" scripts/kg_v2_annotate_batch.py --output "$site/annotations-v2"
node -e 'const s = require("./data/local-kg/merged/site/annotations-v2/status.json"); if (s.completed !== 1240 || s.status !== "complete") throw new Error("Check annotation status.json for missing pages");'
"$nlp" scripts/apply_plate_candidates.py --annotations "$site/annotations-v2"
"$nlp" scripts/apply_artifact_identity.py --apply
"$nlp" scripts/enrich_name_materials.py --apply
"${offline[@]}" "$dimensions" scripts/enrich_fulltext_recall.py --write --persist
"$nlp" scripts/enrich_catalog_structure.py --apply
printf 'Atlas: %s\nSQLite: %s/knowledge.sqlite3\n' "$site" "$WIKIBRIDGE_KG_DATABASE_ROOT"
