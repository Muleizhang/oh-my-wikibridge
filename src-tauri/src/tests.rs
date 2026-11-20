use crate::{
    ingest::Unit,
    knowledge, opencode,
    store::{State, Store},
};
use std::{fs, io::Write, path::Path};
use zip::{ZipWriter, write::SimpleFileOptions};

fn workspace(dir: &tempfile::TempDir) -> Store {
    Store::new(dir.path().join("database")).unwrap()
}

fn import_text(store: &Store, id: &str, path: &Path, content: &str) {
    fs::write(path, content).unwrap();
    let imported = store.begin_import(id, path).unwrap();
    assert_eq!(
        imported.source.status, "draft",
        "{:?}",
        imported.source.error
    );
}

#[test]
fn roles_and_publication_preserve_source_versions() {
    let directory = tempfile::tempdir().unwrap();
    let state = State::new(directory.path().join("database")).unwrap();
    let store = &state.store;
    assert!(state.require_admin("guest").is_err());
    let token = state.login("test password").unwrap();
    assert!(state.login("wrong password").is_err());
    state.require_admin(&token).unwrap();

    let corpus = store.create_corpus("纹样", "").unwrap();
    let second = store.create_corpus("器物", "").unwrap();
    let first_scope = vec![corpus.clone()];
    let second_scope = vec![second.clone()];
    let path = directory.path().join("研究笔记.md");
    import_text(
        store,
        &corpus,
        &path,
        "(云气纹, 记录于, 汉代漆器)\n云气纹用于汉代漆器的彩绘。",
    );
    import_text(
        store,
        &second,
        &directory.path().join("其他文本.txt"),
        "云气纹与铜镜。",
    );

    let original = store.sources(&corpus, true).unwrap().remove(0);
    let draft_evidence = store.review(&corpus).unwrap().evidence.remove(0);
    assert_eq!(draft_evidence.sha256, original.sha256);
    assert!(store.evidence(&draft_evidence.id, false).is_err());
    assert!(store.read_range(&original.id, 0, 4, false).is_err());
    assert!(store.open_source(&original.id, false).is_err());
    assert!(store.corpora(false).unwrap().is_empty());
    assert!(
        knowledge::search(store, "云气纹", &first_scope, "hybrid", 10)
            .unwrap()
            .hits
            .is_empty()
    );
    assert!(
        !knowledge::graph(store, &first_scope, true, &[])
            .unwrap()
            .is_empty()
    );

    assert_eq!(store.publish(&corpus).unwrap(), 1);
    assert_eq!(store.corpora(false).unwrap().len(), 1);
    let hits = knowledge::search(store, "云气纹", &first_scope, "tfidf", 10)
        .unwrap()
        .hits;
    assert!(hits.iter().any(|hit| hit.evidence.id == draft_evidence.id));
    assert!(
        knowledge::search(store, "云气纹", &second_scope, "hybrid", 10)
            .unwrap()
            .hits
            .is_empty()
    );
    let facts = knowledge::graph(store, &first_scope, false, &[]).unwrap();
    assert!(
        facts
            .iter()
            .any(|fact| fact.relation == "记录于" && fact.evidence_id == draft_evidence.id)
    );
    assert!(facts.iter().any(|fact| fact.relation == "同句提及"));
    assert!(store.begin_import(&corpus, &path).unwrap().duplicate);
    let response = opencode::ask(store, "云气纹", &first_scope).unwrap();
    assert!(response.answer.is_none());
    assert_eq!(response.model.as_deref(), Some("homo/gpt-6.1-terra"));
    assert_eq!(response.trace.last().unwrap().tool, "query_graph");
    assert!(!response.evidence.is_empty());

    import_text(store, &corpus, &path, "新版本记录莲花纹与唐代铜镜。");
    assert!(store.evidence(&draft_evidence.id, false).is_ok());
    assert_eq!(store.publish(&corpus).unwrap(), 2);
    assert!(store.evidence(&draft_evidence.id, false).is_err());
    assert!(store.evidence(&draft_evidence.id, true).is_ok());
    assert!(
        knowledge::search(store, "莲花纹", &first_scope, "hybrid", 10)
            .unwrap()
            .hits
            .len()
            == 1
    );
    assert_eq!(store.publish(&second).unwrap(), 1);
    let combined = knowledge::search(store, "云气纹", &[corpus, second], "hybrid", 10)
        .unwrap()
        .hits;
    assert!(!combined.is_empty());
    assert!(
        combined
            .iter()
            .any(|hit| hit.evidence.corpus_name == "器物")
    );
    assert!(
        combined
            .iter()
            .any(|hit| hit.evidence.corpus_name == "纹样")
    );
    state.logout(&token).unwrap();
    assert!(state.require_admin(&token).is_err());
}

