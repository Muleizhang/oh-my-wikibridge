# Reliable Local Pipeline

The repository contains the current typed pipeline and review UI. Historical experiments, large OCR outputs, PDFs and screenshots are kept in a local archive or ignored data directories and are not part of the Git change.

The pipeline processes a selected PDF slice through PP-Structure/OCR, caption boundary detection, UIE field extraction, typed quantity/event parsing, LTP syntax plus open relation candidates, local embedding retrieval, reranking, validation, and SQLite persistence. Same-name motif, period, technique, material and culture mentions are grouped as source-scoped concepts; artifact, place and organization occurrences remain separate instances.

Caption construction also supplements UIE omissions using explicit name structure: open-ended `…纹` spans, material-plus-carrier phrases, and named techniques. A single unambiguous era heading on the same plate page can supply a contextual period candidate when the caption has no explicit era. These candidates retain their method and exact source spans; heading assignments retain both the caption and heading evidence. Mixed-era headings, excavation dates, depicted objects, and cross-page chapter propagation are excluded. This supplement does not establish historical transmission or independently measured extraction accuracy.

Existing cached OCR can be supplemented without rerunning models using `python3 scripts/kg_v2_enrich.py --write`, followed by `python3 scripts/kg_v2_store.py` and the atlas exporter. The enrichment preserves the previous graph in the ignored local archive, retains original candidates and identity proposals, and does not rerank the new mentions. Independent evaluation of the added relations remains pending.

Prepare local data and models:

```bash
python3 scripts/prepare_kg_v2_data.py --source /private/path/volume-1.pdf
python3 scripts/download_kg_v2_models.py
npm run pipeline:reliable
```

Layout dependencies are in `scripts/requirements-kg-v2-layout.txt`; NLP dependencies are in `scripts/requirements-kg-v2-nlp.txt`. OCR preparation uses four page workers by default; PP-Structure uses two processes with four CPU threads each. Set `WIKIBRIDGE_LAYOUT_PYTHON`, `WIKIBRIDGE_LTP_PYTHON`, or `WIKIBRIDGE_KG_DATA` when using different local environments.

For single-image scanned pages, previews retain the PDF's original JPEG bytes or original-resolution lossless image. OCR preprocessing uses temporary PNG files, and the desktop shares preview storage with the project through hard links when supported. Existing results can be migrated with `python3 scripts/compact_kg_images.py --prune`; this preserves knowledge data and evidence coordinates, then removes the old rendered PNG copies.

Export graphable artifact, motif, period, material, and technique candidates into Muleizhang's standalone star-atlas view with `python3 scripts/export_atlas_kg.py`. It writes an ignored `data/local-kg/star-atlas/` folder with small page previews and the viewer manifest. Unrecognized period candidates are kept in the export audit but omitted from the timeline. Serve the folder with `python3 -m http.server 1421 --bind 127.0.0.1 --directory data/local-kg/star-atlas`; every displayed edge remains marked as an unreviewed candidate.

Run checks with `npm run test:kg` and `npm run build`. The pipeline only produces candidate data; automatic fact acceptance and identity merging remain disabled until independent annotation and calibration are available.
