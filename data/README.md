# Local Pipeline Data

The PDF corpus, original page images, OCR/layout caches, graph JSON and local SQLite database are intentionally excluded from Git. Put the source PDF in a private directory, then prepare the development slice:

```bash
python3 scripts/prepare_kg_v2_data.py --source /path/to/volume-1.pdf
npm run pipeline:reliable
```

The default data directory is `data/local-kg/`. Override it with `WIKIBRIDGE_KG_DATA=/path/to/data`.

Page previews preserve the source PDF's image compression and resolution; preprocessed OCR PNGs are temporary. `page-images.json` records the preview files and their mapping to OCR coordinates.

Public model weights are downloaded separately and never included in the repository. Inference is run offline with the local model cache.
