mod ingest;
mod knowledge;
mod motifs;
mod opencode;
mod pipeline;
mod store;

use ingest::Unit;
use std::{io::Write, path::PathBuf};
use store::{Corpus, Evidence, Import, Result, Source, State as AppState};
use tauri::{
    Emitter, Manager, State, WindowEvent,
    ipc::Response,
    menu::{Menu, MenuItem},
    tray::{MouseButton, TrayIconBuilder, TrayIconEvent},
};

async fn worker<T: Send + 'static>(f: impl FnOnce() -> Result<T> + Send + 'static) -> Result<T> {
    tauri::async_runtime::spawn_blocking(f)
        .await
        .map_err(|error| error.to_string())?
}

#[tauri::command]
fn admin_exists(state: State<AppState>) -> Result<bool> {
    Ok(store::setting(&state.store.connect()?, "admin_hash")?.is_some())
}
#[tauri::command]
fn admin_login(state: State<AppState>, password: String) -> Result<String> {
    state.login(&password)
}
#[tauri::command]
fn admin_logout(state: State<AppState>, token: String) -> Result<()> {
    state.logout(&token)
}

fn admin_if_present(state: &AppState, token: Option<&str>) -> Result<bool> {
    if let Some(token) = token {
        state.require_admin(token)?;
        Ok(true)
    } else {
        Ok(false)
    }
}

#[tauri::command]
fn list_corpora(state: State<AppState>, token: Option<String>) -> Result<Vec<Corpus>> {
    state
        .store
        .corpora(admin_if_present(&state, token.as_deref())?)
}
#[tauri::command]
fn create_corpus(
    state: State<AppState>,
    token: String,
    name: String,
    description: String,
) -> Result<String> {
    state.require_admin(&token)?;
    state.store.create_corpus(&name, &description)
}
#[tauri::command]
fn list_sources(
    state: State<AppState>,
    corpus_id: String,
    token: Option<String>,
) -> Result<Vec<Source>> {
    state
        .store
        .sources(&corpus_id, admin_if_present(&state, token.as_deref())?)
}
#[tauri::command]
async fn begin_import(
    state: State<'_, AppState>,
    token: String,
    corpus_id: String,
    path: String,
) -> Result<Import> {
    state.require_admin(&token)?;
    let store = state.store.clone();
    worker(move || store.begin_import(&corpus_id, &PathBuf::from(path))).await
}
#[tauri::command]
async fn retry_import(
    state: State<'_, AppState>,
    token: String,
    source_id: String,
) -> Result<Import> {
    state.require_admin(&token)?;
    let store = state.store.clone();
    worker(move || store.retry(&source_id)).await
}
#[tauri::command]
async fn start_ocr(state: State<'_, AppState>, token: String, source_id: String) -> Result<Import> {
    state.require_admin(&token)?;
    let store = state.store.clone();
    worker(move || store.start_ocr(&source_id)).await
}
#[tauri::command]
async fn submit_units(
    state: State<'_, AppState>,
    token: String,
    source_id: String,
    units: Vec<Unit>,
) -> Result<()> {
    state.require_admin(&token)?;
    let store = state.store.clone();
    worker(move || {
        if units.len() > 20 {
            return Err("每批最多处理 20 个内容单元。".into());
        }
        store.add_units(&source_id, &units)
    })
    .await
}
#[tauri::command]
fn finish_import(state: State<AppState>, token: String, source_id: String) -> Result<()> {
    state.require_admin(&token)?;
    state.store.finish(&source_id)
}
#[tauri::command]
fn fail_import(
    state: State<AppState>,
    token: String,
    source_id: String,
    error: String,
) -> Result<()> {
    state.require_admin(&token)?;
    state.store.fail(&source_id, &error)
}
#[tauri::command]
async fn read_source_range(
    state: State<'_, AppState>,
    token: Option<String>,
    source_id: String,
    offset: u64,
    length: usize,
) -> Result<Response> {
    let admin = admin_if_present(&state, token.as_deref())?;
    let store = state.store.clone();
    worker(move || {
        store
            .read_range(&source_id, offset, length, admin)
            .map(Response::new)
    })
    .await
}
#[tauri::command]
fn publish_corpus(state: State<AppState>, token: String, corpus_id: String) -> Result<u32> {
    state.require_admin(&token)?;
    state.store.publish(&corpus_id)
}
#[tauri::command]
fn evidence(state: State<AppState>, token: Option<String>, id: String) -> Result<Evidence> {
    state
        .store
        .evidence(&id, admin_if_present(&state, token.as_deref())?)
}

