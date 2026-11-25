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

Artifact crops are independent of source-page previews. The exporter automatically reads
`plate-images/manifest.json` beside the selected `graph.json`, or an explicit `--plate-manifest`.
The crop manifest uses the existing book-sample format: source PDF `sha256`, rows with `page`,
`item`, `artifact`, and separate `imageUrl` (artifact), `detailUrl` (motif) and `captionUrl`.
The PDF hash, page, figure number and name must match; ambiguous or unmatched records are
reported without guessing. OCR caption coordinates are not artifact image boxes. Merging
and original-page packaging preserve each image role; unannotated entries are labeled
as source pages in the drawer.

Recover the four previously annotated first-volume crops without rerunning extraction:

```bash
python3 scripts/prepare_book_atlas.py /path/to/the-matching-first-volume.pdf --output data/local-kg/plate-images
python3 scripts/export_atlas_kg.py --output data/local-kg/atlas-vol1
```

These are four explicit annotations, not an automatic whole-book image segmentation model.

For automatic region candidates, `kg_v2_annotate_plates.py` searches for isolated
figure numbers at two contrast levels independently of artifact detection, then
recognizes them with a cached local PP-OCRv5 recognizer. It combines complete photo
panels, usable cached layout boxes and connected components with the ink detector.
Only thin marginal rules are removed on the complete-panel path; internal shafts
and solid photograph regions are preserved. Spatial pairing associates each region
with its nearest eligible figure number instead of consuming an entire column.
Printed numbers without a parsed catalog caption still act as spatial boundaries,
so images 1 and 2 cannot silently become extra views of catalog record 3. Detected
photo panels also cover black-background and rectangular detail plates; blank
paper strips next to a complete photograph are excluded. Boxes spanning explicit
catalog text are rejected rather than presented as object crops.
Multiple subimages in one caption group do not establish one physical object.
Original page bytes and resolution are retained; crops keep their original pixel
scale. No LLM is used and the graph is not modified.

Run all three cached volumes with resumable page outputs and two local workers:

```bash
unshare -n /path/to/layout-env/bin/python scripts/kg_v2_annotate_batch.py --workers 2
```

The default output is `data/local-kg/merged/site/annotations/`; its `index.html`
shows progress and links to each page's crop preview and `candidate-annotations.json`.
Existing page images are hard-linked when possible. Missing captions, unrecognized
or duplicate figure numbers, unassigned regions and execution errors are recorded.
Resume checks the script, local OCR weights, OCR inputs and source-image hash.
The spatial costs still favor lower-right labels; unusual layouts can produce
wrong groups even without a rule warning. All results remain candidates,
separate from the reviewed crop manifest consumed by the atlas exporter. Independent
cross-page accuracy has not been measured.

To display the generated crop candidates in the current merged atlas, run
`python3 scripts/apply_plate_candidates.py`. It archives the previous manifest,
binds candidates by volume and exact catalog-record ID, and retains explicit
reviewed crops and original-page evidence. Multi-image caption groups have an
unscaled group image and individual images in the drawer gallery; small previews
keep star-map loading bounded. The drawer labels these images as automatic
candidates. Restart the atlas server after updating its cached manifest.

To replace an earlier candidate run, write the new run to a separate directory and
use `--annotations data/local-kg/merged/site/annotations-v2 --reset-candidates` when
applying it. This removes stale automatic bindings while keeping explicit crops.
Missing figure numbers, duplicate labels and captions without regions remain
visible in each page's audit. The focused geometry regressions run with
`python -m unittest discover -s scripts -p test_kg_plate_geometry.py` in the layout
environment.

Run checks with `npm run test:kg` and `npm run build`. The pipeline only produces candidate data; automatic fact acceptance and identity merging remain disabled until independent annotation and calibration are available.

Artifact carrier types can be added separately from cached catalog names with
`python3 scripts/enrich_artifact_types.py --write --persist`. This does not rerun
OCR, UIE, LTP or image annotation. It binds an explicit carrier name to its exact
catalog record, separates motif content from the carrier, and preserves the name
span as evidence. Shape modifiers, parenthetical view descriptions, merged captions
and unresolved records do not supply a guessed type. Type concepts are shared by
name while individual artifacts remain separate. The current atlas gains `:artifact_type`
relations and an `artifactType` structured query filter. The atlas exposes types in
the catalog, global search, entity switcher, clickable detail/page labels and 2D/3D
graphs. Each graph can cluster by any other populated dimension. River and specimen
filters include untyped records as a separate option; undated river records remain
in the pending-date list. Symbolic comparison supports `kind: "artifact_type"`,
comparing recorded motifs and materials with coverage counts. All existing image
roles are retained. Symbolic meanings are not extracted by this rule.

