use crate::store::{EVIDENCE_SELECT, Evidence, Result, Store, map_evidence, sql};
use jieba_rs::Jieba;
use nalgebra::DMatrix;
use oxigraph::{
    model::{GraphName, Literal, NamedNode, Quad},
    sparql::{QueryResults, SparqlEvaluator},
    store::Store as RdfStore,
};
use rand::{Rng, SeedableRng, rngs::StdRng};
use regex::Regex;
use rusqlite::{Connection, params_from_iter};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeSet, HashMap},
    sync::LazyLock,
};

static JIEBA: LazyLock<Jieba> = LazyLock::new(Jieba::new);
static TRIPLE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
    r"^[\s（(]*([^，,→|（）()]{1,80})\s*[,，|→]\s*([^，,→|（）()]{1,30})\s*[,，|→]\s*([^，,→|（）()]{1,80})[）)]?\s*$"
).expect("static regular expression")
});
static CONCEPT: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
    r"凤鸟纹|鸟纹|龙纹|夔纹|蟠螭纹|饕餮纹|兽面纹|云气纹|云纹|雷纹|云雷纹|莲花纹|忍冬纹|卷草纹|联珠纹|几何纹|动物纹|植物纹|人物纹|新石器时代|春秋|西周|商代|战国|秦代|汉代|魏晋|南北朝|隋代|唐代|五代|青铜器|铜镜|漆器|玉器|陶器|陶瓷|织绣|金银器|壁画|瓦当|画像石|画像砖|敦煌"
).expect("static regular expression")
});

pub fn tokens(text: &str) -> Vec<String> {
    let lower = text.to_lowercase();
    JIEBA
        .cut(&lower, false)
        .into_iter()
        .filter_map(|token| {
            let word: String = token
                .chars()
                .filter(|char| char.is_alphanumeric())
                .collect();
            (!word.is_empty()).then_some(word)
        })
        .collect()
}

pub fn chunks(text: &str) -> Vec<&str> {
    let mut result = Vec::new();
    let mut start = 0;
    let mut length = 0;
    for (index, character) in text.char_indices() {
        length += 1;
        if length >= 760
            || (length >= 420 && matches!(character, '\n' | '。' | '！' | '？' | '；' | '.'))
        {
            let end = index + character.len_utf8();
            let chunk = text[start..end].trim();
            if !chunk.is_empty() {
                result.push(chunk);
            }
            start = end;
            length = 0;
        }
    }
    let chunk = text[start..].trim();
    if !chunk.is_empty() {
        result.push(chunk);
    }
    result
}

pub fn extract(text: &str) -> BTreeSet<(String, String, String)> {
    let mut facts = BTreeSet::new();
    for line in text.lines() {
        let trimmed = line.trim();
        // Accept explicitly marked triples, or the documented arrow form.
        if (trimmed.starts_with(['(', '（']) || trimmed.matches('→').count() == 2)
            && let Some(parts) = TRIPLE.captures(trimmed)
        {
            let triple = (
                parts[1].trim().to_owned(),
                parts[2].trim().to_owned(),
                parts[3].trim().to_owned(),
            );
            if !triple.0.is_empty() && !triple.1.is_empty() && !triple.2.is_empty() {
                facts.insert(triple);
            }
        }
    }
    for sentence in text.split(['。', '！', '？', '；', '\n']) {
        let terms: BTreeSet<_> = CONCEPT
            .find_iter(sentence)
            .map(|entry| entry.as_str())
            .collect();
        for motif in terms.iter().filter(|term| term.ends_with('纹')) {
            for term in terms.iter().filter(|term| !term.ends_with('纹')) {
                facts.insert((motif.to_string(), "同句提及".into(), term.to_string()));
            }
        }
    }
    facts
}

