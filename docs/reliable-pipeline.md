# Reliable Local Pipeline

The repository contains the current typed pipeline and review UI. Historical experiments, large OCR outputs, PDFs and screenshots are kept in a local archive or ignored data directories and are not part of the Git change.

The pipeline processes a selected PDF slice through PP-Structure/OCR, caption boundary detection, UIE field extraction, typed quantity/event parsing, LTP syntax plus open relation candidates, local embedding retrieval, reranking, validation, and SQLite persistence. Same-name motif, period, technique, material and culture mentions are grouped as source-scoped concepts; artifact, place and organization occurrences remain separate instances.

Prepare local data and models:

```bash
python3 scripts/prepare_kg_v2_data.py --source /private/path/volume-1.pdf
python3 scripts/download_kg_v2_models.py
npm run pipeline:reliable
```

Layout dependencies are in `scripts/requirements-kg-v2-layout.txt`; NLP dependencies are in `scripts/requirements-kg-v2-nlp.txt`. Set `WIKIBRIDGE_LAYOUT_PYTHON`, `WIKIBRIDGE_LTP_PYTHON`, or `WIKIBRIDGE_KG_DATA` when using different local environments.

Run checks with `npm run test:kg` and `npm run build`. The pipeline only produces candidate data; automatic fact acceptance and identity merging remain disabled until independent annotation and calibration are available.
