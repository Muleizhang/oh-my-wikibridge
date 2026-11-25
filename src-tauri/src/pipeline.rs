//! Typed pipeline reads and append-only manual review decisions.
use crate::store::{Result, Store, sql};
use rusqlite::{OptionalExtension, params};

#[cfg(test)]
pub fn latest(store: &Store) -> Result<serde_json::Value> {
    latest_version(store, None)
}

pub fn latest_version(store: &Store, version: Option<&str>) -> Result<serde_json::Value> {
    let connection = store.connect()?;
    let row: Option<(String, String)> = sql(connection.query_row(
        "SELECT id,graph_json FROM kg_runs WHERE state='complete' AND (?1 IS NULL OR json_extract(graph_json,'$.version')=?1) ORDER BY created_at DESC, rowid DESC LIMIT 1",
        [version], |row| Ok((row.get(0)?, row.get(1)?)),
    ).optional())?;
    let (id, text) = row.ok_or("尚未生成所选版本的本地语料图谱。")?;
    let mut graph: serde_json::Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    if graph.get("version").and_then(|v| v.as_str()) == Some("typed-kg-v2") {
        let mut statement = sql(connection.prepare("SELECT id,target_kind,target_id,decision,reviewer,note,created_at FROM kg_reviews WHERE run_id=?1 ORDER BY rowid"))?;
        let rows = sql(statement.query_map([&id], |r| Ok(serde_json::json!({
            "id":r.get::<_,String>(0)?,"targetKind":r.get::<_,String>(1)?,"targetId":r.get::<_,String>(2)?,
            "decision":r.get::<_,String>(3)?,"reviewer":r.get::<_,String>(4)?,"note":r.get::<_,String>(5)?,"createdAt":r.get::<_,String>(6)?
        }))))?;
        graph["reviews"] = serde_json::Value::Array(sql(rows.collect())?);
        let mut regions =
            sql(connection
                .prepare("SELECT assertion_id,regions FROM kg_plate_regions WHERE run_id=?1"))?;
        let pairs = sql(regions.query_map([&id], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        }))?;
        let mut plate_regions = serde_json::Map::new();
        for pair in pairs {
            let (key, value) = sql(pair)?;
            plate_regions.insert(
                key,
                serde_json::from_str(&value).map_err(|e| e.to_string())?,
            );
        }
        graph["plateRegions"] = serde_json::Value::Object(plate_regions);
        graph["runId"] = serde_json::Value::String(id);
    }
    Ok(graph)
}

pub fn review(
    store: &Store,
    run_id: &str,
    target_kind: &str,
    target_id: &str,
    decision: &str,
    reviewer: &str,
    note: &str,
) -> Result<String> {
    if !matches!(decision, "accept" | "reject" | "revoke")
        || !matches!(target_kind, "assertion" | "identity")
        || reviewer.trim().is_empty()
        || reviewer.len() > 160
        || note.trim().is_empty()
        || note.len() > 4000
    {
        return Err("请填写复核者与依据，并选择有效操作。".into());
    }
    let conn = store.connect()?;
    let text: String = sql(conn.query_row(
        "SELECT graph_json FROM kg_runs WHERE id=?1 AND state='complete'",
        [run_id],
        |r| r.get(0),
    ))?;
    let graph: serde_json::Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    let key = if target_kind == "assertion" {
        "assertions"
    } else {
        "identityProposals"
    };
    let target = graph[key]
        .as_array()
        .and_then(|items| items.iter().find(|x| x["id"].as_str() == Some(target_id)))
        .ok_or("该条目不属于这次运行。")?;
    if decision == "accept" && target_kind == "assertion" {
        let blocked = [
            "unresolved_subject",
            "unresolved_object",
            "quantity_dimension_mismatch",
            "quantity_owner_not_artifact",
            "missing_evidence",
            "relation_subject_type",
            "relation_object_type",
            "field_value_type_conflict",
            "relation_definition_pending",
        ];
        if target["issues"].as_array().is_some_and(|items| {
            items
                .iter()
                .any(|v| v.as_str().is_some_and(|s| blocked.contains(&s)))
        }) {
            return Err("该陈述仍有对象或类型错误，请先修订数据，不能直接确认为事实。".into());
        }
    }
    if decision == "accept"
        && target_kind == "identity"
        && target["typeAgreement"].as_bool() != Some(true)
    {
        return Err("候选对象类型不一致，请先修订类型。".into());
    }
    let id = uuid::Uuid::new_v4().to_string();
    sql(conn.execute("INSERT INTO kg_reviews(id,run_id,target_kind,target_id,decision,reviewer,note) VALUES (?1,?2,?3,?4,?5,?6,?7)",
        params![id,run_id,target_kind,target_id,decision,reviewer.trim(),note.trim()]))?;
    Ok(id)
}