#[tauri::command]
async fn review_corpus(
    state: State<'_, AppState>,
    token: String,
    corpus_id: String,
) -> Result<store::Review> {
    state.require_admin(&token)?;
    let store = state.store.clone();
    worker(move || store.review(&corpus_id)).await
}
#[tauri::command]
async fn search_library(
    state: State<'_, AppState>,
    query: String,
    corpus_ids: Vec<String>,
    mode: String,
) -> Result<knowledge::SearchResult> {
    let store = state.store.clone();
    worker(move || knowledge::search(&store, &query, &corpus_ids, &mode, 20)).await
}
#[tauri::command]
async fn graph_library(
    state: State<'_, AppState>,
    corpus_ids: Vec<String>,
    evidence_ids: Vec<String>,
    review_token: Option<String>,
) -> Result<Vec<knowledge::Fact>> {
    let reviewer = admin_if_present(&state, review_token.as_deref())?;
    let store = state.store.clone();
    worker(move || knowledge::graph(&store, &corpus_ids, reviewer, &evidence_ids)).await
}
#[tauri::command]
async fn published_motifs(
    state: State<'_, AppState>,
    corpus_ids: Vec<String>,
) -> Result<Vec<motifs::Row>> {
    let store = state.store.clone();
    worker(move || motifs::rows(&store, &corpus_ids)).await
}
#[tauri::command]
fn save_plate_regions(
    state: State<AppState>,
    token: String,
    run_id: String,
    assertion_id: String,
    regions: motifs::Regions,
) -> Result<()> {
    state.require_admin(&token)?;
    motifs::save_regions(&state.store, &run_id, &assertion_id, regions)
}
#[tauri::command]
async fn local_pipeline_graph(
    state: State<'_, AppState>,
    token: String,
    version: Option<String>,
) -> Result<serde_json::Value> {
    state.require_admin(&token)?;
    let store = state.store.clone();
    worker(move || pipeline::latest_version(&store, version.as_deref())).await
}
#[tauri::command]
async fn review_pipeline_item(
    state: State<'_, AppState>,
    token: String,
    run_id: String,
    target_kind: String,
    target_id: String,
    decision: String,
    reviewer: String,
    note: String,
) -> Result<String> {
    state.require_admin(&token)?;
    let store = state.store.clone();
    worker(move || {
        pipeline::review(
            &store,
            &run_id,
            &target_kind,
            &target_id,
            &decision,
            &reviewer,
            &note,
        )
    })
    .await
}
#[tauri::command]
async fn local_pipeline_image(
    state: State<'_, AppState>,
    token: String,
    page: u32,
    run_id: Option<String>,
) -> Result<Response> {
    state.require_admin(&token)?;
    let store = state.store.clone();
    worker(move || store.pipeline_image_for_run(page, run_id.as_deref()).map(Response::new)).await
}
#[tauri::command]
async fn analyze_library(
    state: State<'_, AppState>,
    corpus_ids: Vec<String>,
    keyword: String,
) -> Result<knowledge::Analytics> {
    let store = state.store.clone();
    worker(move || knowledge::analysis(&store, &corpus_ids, &keyword)).await
}
#[tauri::command]
async fn backend_status(state: State<'_, AppState>) -> Result<opencode::Status> {
    let store = state.store.clone();
    worker(move || opencode::status(&store)).await
}
#[tauri::command]
async fn backend_models(state: State<'_, AppState>, token: String) -> Result<Vec<String>> {
    state.require_admin(&token)?;
    let store = state.store.clone();
    worker(move || opencode::models(&store)).await
}
#[tauri::command]
fn configure_backend(
    state: State<AppState>,
    token: String,
    path: String,
    model: String,
    allow_remote: bool,
) -> Result<()> {
    state.require_admin(&token)?;
    opencode::configure(&state.store, &path, &model, allow_remote)
}
#[tauri::command]
async fn ask_library(
    state: State<'_, AppState>,
    question: String,
    corpus_ids: Vec<String>,
    motif_id: Option<String>,
) -> Result<opencode::Answer> {
    let store = state.store.clone();
    worker(move || opencode::ask(&store, &question, &corpus_ids, motif_id.as_deref())).await
}