Other simple dimensions use `scripts/enrich_simple_dimensions.py --write --persist`
in an isolated Python environment with `scripts/requirements-kg-dimensions.txt` and
CUDA PyTorch. The runner reuses cached OCR, applies pinned local UIE and multilingual
GLiNER weights to individual catalog records, caches raw predictions, then writes
source-bound candidates to the three graphs, SQLite and the existing merged atlas.
No LLM/API calls, OCR rerun or image replacement is involved. Every new assertion
must have a model prediction with exact source offsets, score, model and revision;
rules only validate ownership, relation context, field type and normalized names.
There is no dictionary fallback for missing model spans. Reports distinguish model
outputs from candidates that survive validation; neither is an accuracy estimate.
The atlas exposes populated dimensions through the catalog's additional-dimensions
menu, search, detail labels and additional graph clustering. Location relationships
retain separate excavation, discovery and collection predicates; institutions are
separate from places. Interpretive meaning and transmission remain out of scope.

Symbolic meanings and religious context are added with
`python3 scripts/enrich_interpretations.py --write --persist`. Local Chinese UIE
first extracts short meaning labels, then subjects, then verifies each pairing
with a subject-specific relation query. Neural predictions are cached. Paragraph
boundaries exclude neighboring figure captions from relation context. Raw OCR and
source spans remain unchanged; no OCR or LLM calls are involved. This stage does
not store a separate uncertainty/modality field, per the requested presentation.

Interpretations are stored in `graph.interpretations`, SQLite
`kg_interpretations` and the atlas manifest. Each retains its subject, short label,
original passage, page and model provenance. They remain separate from artifact
facts: an interpretation node links to its subject using `:interpretation_subject`
and to a meaning with `:interpreted_as` (or `:religious_context`). No meaning is
automatically assigned to every artifact with the same motif. The atlas exposes
these through the additional catalog dimensions, text search, source-page links
and attribute cards in the 2D/3D graph. They can also be queried through SPARQL or the local
`interpretations` action. Existing artifact data, identity mappings and images are
preserved.

Symbolic meanings and beliefs are displayed as properties of the focused pattern,
with clickable tags expanding the original passages and source-page links. The
UI indexes these records once, groups equivalent pattern/纹/纹样 spellings and
deduplicates repeated values while retaining all source records. Artifact details
show these under the corresponding pattern's document interpretation, without
writing them onto the artifact. The catalog action is “查看属性”; subjects without
a catalog cluster retain a single subject view with the same property card. This
display projection adds no meaning/belief nodes or edges to the star atlas and
does not change stored RDF or extraction data.

The full-text recall pass is `scripts/enrich_fulltext_recall.py --write --persist`
in the same isolated model environment. It reuses the pinned local UIE weights
without training, API calls or OCR reruns. Every PP-Structure page is covered by
overlapping token windows; isolated captions and prose paragraphs provide extra
views. Records with segmentation issues are still scanned, while artifact binding
requires an existing typed artifact owner. Prose relations stay on concept-level
source statements instead of being copied to similarly named catalog artifacts.

Value-first and subject-conditioned queries contribute a union of candidates;
`涵义`, craft and composition queries cover gaps in the initial schemas. Model
endpoint decoding and per-field screening thresholds are recorded explicitly.
Relation confirmation is supporting evidence, not a mandatory third successful
model pass. When local NER returns no subject, aligned mentions of existing graph
motifs can supply an anchor; this route requires an explicit subject-conditioned
UIE value prediction and never creates a relation from a name lookup alone.
Full predicted descriptions are retained before short-label splitting
and normalization. Negative contexts, unsupported ownership and rejected values
remain in `data/local-kg/fulltext-recall/decisions.json`. Per-page processing
coverage is in `coverage.json`; neither processing coverage nor model scores are
an independently measured fact recall or precision estimate.

Caption-level craft and composition results become regular artifact assertions.
Prose results extend `graph.interpretations` with `technique` and `composition`
kinds, mapped to `:uses_technique` and `:has_composition` on source statement
nodes. The atlas's “文献关系” entry includes these alongside symbolic, religious
and ritual interpretations. The writer extends `sourceItems`/`sourceRows` first,
then reapplies the existing artifact identity projection; image URLs and identity
decisions are preserved. Raw model predictions are cached for repeatable filtering
and incremental reruns. Reports explicitly record zero fine-tuning and no measured
semantic accuracy.
