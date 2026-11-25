"""Tests for scripts/merge_kg_volumes.py across both manifest.json and graph.json volume formats."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from merge_kg_volumes import merge_volumes


class MergeVolumesTest(unittest.TestCase):
    def test_merge_mixed_manifest_and_graph_volumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            # Volume 1: manifest.json format (商代 · 青铜 · 云雷纹)
            v1 = root / "vol1"
            (v1 / "assets").mkdir(parents=True)
            (v1 / "assets" / "p10.jpg").write_bytes(b"fake-jpg-v1")
            (v1 / "manifest.json").write_text(json.dumps({
                "title": "中国纹样全集 1",
                "pages": [{"page": 10, "previewUrl": "assets/p10.jpg", "entries": 1}],
                "items": [{
                    "artifactId": "a1", "artifact": "商代云雷纹青铜尊", "item": "图 1", "page": 10,
                    "locator": "第 10 页 · 图 1", "evidenceId": "a1",
                    "imageUrl": "assets/p10.jpg", "detailUrl": "assets/p10.jpg", "captionUrl": "",
                }],
                "rows": [
                    {"id": "a1:period", "artifactId": "a1", "artifact": "商代云雷纹青铜尊", "page": 10,
                     "predicate": "period", "object": "商代", "evidenceId": "a1", "imageUrl": "assets/p10.jpg"},
                    {"id": "a1:mat", "artifactId": "a1", "artifact": "商代云雷纹青铜尊", "page": 10,
                     "predicate": "made_of", "object": "青铜", "evidenceId": "a1", "imageUrl": "assets/p10.jpg"},
                    {"id": "a1:motif", "artifactId": "a1", "artifact": "商代云雷纹青铜尊", "page": 10,
                     "predicate": "decorated_with", "object": "云雷纹", "evidenceId": "a1", "imageUrl": "assets/p10.jpg"},
                ],
                "evidence": [{"id": "a1", "ordinal": 10, "locator": "第 10 页 · 图 1", "text": "商代云雷纹青铜尊",
                              "previewUrl": "assets/p10.jpg", "bbox": [0.1, 0.2, 0.5, 0.6]}],
            }, ensure_ascii=False))

            # Volume 2: graph.json format (汉代 · 漆器 · 云雷纹 — bridges across books via 云雷纹!)
            v2 = root / "vol2"
            (v2 / "images").mkdir(parents=True)
            (v2 / "images" / "v1-p0005.png").write_bytes(b"fake-png-v2")
            (v2 / "graph.json").write_text(json.dumps({
                "sourceContext": {"title": "中国纹样全集 2"},
                "documents": [{"page": 5, "imageSize": [1000, 1000]}],
                "records": [{"id": "rec1", "page": 5, "item": 2, "label": "汉代云雷纹漆盘", "text": "2.汉代云雷纹漆盘",
                             "bbox": [100, 200, 500, 400]}],
                "entities": [
                    {"id": "e-art", "kind": "artifact", "label": "汉代云雷纹漆盘", "recordId": "rec1"},
                    {"id": "e-per", "kind": "period", "label": "汉代"},
                    {"id": "e-mat", "kind": "material", "label": "漆器"},
                    {"id": "e-mot", "kind": "motif", "label": "云雷纹"},
                ],
                "events": [],
                "assertions": [
                    {"id": "s1", "subject": "e-art", "predicate": "period", "label": "时代",
                     "object": {"kind": "entity", "id": "e-per"}, "evidence": [{"page": 5, "text": "汉代"}], "issues": []},
                    {"id": "s2", "subject": "e-art", "predicate": "made_of", "label": "材质",
                     "object": {"kind": "entity", "id": "e-mat"}, "evidence": [{"page": 5, "text": "漆器"}], "issues": []},
                    {"id": "s3", "subject": "e-art", "predicate": "decorated_with", "label": "纹样",
                     "object": {"kind": "entity", "id": "e-mot"}, "evidence": [{"page": 5, "text": "云雷纹"}], "issues": []},
                ],
            }, ensure_ascii=False))

            # Volume 3: graph.json format (唐代 · 铜器 · 凤鸟纹)
            v3 = root / "vol3"
            (v3 / "images").mkdir(parents=True)
            (v3 / "images" / "v1-p0008.png").write_bytes(b"fake-png-v3")
            (v3 / "graph.json").write_text(json.dumps({
                "sourceContext": {"title": "中国纹样全集 3"},
                "documents": [{"page": 8, "imageSize": [1000, 1000]}],
                "records": [{"id": "rec1", "page": 8, "item": 1, "label": "唐代凤鸟纹铜镜", "text": "1.唐代凤鸟纹铜镜"}],
                "entities": [
                    {"id": "e-art", "kind": "artifact", "label": "唐代凤鸟纹铜镜", "recordId": "rec1"},
                    {"id": "e-per", "kind": "period", "label": "唐代"},
                    {"id": "e-mat", "kind": "material", "label": "铜器"},
                    {"id": "e-mot", "kind": "motif", "label": "凤鸟纹"},
                ],
                "events": [],
                "assertions": [
                    {"id": "s1", "subject": "e-art", "predicate": "period", "label": "时代",
                     "object": {"kind": "entity", "id": "e-per"}, "evidence": [{"page": 8, "text": "唐代"}], "issues": []},
                    {"id": "s2", "subject": "e-art", "predicate": "made_of", "label": "材质",
                     "object": {"kind": "entity", "id": "e-mat"}, "evidence": [{"page": 8, "text": "铜器"}], "issues": []},
                    {"id": "s3", "subject": "e-art", "predicate": "decorated_with", "label": "纹样",
                     "object": {"kind": "entity", "id": "e-mot"}, "evidence": [{"page": 8, "text": "凤鸟纹"}], "issues": []},
                ],
            }, ensure_ascii=False))

            out = root / "merged"
            merged = merge_volumes(
                [f"第一册={v1}", f"第二册={v2}", f"第三册={v3}"],
                out,
                title="中国纹样全集 · 三册总图谱",
                mode="copy",
                build_html=True,
            )

            self.assertEqual(len(merged["volumes"]), 3)
            self.assertEqual(len(merged["pages"]), 3)
            self.assertEqual(len(merged["items"]), 3)
            self.assertEqual(len(merged["rows"]), 9)
            self.assertTrue((out / "manifest.json").is_file())
            self.assertTrue((out / "index.html").is_file())
            # Verify bbox was normalized from pixels to [0..1]
            ev_v2 = next(e for e in merged["evidence"] if e["volume"] == "第二册")
            self.assertEqual(ev_v2["bbox"], [0.1, 0.2, 0.5, 0.4])
            # Verify shared semantic objectId across vol1 & vol2
            yunlei_rows = [r for r in merged["rows"] if r["object"] == "云雷纹"]
            self.assertEqual(len(yunlei_rows), 2)
            self.assertEqual(len({r["objectId"] for r in yunlei_rows}), 1)

            # Verify JS symbolic reasoner can trace a cross-volume path: 商代 (Vol1) -> 汉代 (Vol2) via 云雷纹,
            # AND 商代 (Vol1) -> 唐代 (Vol3) via RDFS ontology 青铜 ⊑ 铜器类 ⊒ 铜器!
            check_js = (
                "import { readFileSync } from 'node:fs';"
                "import { createKGReasoner } from './src/kg-reasoner.js';"
                f"const m = JSON.parse(readFileSync({json.dumps(str(out / 'manifest.json'))}, 'utf8'));"
                "const r = createKGReasoner(m);"
                "const p12 = r.findPaths('商代', '汉代', { useOntology: false });"
                "const p13 = r.findPaths('商代', '唐代', { useOntology: true });"
                "if (!p12.paths.length) throw new Error('Expected Vol1->Vol2 path via 云雷纹');"
                "if (!p13.paths.length) throw new Error('Expected Vol1->Vol3 ontology path via 铜器类');"
                "console.log('Cross-volume paths OK:', p12.paths[0].summary, '|', p13.paths[0].summary);"
            )
            res = subprocess.run(["node", "--input-type=module", "-e", check_js], check=True, capture_output=True, text=True)
            self.assertIn("Cross-volume paths OK", res.stdout)


if __name__ == "__main__":
    unittest.main()
