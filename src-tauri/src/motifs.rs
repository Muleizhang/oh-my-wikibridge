use crate::store::{Result, Store, sql};
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct Row {
    pub id: String,
    pub source_id: String,
    pub source_name: String,
    pub bytes: u64,
    pub artifact_id: String,
    pub artifact: String,
    pub item: u32,
    pub predicate: String,
    pub object: String,
    pub object_id: String,
    pub evidence_id: String,
    pub page: u32,
    pub quote: String,
    pub qualifiers: Vec<serde_json::Value>,
    pub regions: Option<Regions>,
}

#[derive(Clone, Serialize, Deserialize)]
pub struct Regions {
    pub artifact: [f64; 4],
    pub motif: [f64; 4],
}

pub fn rows(store: &Store, ids: &[String]) -> Result<Vec<Row>> {
    if ids.len() > 128 {
        return Err("最多可选择 128 个语料库。".into());
    }
    let conn = store.connect()?;
    let mut stmt = sql(conn.prepare(include_str!("published_motifs.sql")))?;
    let scope = serde_json::to_string(ids).map_err(|e| e.to_string())?;
    let rows = sql(stmt.query_map([scope], |r| r.get::<_, String>(0)))?;
    rows.map(|r| serde_json::from_str(&sql(r)?).map_err(|e| e.to_string()))
        .collect()
}

pub fn save_regions(store: &Store, run: &str, assertion: &str, regions: Regions) -> Result<()> {
    let valid =
        |b: [f64; 4]| b.iter().all(|v| (0.0..=1.0).contains(v)) && b[0] < b[2] && b[1] < b[3];
    if !valid(regions.artifact) || !valid(regions.motif) {
        return Err("选区必须位于页面内且具有有效面积。".into());
    }
    let conn = store.connect()?;
    let json = serde_json::to_string(&regions).map_err(|e| e.to_string())?;
    let changed = sql(conn.execute(
        "INSERT INTO kg_plate_regions(run_id,assertion_id,regions)
         SELECT run_id,id,?3 FROM kg_assertions WHERE run_id=?1 AND id=?2 AND predicate='decorated_with'
         ON CONFLICT(run_id,assertion_id) DO UPDATE SET regions=excluded.regions",
        rusqlite::params![run, assertion, json]))?;
    if changed == 0 {
        return Err("未找到该纹样陈述。".into());
    }
    Ok(())
}

pub fn matching<'a>(rows: &'a [Row], question: &str, selected_id: Option<&str>) -> Vec<&'a Row> {
    let motifs: Vec<_> = rows
        .iter()
        .filter(|r| {
            r.predicate == "decorated_with"
                && selected_id.map_or_else(|| question.contains(&r.object), |id| id == r.object_id)
        })
        .collect();
    // A longer motif name may contain another; do not mix their occurrences.
    let selected: Vec<_> = motifs
        .iter()
        .filter(|r| {
            !motifs.iter().any(|other| {
                other.object.len() > r.object.len()
                    && other.object.contains(&r.object)
                    && !question.replace(&other.object, "").contains(&r.object)
            })
        })
        .collect();
    rows.iter()
        .filter(|r| {
            selected.iter().any(|m| {
                m.artifact_id == r.artifact_id && (r.predicate != "decorated_with" || r.id == m.id)
            })
        })
        .collect()
}

pub fn asks_for_artifacts(question: &str, name: &str) -> bool {
    let text = question.trim().trim_end_matches(['？', '?', '。']);
    [
        format!("哪些器物饰有{name}？请列出书中已确认的时代、材质、工艺和出处"),
        format!("{name}出现在哪些器物上"),
        format!("哪些器物饰有{name}"),
        format!("哪些器物上有{name}"),
        format!("{name}装饰在哪些器物上"),
    ]
    .contains(&text.to_owned())
}

pub fn relation(predicate: &str) -> &str {
    match predicate {
        "decorated_with" => "饰有纹样",
        "period" => "所属时代",
        "made_of" => "材质",
        "uses_technique" => "制作工艺",
        _ => predicate,
    }
}