fn scope(ids: &[String]) -> Result<String> {
    if ids.is_empty() || ids.len() > 128 {
        return Err("请选择 1–128 个已发布的语料库。".into());
    }
    Ok(std::iter::repeat_n("?", ids.len())
        .collect::<Vec<_>>()
        .join(","))
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Hit {
    pub evidence: Evidence,
    pub score: f64,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Fact {
    pub subject: String,
    pub relation: String,
    pub object: String,
    pub evidence_id: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SearchResult {
    pub hits: Vec<Hit>,
    pub trace: Vec<Trace>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Trace {
    pub tool: String,
    pub detail: String,
    pub evidence_ids: Vec<String>,
}

fn by_fts(conn: &Connection, terms: &[String], ids: &[String]) -> Result<Vec<Hit>> {
    let placeholders = scope(ids)?;
    let query = format!(
        "{EVIDENCE_SELECT} JOIN chunks_fts ON chunks_fts.rowid=c.seq
        WHERE s.status='published' AND s.corpus_id IN ({placeholders}) AND chunks_fts MATCH ?
        ORDER BY bm25(chunks_fts), c.seq LIMIT 90"
    );
    let expression = terms
        .iter()
        .map(|term| format!("\"{term}\""))
        .collect::<Vec<_>>()
        .join(" OR ");
    let mut statement = sql(conn.prepare(&query))?;
    let evidence = sql(statement.query_map(
        params_from_iter(ids.iter().chain(std::iter::once(&expression))),
        map_evidence,
    ))?;
    let values = sql(evidence.collect::<rusqlite::Result<Vec<_>>>())?;
    Ok(values
        .into_iter()
        .enumerate()
        .map(|(index, evidence)| Hit {
            evidence,
            score: 1.0 / (index as f64 + 1.0),
        })
        .collect())
}

fn sample(store: &Store, ids: &[String], limit: u32) -> Result<Vec<Evidence>> {
    let placeholders = scope(ids)?;
    let conn = store.connect()?;
    let mut statement = sql(conn.prepare(&format!(
        "{EVIDENCE_SELECT} WHERE s.status='published' AND s.corpus_id IN ({placeholders})
        ORDER BY ((c.seq*104729)%85159) LIMIT {limit}"
    )))?;
    let rows = sql(statement.query_map(params_from_iter(ids), map_evidence))?;
    sql(rows.collect())
}

pub fn search(
    store: &Store,
    query: &str,
    ids: &[String],
    mode: &str,
    limit: usize,
) -> Result<SearchResult> {
    if query.chars().count() > 600 {
        return Err("查询最多 600 个字符。".into());
    }
    if !matches!(mode, "keyword" | "tfidf" | "hybrid") {
        return Err("未知检索模式。".into());
    }
    let raw_tokens = tokens(query);
    let keywords: BTreeSet<String> = raw_tokens
        .iter()
        .filter(|word| {
            !matches!(
                word.as_str(),
                "的" | "和"
                    | "与"
                    | "是"
                    | "有"
                    | "在"
                    | "什么"
                    | "哪些"
                    | "如何"
                    | "以及"
                    | "请"
                    | "the"
                    | "and"
                    | "of"
                    | "what"
                    | "a"
                    | "is"
                    | "in"
            )
        })
        .take(32)
        .cloned()
        .collect();
    let terms: Vec<_> = if keywords.is_empty() {
        raw_tokens.into_iter().take(32).collect()
    } else {
        keywords.into_iter().collect()
    };
    if terms.is_empty() {
        return Err("请输入可检索的关键词。".into());
    }
    let conn = store.connect()?;
    let baseline = by_fts(&conn, &terms, ids)?;
    let mut trace = vec![Trace {
        tool: "search_fts".into(),
        detail: format!("{} 个分词，{} 条候选证据", terms.len(), baseline.len()),
        evidence_ids: baseline
            .iter()
            .take(limit)
            .map(|hit| hit.evidence.id.clone())
            .collect(),
    }];
    let mut hits = baseline;
    if mode != "keyword" && !hits.is_empty() {
        let document_terms: Vec<_> = hits
            .iter()
            .map(|hit| frequencies(tokens(&hit.evidence.text)))
            .collect();
        let query_terms = frequencies(terms);
        let mut document_frequency = HashMap::new();
        for document in &document_terms {
            for term in document.keys() {
                *document_frequency.entry(term.clone()).or_insert(0usize) += 1;
            }
        }
        let count = document_terms.len() as f64;
        let weight = |term: &str, frequency: usize| {
            (1.0 + (frequency as f64).ln())
                * (1.0
                    + ((count + 1.0) / (*document_frequency.get(term).unwrap_or(&0) as f64 + 1.0))
                        .ln())
        };
        let query_norm = query_terms
            .iter()
            .map(|(term, count)| weight(term, *count).powi(2))
            .sum::<f64>()
            .sqrt();
        for (hit, document) in hits.iter_mut().zip(document_terms) {
            let norm = document
                .iter()
                .map(|(term, count)| weight(term, *count).powi(2))
                .sum::<f64>()
                .sqrt();
            let dot: f64 = query_terms
                .iter()
                .filter_map(|(term, count)| {
                    Some(weight(term, *count) * weight(term, *document.get(term)?))
                })
                .sum();
            let cosine = if norm * query_norm > 0.0 {
                dot / (norm * query_norm)
            } else {
                0.0
            };
            hit.score = if mode == "hybrid" {
                0.75 * cosine + 0.25 * hit.score
            } else {
                cosine
            };
        }
        hits.sort_by(|first, second| second.score.total_cmp(&first.score));
        trace.push(Trace {
            tool: if mode == "hybrid" {
                "rank_hybrid"
            } else {
                "rank_tfidf"
            }
            .into(),
            detail: format!("对 {} 条候选证据计算 TF-IDF 余弦相似度", hits.len()),
            evidence_ids: hits
                .iter()
                .take(limit)
                .map(|hit| hit.evidence.id.clone())
                .collect(),
        });
    }
    hits.truncate(limit);
    Ok(SearchResult { hits, trace })
}

fn frequencies(words: Vec<String>) -> HashMap<String, usize> {
    let mut result = HashMap::new();
    for word in words {
        *result.entry(word).or_insert(0) += 1;
    }
    result
}

fn facts(store: &Store, ids: &[String], reviewer: bool, evidence: &[String]) -> Result<Vec<Fact>> {
    let columns = scope(ids)?;
    let conn = store.connect()?;
    let status = if reviewer {
        "s.status='draft'"
    } else {
        "s.status='published'"
    };
    let selected = if evidence.is_empty() {
        String::new()
    } else {
        format!(" AND f.chunk_id IN ({})", scope(evidence)?)
    };
    let mut statement = sql(conn.prepare(&format!(
        "SELECT f.subject,f.relation,f.object,f.chunk_id
         FROM facts f JOIN chunks c ON f.chunk_id=c.id JOIN units u ON c.unit_id=u.id
         JOIN sources s ON u.source_id=s.id
         WHERE {status} AND s.corpus_id IN ({columns}){selected} ORDER BY c.seq,f.subject,f.relation,f.object LIMIT 150"
    )))?;
    let rows = sql(
        statement.query_map(params_from_iter(ids.iter().chain(evidence)), |row| {
            Ok(Fact {
                subject: row.get(0)?,
                relation: row.get(1)?,
                object: row.get(2)?,
                evidence_id: row.get(3)?,
            })
        }),
    )?;
    sql(rows.collect())
}

fn identifier(namespace: &str, label: &str) -> NamedNode {
    NamedNode::new_unchecked(format!(
        "urn:wikibridge:{namespace}:{:x}",
        Sha256::digest(label.as_bytes())
    ))
}

fn as_rdf(facts: &[Fact]) -> Result<RdfStore> {
    let db = RdfStore::new().map_err(|error| error.to_string())?;
    let label = NamedNode::new_unchecked("http://www.w3.org/2000/01/rdf-schema#label");
    for fact in facts {
        let subject = identifier("concept", &fact.subject);
        let relation = identifier("relation", &fact.relation);
        let object = identifier("concept", &fact.object);
        let graph = identifier("evidence", &fact.evidence_id);
        for quad in [
            Quad::new(
                subject.clone(),
                relation.clone(),
                object.clone(),
                GraphName::NamedNode(graph.clone()),
            ),
            Quad::new(
                subject,
                label.clone(),
                Literal::new_simple_literal(&fact.subject),
                GraphName::DefaultGraph,
            ),
            Quad::new(
                relation,
                label.clone(),
                Literal::new_simple_literal(&fact.relation),
                GraphName::DefaultGraph,
            ),
            Quad::new(
                object,
                label.clone(),
                Literal::new_simple_literal(&fact.object),
                GraphName::DefaultGraph,
            ),
            Quad::new(
                graph,
                label.clone(),
                Literal::new_simple_literal(&fact.evidence_id),
                GraphName::DefaultGraph,
            ),
        ] {
            db.insert(&quad).map_err(|error| error.to_string())?;
        }
    }
    Ok(db)
}

pub fn graph(
    store: &Store,
    ids: &[String],
    reviewer: bool,
    evidence: &[String],
) -> Result<Vec<Fact>> {
    let facts = facts(store, ids, reviewer, evidence)?;
    let rdf = as_rdf(&facts)?;
    let query = "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?subject ?relation ?object ?evidence WHERE {
            GRAPH ?g { ?s ?p ?o }
            ?s rdfs:label ?subject . ?p rdfs:label ?relation . ?o rdfs:label ?object . ?g rdfs:label ?evidence .
        } ORDER BY ?subject ?relation ?object ?evidence";
    let query = SparqlEvaluator::new()
        .parse_query(query)
        .map_err(|error| error.to_string())?;
    let QueryResults::Solutions(solutions) = query
        .on_store(&rdf)
        .execute()
        .map_err(|error| error.to_string())?
    else {
        return Err("图谱查询未返回结果集。".into());
    };
    solutions
        .map(|solution| {
            let solution = solution.map_err(|error| error.to_string())?;
            let read = |key: &str| match solution.get(key) {
                Some(oxigraph::model::Term::Literal(value)) => value.value().to_owned(),
                _ => String::new(),
            };
            Ok(Fact {
                subject: read("subject"),
                relation: read("relation"),
                object: read("object"),
                evidence_id: read("evidence"),
            })
        })
        .collect()
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Analytics {
    pub sample_size: usize,
    pub top_terms: Vec<(String, usize)>,
    pub pairs: Vec<(String, String, u32)>,
    pub projection: Vec<(String, f64, f64)>,
    pub neighbors: Vec<(String, f64)>,
}

fn is_informative(word: &str) -> bool {
    word.chars().count() >= 2
        && !word.chars().all(|char| char.is_numeric())
        && !matches!(
            word,
            "一个"
                | "一种"
                | "可以"
                | "但是"
                | "这些"
                | "以及"
                | "进行"
                | "通过"
                | "不同"
                | "主要"
                | "其中"
                | "the"
                | "and"
                | "from"
                | "this"
                | "with"
        )
}

pub fn analysis(store: &Store, ids: &[String], keyword: &str) -> Result<Analytics> {
    let evidence = sample(store, ids, 240)?;
    let sentences: Vec<_> = evidence
        .iter()
        .map(|e| {
            tokens(&e.text)
                .into_iter()
                .filter(|word| is_informative(word))
                .take(120)
                .collect::<Vec<_>>()
        })
        .collect();
    Ok(analyze(&sentences, keyword))
}

fn analyze(sentences: &[Vec<String>], keyword: &str) -> Analytics {
    let frequency = frequencies(sentences.iter().flatten().cloned().collect());
    let mut ranked: Vec<_> = frequency
        .into_iter()
        .filter(|(_, count)| *count >= 2)
        .collect();
    ranked.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
    ranked.truncate(400);
    let vocabulary: HashMap<_, _> = ranked
        .iter()
        .enumerate()
        .map(|(id, (word, _))| (word.as_str(), id))
        .collect();
    let top_terms: Vec<_> = ranked.iter().take(18).cloned().collect();
    let n = top_terms.len();
    let mut counts = DMatrix::<f64>::zeros(n, n);
    let ids: Vec<Vec<Option<usize>>> = sentences
        .iter()
        .map(|words| {
            words
                .iter()
                .map(|word| vocabulary.get(word.as_str()).copied())
                .collect()
        })
        .collect();
    for sentence in &ids {
        for (i, left) in sentence.iter().enumerate() {
            let Some(left) = left.filter(|id| *id < n) else {
                continue;
            };
            for j in i + 1..(i + 3).min(sentence.len()) {
                let Some(right) = sentence[j].filter(|id| *id < n) else {
                    continue;
                };
                counts[(left, right)] += 1.0;
                counts[(right, left)] += 1.0;
            }
        }
    }
    let mut pairs = Vec::new();
    for i in 0..n {
        for j in i + 1..n {
            if counts[(i, j)] > 0.0 {
                pairs.push((
                    ranked[i].0.clone(),
                    ranked[j].0.clone(),
                    counts[(i, j)] as u32,
                ));
            }
        }
    }
    pairs.sort_by(|a, b| b.2.cmp(&a.2));
    pairs.truncate(14);
    let mut projection = Vec::new();
    if n >= 2 && counts.iter().any(|value| *value > 0.0) {
        let svd = counts.svd(true, false);
        if let Some(u) = svd.u {
            for (index, (word, _)) in top_terms.iter().enumerate() {
                projection.push((
                    word.clone(),
                    u[(index, 0)] * svd.singular_values[0],
                    u[(index, 1)] * svd.singular_values[1],
                ));
            }
        }
    }
    let neighbors = vocabulary
        .get(keyword.trim().to_lowercase().as_str())
        .copied()
        .map(|target| skip_gram(&ids, &ranked, target))
        .unwrap_or_default();
    Analytics {
        sample_size: sentences.len(),
        top_terms,
        pairs,
        projection,
        neighbors,
    }
}

fn skip_gram(
    sentences: &[Vec<Option<usize>>],
    vocabulary: &[(String, usize)],
    target: usize,
) -> Vec<(String, f64)> {
    if vocabulary.len() < 2 {
        return Vec::new();
    }
    const DIM: usize = 24;
    let mut rng = StdRng::seed_from_u64(42);
    let mut input: Vec<[f32; DIM]> = (0..vocabulary.len())
        .map(|_| std::array::from_fn(|_| rng.random_range(-0.05..0.05)))
        .collect();
    let mut output = vec![[0.0f32; DIM]; vocabulary.len()];
    let mut weights = Vec::with_capacity(vocabulary.len());
    let mut total = 0.0;
    for (_, frequency) in vocabulary {
        total += (*frequency as f64).powf(0.75);
        weights.push(total);
    }
    for epoch in 0..3 {
        let rate = 0.045 - 0.01 * epoch as f32;
        for sentence in sentences {
            for (index, center) in sentence.iter().enumerate() {
                let Some(center) = *center else {
                    continue;
                };
                for (position, context) in sentence
                    .iter()
                    .enumerate()
                    .take(index + 3)
                    .skip(index.saturating_sub(2))
                {
                    if position == index {
                        continue;
                    }
                    let Some(context) = *context else {
                        continue;
                    };
                    let update = |i: &mut [f32; DIM], o: &mut [f32; DIM], label: f32| {
                        let dot: f32 = i.iter().zip(o.iter()).map(|(a, b)| a * b).sum();
                        let gradient = (label - 1.0 / (1.0 + (-dot).exp())) * rate;
                        for (input, output) in i.iter_mut().zip(o.iter_mut()) {
                            let previous = *input;
                            *input += gradient * *output;
                            *output += gradient * previous;
                        }
                    };
                    update(&mut input[center], &mut output[context], 1.0);
                    for _ in 0..3 {
                        let draw = rng.random_range(0.0..total);
                        let negative = weights.partition_point(|value| *value <= draw);
                        if negative != context {
                            update(&mut input[center], &mut output[negative], 0.0);
                        }
                    }
                }
            }
        }
    }
    let norm = |vector: &[f32; DIM]| vector.iter().map(|value| value.powi(2)).sum::<f32>().sqrt();
    let target_norm = norm(&input[target]);
    let mut neighbors: Vec<_> = vocabulary
        .iter()
        .enumerate()
        .filter(|(id, _)| *id != target)
        .map(|(id, (word, _))| {
            let dot: f32 = input[target]
                .iter()
                .zip(input[id].iter())
                .map(|(a, b)| a * b)
                .sum();
            (
                word.clone(),
                (dot / (target_norm * norm(&input[id]))) as f64,
            )
        })
        .collect();
    neighbors.sort_by(|a, b| b.1.total_cmp(&a.1));
    neighbors.truncate(10);
    neighbors
}