#[test]
fn incomplete_ocr_can_retry_and_is_not_public() {
    let directory = tempfile::tempdir().unwrap();
    let store = workspace(&directory);
    let corpus = store.create_corpus("扫描件", "").unwrap();
    let path = directory.path().join("scan.pdf");
    fs::write(
        &path,
        b"stub bytes; the browser submits extracted page data",
    )
    .unwrap();
    let imported = store.begin_import(&corpus, &path).unwrap();
    let id = imported.source.id;
    assert!(imported.needs_extraction);
    assert_eq!(imported.source.status, "queued");
    assert_eq!(store.read_range(&id, 0, 4, true).unwrap(), b"stub");
    store.start_ocr(&id).unwrap();
    let page = Unit {
        kind: "page".into(),
        ordinal: 12,
        locator: "PDF 第 12 页".into(),
        text: "战国纹样图版，铜镜，龙纹。".into(),
        method: "ocr".into(),
        confidence: Some(0.61),
    };
    store.add_units(&id, std::slice::from_ref(&page)).unwrap();
    store.fail(&id, "interrupted").unwrap();
    assert!(store.publish(&corpus).is_err());
    let retry = store.retry(&id).unwrap();
    assert_eq!(retry.source.unit_count, 0);
    store.add_units(&id, std::slice::from_ref(&page)).unwrap();
    store.add_units(&id, std::slice::from_ref(&page)).unwrap();
    store.finish(&id).unwrap();
    let review = store.review(&corpus).unwrap();
    assert_eq!((review.ocr_count, review.low_confidence_count), (1, 1));
    assert_eq!(review.evidence[0].ordinal, 12);
    store.publish(&corpus).unwrap();
    assert_eq!(store.sources(&corpus, false).unwrap()[0].unit_count, 1);
}

fn office(path: &Path, parts: &[(&str, &str)]) {
    let mut archive = ZipWriter::new(fs::File::create(path).unwrap());
    for (name, body) in parts {
        archive
            .start_file(*name, SimpleFileOptions::default())
            .unwrap();
        archive.write_all(body.as_bytes()).unwrap();
    }
    archive.finish().unwrap();
}

#[test]
fn office_import_preserves_paragraph_slide_and_cell_locators() {
    let directory = tempfile::tempdir().unwrap();
    let store = workspace(&directory);
    let id = store.create_corpus("课堂", "").unwrap();
    let docx = directory.path().join("test.docx");
    office(
        &docx,
        &[(
            "word/document.xml",
            r#"
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
            <w:body><w:p/><w:p><w:r><w:t>陶瓷文本</w:t></w:r></w:p></w:body>
        </w:document>"#,
        )],
    );
    let pptx = directory.path().join("test.pptx");
    office(
        &pptx,
        &[
            (
                "ppt/presentation.xml",
                r#"<p:presentation xmlns:p="p" xmlns:r="r"><p:sldIdLst><p:sldId r:id="two"/><p:sldId r:id="one"/></p:sldIdLst></p:presentation>"#,
            ),
            (
                "ppt/_rels/presentation.xml.rels",
                r#"<Relationships><Relationship Id="one" Target="slides/slide1.xml"/><Relationship Id="two" Target="slides/slide2.xml"/></Relationships>"#,
            ),
            (
                "ppt/slides/slide1.xml",
                r#"<p:sld xmlns:p="p" xmlns:a="a"><a:p><a:r><a:t>第二张放映</a:t></a:r></a:p></p:sld>"#,
            ),
            (
                "ppt/slides/slide2.xml",
                r#"<p:sld xmlns:p="p" xmlns:a="a"><a:p><a:r><a:t>陶瓷幻灯片</a:t></a:r></a:p></p:sld>"#,
            ),
        ],
    );
    let xlsx = directory.path().join("test.xlsx");
    office(
        &xlsx,
        &[
            (
                "xl/workbook.xml",
                r#"<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="统计" sheetId="1" r:id="rId1"/></sheets></workbook>"#,
            ),
            (
                "xl/_rels/workbook.xml.rels",
                r#"<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>"#,
            ),
            (
                "xl/worksheets/sheet1.xml",
                r#"<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="7"><c r="C7" t="inlineStr"><is><t>陶瓷表格</t></is></c></row></sheetData></worksheet>"#,
            ),
        ],
    );
    for path in [docx, pptx, xlsx] {
        let result = store.begin_import(&id, &path).unwrap();
        assert_eq!(result.source.status, "draft", "{:?}", result.source.error);
    }
    store.publish(&id).unwrap();
    let hits = knowledge::search(&store, "陶瓷", &[id], "keyword", 10)
        .unwrap()
        .hits;
    let evidence: Vec<_> = hits.into_iter().map(|hit| hit.evidence).collect();
    assert_eq!(evidence.len(), 3);
    assert!(
        evidence
            .iter()
            .any(|item| item.extension == "docx" && item.ordinal == 2)
    );
    assert!(
        evidence
            .iter()
            .any(|item| item.extension == "pptx" && item.ordinal == 1)
    );
    assert!(evidence.iter().any(|item| item.extension == "xlsx"
        && item.locator == "统计 · 第 7 行"
        && item.text.starts_with("C7:")));
}

#[test]
#[ignore = "sends synthetic evidence through the configured OpenCode model"]
fn configured_opencode_smoke() {
    let directory = tempfile::tempdir().unwrap();
    let store = workspace(&directory);
    let corpus = store.create_corpus("合成测试", "").unwrap();
    import_text(
        &store,
        &corpus,
        &directory.path().join("synthetic.txt"),
        "(WikiBridge fixture, test color, emerald green)\nThe WikiBridge fixture test color is emerald green.",
    );
    store.publish(&corpus).unwrap();
    opencode::configure(&store, "", "homo/gpt-6.1-terra", true).unwrap();
    let result = opencode::ask(
        &store,
        "What is the WikiBridge fixture test color?",
        &[corpus],
    )
    .unwrap();
    let answer = result
        .answer
        .expect(&format!("OpenCode smoke test: {:?}", result.error));
    assert!(answer.to_lowercase().contains("green"), "{answer}");
    assert!(answer.contains("[1]") || answer.contains("[2]"), "{answer}");
    assert_eq!(result.trace.last().unwrap().tool, "opencode_generate");
}