fn save_as(
    app: &tauri::AppHandle,
    name: &str,
    write: impl FnOnce(&mut std::fs::File) -> std::io::Result<()>,
) -> Result<bool> {
    use tauri_plugin_dialog::{DialogExt, FilePath};
    let Some(FilePath::Path(path)) = app.dialog().file().set_file_name(name).blocking_save_file()
    else {
        return Ok(false);
    };
    let folder = path.parent().ok_or("导出目录无效。")?;
    let mut file = tempfile::NamedTempFile::new_in(folder).map_err(|error| error.to_string())?;
    write(file.as_file_mut()).map_err(|error| error.to_string())?;
    file.persist(&path).map_err(|error| error.to_string())?;
    Ok(true)
}

#[tauri::command]
async fn save_report(app: tauri::AppHandle, text: String) -> Result<bool> {
    if text.len() > 512 * 1024 {
        return Err("报告超过导出上限。".into());
    }
    worker(move || {
        save_as(&app, "WikiBridge.md", |file| {
            file.write_all(text.as_bytes())
        })
    })
    .await
}

#[tauri::command]
async fn save_source(
    app: tauri::AppHandle,
    state: State<'_, AppState>,
    token: Option<String>,
    source_id: String,
) -> Result<bool> {
    let admin = admin_if_present(&state, token.as_deref())?;
    let store = state.store.clone();
    worker(move || {
        let (name, mut original) = store.open_source(&source_id, admin)?;
        save_as(&app, &name, |file| {
            std::io::copy(&mut original, file).map(|_| ())
        })
    })
    .await
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let path = app.path().app_data_dir()?;
            app.manage(AppState::new(path).map_err(std::io::Error::other)?);
            let show = MenuItem::with_id(app, "show", "显示 WikiBridge", true, None::<&str>)?;
            let admin = MenuItem::with_id(app, "admin", "打开管理员工作区", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "退出 WikiBridge", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &admin, &quit])?;
            if let Some(icon) = app.default_window_icon().cloned() {
                TrayIconBuilder::new()
                    .icon(icon)
                    .icon_as_template(true)
                    .tooltip("WikiBridge")
                    .menu(&menu)
                    .show_menu_on_left_click(false)
                    .on_menu_event(|app, event| match event.id().as_ref() {
                        "show" => show_main_window(app),
                        "admin" => {
                            show_main_window(app);
                            let _ = app.emit("wikibridge://open-admin", ());
                        }
                        "quit" => app.exit(0),
                        _ => {}
                    })
                    .on_tray_icon_event(|tray, event| {
                        if let TrayIconEvent::Click {
                            button: MouseButton::Left,
                            ..
                        } = event
                        {
                            show_main_window(tray.app_handle());
                        }
                    })
                    .build(app)?;
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![
            admin_exists,
            admin_login,
            admin_logout,
            list_corpora,
            create_corpus,
            list_sources,
            begin_import,
            retry_import,
            start_ocr,
            submit_units,
            finish_import,
            fail_import,
            read_source_range,
            publish_corpus,
            evidence,
            review_corpus,
            search_library,
            graph_library,
            local_pipeline_graph,
            published_motifs,
            save_plate_regions,
            review_pipeline_item,
            local_pipeline_image,
            analyze_library,
            backend_status,
            backend_models,
            configure_backend,
            ask_library,
            save_report,
            save_source
        ])
        .run(tauri::generate_context!())
        .expect("failed to run WikiBridge");
}

fn show_main_window<R: tauri::Runtime>(app: &tauri::AppHandle<R>) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    }
}

#[cfg(test)]
mod tests;
