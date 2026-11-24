use crate::ingest::{self, Unit};
use argon2::{
    Argon2,
    password_hash::{PasswordHash, PasswordHasher, PasswordVerifier, SaltString},
};
use rusqlite::{Connection, OptionalExtension, Transaction, params};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File},
    io::{Read, Seek, SeekFrom, Write},
    path::{Path, PathBuf},
    sync::Mutex,
    time::Duration,
};
use uuid::Uuid;

pub type Result<T> = std::result::Result<T, String>;
pub const MAX_FILE_BYTES: u64 = 512 * 1024 * 1024;
const MAX_RANGE: usize = 8 * 1024 * 1024;

pub fn sql<T>(result: rusqlite::Result<T>) -> Result<T> {
    result.map_err(|error| error.to_string())
}

pub struct State {
    pub store: Store,
    admin_session: Mutex<Option<String>>,
}

#[derive(Clone)]
pub struct Store {
    root: PathBuf,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Corpus {
    pub id: String,
    pub name: String,
    pub description: String,
    pub revision: u32,
    pub document_count: u32,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Source {
    pub id: String,
    pub name: String,
    pub extension: String,
    pub bytes: u64,
    pub sha256: String,
    pub status: String,
    pub error: Option<String>,
    pub unit_count: u32,
    pub created_at: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Import {
    pub source: Source,
    pub needs_extraction: bool,
    pub duplicate: bool,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Evidence {
    pub id: String,
    pub source_id: String,
    pub corpus_id: String,
    pub corpus_name: String,
    pub source_name: String,
    pub extension: String,
    pub bytes: u64,
    pub sha256: String,
    pub kind: String,
    pub ordinal: u32,
    pub locator: String,
    pub text: String,
    pub method: String,
    pub confidence: Option<f32>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Review {
    pub evidence: Vec<Evidence>,
    pub fact_count: u32,
    pub ocr_count: u32,
    pub low_confidence_count: u32,
}

pub const EVIDENCE_SELECT: &str = "
SELECT c.id,s.id,s.corpus_id,k.name,s.name,s.extension,s.bytes,s.hash,
       u.kind,u.ordinal,u.locator,c.text,u.method,u.confidence
FROM chunks c JOIN units u ON c.unit_id=u.id JOIN sources s ON u.source_id=s.id
JOIN corpora k ON s.corpus_id=k.id";

pub fn map_evidence(row: &rusqlite::Row<'_>) -> rusqlite::Result<Evidence> {
    Ok(Evidence {
        id: row.get(0)?,
        source_id: row.get(1)?,
        corpus_id: row.get(2)?,
        corpus_name: row.get(3)?,
        source_name: row.get(4)?,
        extension: row.get(5)?,
        bytes: row.get(6)?,
        sha256: row.get(7)?,
        kind: row.get(8)?,
        ordinal: row.get(9)?,
        locator: row.get(10)?,
        text: row.get(11)?,
        method: row.get(12)?,
        confidence: row.get(13)?,
    })
}

impl State {
    pub fn new(root: PathBuf) -> Result<Self> {
        Ok(Self {
            store: Store::new(root)?,
            admin_session: Mutex::new(None),
        })
    }

    pub fn login(&self, password: &str) -> Result<String> {
        if password.len() > 256 {
            return Err("口令过长。".into());
        }
        let mut session = self
            .admin_session
            .lock()
            .map_err(|error| error.to_string())?;
        let conn = self.store.connect()?;
        if let Some(hash) = setting(&conn, "admin_hash")? {
            let hash = PasswordHash::new(&hash).map_err(|error| error.to_string())?;
            Argon2::default()
                .verify_password(password.as_bytes(), &hash)
                .map_err(|_| "管理员口令不正确。".to_owned())?;
        } else {
            if password.chars().count() < 8 {
                return Err("请使用至少 8 个字符设置管理员口令。".into());
            }
            let salt = SaltString::encode_b64(&rand::random::<[u8; 16]>())
                .map_err(|error| error.to_string())?;
            let hash = Argon2::default()
                .hash_password(password.as_bytes(), &salt)
                .map_err(|error| error.to_string())?;
            set_setting(&conn, "admin_hash", &hash.to_string())?;
        }
        let token = Uuid::new_v4().to_string();
        *session = Some(token.clone());
        Ok(token)
    }

    pub fn logout(&self, token: &str) -> Result<()> {
        let mut session = self
            .admin_session
            .lock()
            .map_err(|error| error.to_string())?;
        if session.as_deref() == Some(token) {
            *session = None;
        }
        Ok(())
    }

    pub fn require_admin(&self, token: &str) -> Result<()> {
        let session = self
            .admin_session
            .lock()
            .map_err(|error| error.to_string())?;
        if session.as_deref() != Some(token) {
            return Err("请先解锁管理员工作区。".into());
        }
        Ok(())
    }
}

pub fn setting(conn: &Connection, key: &str) -> Result<Option<String>> {
    sql(conn
        .query_row("SELECT value FROM settings WHERE key=?1", [key], |row| {
            row.get(0)
        })
        .optional())
}

pub fn set_setting(conn: &Connection, key: &str, value: &str) -> Result<()> {
    sql(conn.execute(
        "INSERT INTO settings VALUES (?1, ?2) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        params![key, value],
    ))?;
    Ok(())
}

fn map_source(row: &rusqlite::Row<'_>) -> rusqlite::Result<Source> {
    Ok(Source {
        id: row.get(0)?,
        name: row.get(1)?,
        extension: row.get(2)?,
        bytes: row.get(3)?,
        sha256: row.get(4)?,
        status: row.get(5)?,
        error: row.get(6)?,
        unit_count: row.get(7)?,
        created_at: row.get(8)?,
    })
}

const SOURCE_SELECT: &str = "
SELECT s.id,s.name,s.extension,s.bytes,s.hash,s.status,s.error,
(SELECT COUNT(*) FROM units u WHERE u.source_id=s.id),s.created_at FROM sources s";

impl Store {
    pub fn new(root: PathBuf) -> Result<Self> {
        fs::create_dir_all(root.join("sources")).map_err(|error| error.to_string())?;
        let store = Self { root };
        let conn = store.connect()?;
        sql(conn.execute_batch("
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS corpora(
                id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                published_at TEXT
            );
            CREATE TABLE IF NOT EXISTS sources(
                id TEXT PRIMARY KEY, corpus_id TEXT NOT NULL REFERENCES corpora(id), name TEXT NOT NULL,
                extension TEXT NOT NULL, bytes INTEGER NOT NULL, hash TEXT NOT NULL,
                status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(corpus_id,hash)
            );
            CREATE TABLE IF NOT EXISTS units(
                id INTEGER PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                kind TEXT NOT NULL, ordinal INTEGER NOT NULL, locator TEXT NOT NULL, method TEXT NOT NULL,
                confidence REAL, UNIQUE(source_id,ordinal)
            );
            CREATE TABLE IF NOT EXISTS chunks(
                seq INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, unit_id INTEGER NOT NULL REFERENCES units(id) ON DELETE CASCADE,
                text TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(tokens, detail=full);
            CREATE TRIGGER IF NOT EXISTS delete_fts AFTER DELETE ON chunks BEGIN
                DELETE FROM chunks_fts WHERE rowid=old.seq;
            END;
            CREATE TABLE IF NOT EXISTS facts(
                chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE, subject TEXT NOT NULL,
                relation TEXT NOT NULL, object TEXT NOT NULL, PRIMARY KEY(chunk_id,subject,relation,object)
            );
            CREATE INDEX IF NOT EXISTS sources_corpus_status ON sources(corpus_id,status);
            CREATE TABLE IF NOT EXISTS kg_runs(
                id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                state TEXT NOT NULL, graph_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS kg_entities(
                run_id TEXT NOT NULL REFERENCES kg_runs(id) ON DELETE CASCADE,
                id TEXT NOT NULL, label TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY(run_id,id)
            );
            CREATE TABLE IF NOT EXISTS kg_mentions(
                run_id TEXT NOT NULL, id TEXT NOT NULL, entity_id TEXT NOT NULL, page INTEGER NOT NULL,
                start INTEGER NOT NULL, end INTEGER NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY(run_id,id), FOREIGN KEY(run_id,entity_id) REFERENCES kg_entities(run_id,id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS kg_edges(
                run_id TEXT NOT NULL, id TEXT NOT NULL, subject_id TEXT NOT NULL,
                predicate TEXT NOT NULL, object_id TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY(run_id,id),
                FOREIGN KEY(run_id,subject_id) REFERENCES kg_entities(run_id,id) ON DELETE CASCADE,
                FOREIGN KEY(run_id,object_id) REFERENCES kg_entities(run_id,id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS kg_records(
                run_id TEXT NOT NULL REFERENCES kg_runs(id) ON DELETE CASCADE,
                id TEXT NOT NULL, page INTEGER NOT NULL, item INTEGER NOT NULL, label TEXT NOT NULL,
                data TEXT NOT NULL, PRIMARY KEY(run_id,id)
            );
            CREATE TABLE IF NOT EXISTS kg_assertions(
                run_id TEXT NOT NULL REFERENCES kg_runs(id) ON DELETE CASCADE,
                id TEXT NOT NULL, subject_id TEXT, predicate TEXT NOT NULL,
                object_kind TEXT NOT NULL, object_json TEXT NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY(run_id,id),
                FOREIGN KEY(run_id,subject_id) REFERENCES kg_entities(run_id,id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS kg_events(
                run_id TEXT NOT NULL REFERENCES kg_runs(id) ON DELETE CASCADE,
                id TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(run_id,id)
            );
            CREATE TABLE IF NOT EXISTS kg_source_mentions(
                run_id TEXT NOT NULL REFERENCES kg_runs(id) ON DELETE CASCADE,
                id TEXT NOT NULL, entity_id TEXT, data TEXT NOT NULL, PRIMARY KEY(run_id,id),
                FOREIGN KEY(run_id,entity_id) REFERENCES kg_entities(run_id,id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS kg_reviews(
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES kg_runs(id),
                target_kind TEXT NOT NULL, target_id TEXT NOT NULL, decision TEXT NOT NULL,
                reviewer TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS kg_reviews_run ON kg_reviews(run_id,target_kind,target_id);
            CREATE INDEX IF NOT EXISTS kg_mentions_entity ON kg_mentions(run_id,entity_id);
            CREATE INDEX IF NOT EXISTS kg_edges_subject ON kg_edges(run_id,subject_id);
            CREATE INDEX IF NOT EXISTS kg_edges_object ON kg_edges(run_id,object_id);
        "))?;
        // A second process may be open, so interrupted imports are resumed explicitly.
        Ok(store)
    }

    pub fn connect(&self) -> Result<Connection> {
        let conn = sql(Connection::open(self.root.join("knowledge.sqlite3")))?;
        sql(conn.busy_timeout(Duration::from_secs(10)))?;
        sql(conn.execute_batch("PRAGMA foreign_keys=ON;"))?;
        Ok(conn)
    }

    pub fn pipeline_image(&self, page: u32) -> Result<Vec<u8>> {
        if !(1..=100).contains(&page) {
            return Err("页码须为 1–100。".into());
        }
        fs::read(
            self.root
                .join("pipeline-pages")
                .join(format!("v1-p{page:04}.png")),
        )
        .map_err(|error| error.to_string())
    }

    pub fn corpora(&self, admin: bool) -> Result<Vec<Corpus>> {
        let conn = self.connect()?;
        let mut statement = sql(conn.prepare("
            SELECT c.id,c.name,c.description,c.revision,
              (SELECT COUNT(*) FROM sources s WHERE s.corpus_id=c.id AND (?1 OR s.status='published'))
            FROM corpora c WHERE (?1 OR c.revision>0) ORDER BY c.name,c.id
        "))?;
        let rows = sql(statement.query_map([admin], |row| {
            Ok(Corpus {
                id: row.get(0)?,
                name: row.get(1)?,
                description: row.get(2)?,
                revision: row.get(3)?,
                document_count: row.get(4)?,
            })
        }))?;
        sql(rows.collect())
    }

    pub fn create_corpus(&self, name: &str, description: &str) -> Result<String> {
        let name = name.trim();
        if name.is_empty() || name.chars().count() > 80 || description.chars().count() > 500 {
            return Err("语料库名称须为 1–80 字，说明最多 500 字。".into());
        }
        let id = Uuid::new_v4().to_string();
        sql(self.connect()?.execute(
            "INSERT INTO corpora(id,name,description) VALUES (?1,?2,?3)",
            params![id, name, description.trim()],
        ))?;
        Ok(id)
    }

    pub fn sources(&self, corpus: &str, admin: bool) -> Result<Vec<Source>> {
        let conn = self.connect()?;
        let mut statement = sql(conn.prepare(&format!("{SOURCE_SELECT} WHERE s.corpus_id=?1 AND (?2 OR s.status='published') ORDER BY s.created_at DESC,s.rowid DESC")))?;
        let rows = sql(statement.query_map(params![corpus, admin], map_source))?;
        sql(rows.collect())
    }

    fn source(conn: &Connection, id: &str) -> Result<Source> {
        sql(conn.query_row(&format!("{SOURCE_SELECT} WHERE s.id=?1"), [id], map_source))
    }

    fn stored_path(&self, source: &Source) -> PathBuf {
        self.root
            .join("sources")
            .join(format!("{}.{}", source.id, source.extension))
    }

    pub fn begin_import(&self, corpus: &str, path: &Path) -> Result<Import> {
        let name = path
            .file_name()
            .and_then(|name| name.to_str())
            .ok_or("文件名无法读取。")?;
        let extension = path
            .extension()
            .and_then(|extension| extension.to_str())
            .unwrap_or("")
            .to_ascii_lowercase();
        if !ingest::supported(&extension) {
            return Err(format!("此版本暂不能处理 .{extension} 文件。"));
        }

        let mut file = File::open(path).map_err(|error| error.to_string())?;
        let info = file.metadata().map_err(|error| error.to_string())?;
        if !info.is_file() || info.len() == 0 || info.len() > MAX_FILE_BYTES {
            return Err("请选择非空文件，单个文件上限为 512 MiB。".into());
        }
        let mut pending = tempfile::NamedTempFile::new_in(self.root.join("sources"))
            .map_err(|error| error.to_string())?;
        let mut hash = Sha256::new();
        let mut bytes = 0;
        let mut buffer = vec![0; 256 * 1024];
        loop {
            let count = file.read(&mut buffer).map_err(|error| error.to_string())?;
            if count == 0 {
                break;
            }
            bytes += count as u64;
            if bytes > MAX_FILE_BYTES {
                return Err("文件超过 512 MiB。".into());
            }
            pending
                .write_all(&buffer[..count])
                .map_err(|error| error.to_string())?;
            hash.update(&buffer[..count]);
        }
        if bytes == 0 {
            return Err("文件为空。".into());
        }
        pending
            .as_file()
            .sync_all()
            .map_err(|error| error.to_string())?;
        let hash = format!("{:x}", hash.finalize());
        let id = Uuid::new_v4().to_string();
        let mut conn = self.connect()?;
        let transaction =
            sql(conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate))?;
        let existing = sql(transaction
            .query_row(
                "SELECT id FROM sources WHERE corpus_id=?1 AND hash=?2",
                params![corpus, hash],
                |row| row.get::<_, String>(0),
            )
            .optional())?;
        if let Some(id) = existing {
            return Ok(Import {
                source: Self::source(&transaction, &id)?,
                needs_extraction: false,
                duplicate: true,
            });
        }
        sql(transaction.execute("INSERT INTO sources(id,corpus_id,name,extension,bytes,hash,status) VALUES (?1,?2,?3,?4,?5,?6,'processing')", params![id, corpus, name, extension, bytes, hash]))?;
        let source = Self::source(&transaction, &id)?;
        let destination = self.stored_path(&source);
        pending
            .persist_noclobber(&destination)
            .map_err(|error| error.to_string())?;
        if let Err(error) = transaction.commit() {
            let _ = fs::remove_file(destination);
            return Err(error.to_string());
        }
        self.process_source(source)
    }

    pub fn retry(&self, id: &str) -> Result<Import> {
        let mut conn = self.connect()?;
        let transaction =
            sql(conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate))?;
        let changed = sql(transaction.execute("UPDATE sources SET status='processing',error=NULL WHERE id=?1 AND status IN ('failed','processing')", [id]))?;
        if changed != 1 {
            return Err("只有处理中或失败的文件可以重新处理。".into());
        }
        sql(transaction.execute("DELETE FROM units WHERE source_id=?1", [id]))?;
        let source = Self::source(&transaction, id)?;
        sql(transaction.commit())?;
        if ingest::needs_browser(&source.extension) {
            return Ok(Import {
                source,
                needs_extraction: true,
                duplicate: false,
            });
        }
        self.process_source(source)
    }

    pub fn start_ocr(&self, id: &str) -> Result<Import> {
        let mut conn = self.connect()?;
        let transaction =
            sql(conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate))?;
        let changed = sql(transaction.execute(
            "UPDATE sources SET status='processing',error=NULL WHERE id=?1 AND status IN ('queued','draft','failed')",
            [id],
        ))?;
        if changed != 1 {
            return Err("当前文件不在可启动 OCR 的状态。".into());
        }
        let source = Self::source(&transaction, id)?;
        sql(transaction.commit())?;
        if ingest::needs_browser(&source.extension) {
            return Ok(Import {
                source,
                needs_extraction: true,
                duplicate: false,
            });
        }
        self.process_source(source)
    }

    fn process_source(&self, source: Source) -> Result<Import> {
        if ingest::needs_browser(&source.extension) {
            sql(self.connect()?.execute(
                "UPDATE sources SET status='queued',error=NULL WHERE id=?1 AND status='processing'",
                [&source.id],
            ))?;
            return Ok(Import {
                source: Self::source(&self.connect()?, &source.id)?,
                needs_extraction: true,
                duplicate: false,
            });
        }
        let outcome = ingest::extract(&self.stored_path(&source), &source.extension)
            .and_then(|units| self.add_units(&source.id, &units))
            .and_then(|()| self.finish(&source.id));
        if let Err(error) = outcome {
            self.fail(&source.id, &error)?;
        }
        Ok(Import {
            source: Self::source(&self.connect()?, &source.id)?,
            needs_extraction: false,
            duplicate: false,
        })
    }

    pub fn read_range(&self, id: &str, offset: u64, length: usize, admin: bool) -> Result<Vec<u8>> {
        let source = Self::source(&self.connect()?, id)?;
        if (!admin && source.status != "published")
            || length == 0
            || length > MAX_RANGE
            || offset
                .checked_add(length as u64)
                .is_none_or(|end| end > source.bytes)
        {
            return Err("无法读取请求的文件区间。".into());
        }
        let mut file = File::open(self.stored_path(&source)).map_err(|error| error.to_string())?;
        file.seek(SeekFrom::Start(offset))
            .map_err(|error| error.to_string())?;
        let mut bytes = vec![0; length];
        file.read_exact(&mut bytes)
            .map_err(|error| error.to_string())?;
        Ok(bytes)
    }

    pub fn open_source(&self, id: &str, admin: bool) -> Result<(String, File)> {
        let source = Self::source(&self.connect()?, id)?;
        if !admin && source.status != "published" {
            return Err("该原始文件尚未发布。".into());
        }
        let file = File::open(self.stored_path(&source)).map_err(|error| error.to_string())?;
        Ok((source.name, file))
    }

    pub fn add_units(&self, source_id: &str, units: &[Unit]) -> Result<()> {
        let mut connection = self.connect()?;
        let transaction =
            sql(connection.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate))?;
        let source = Self::source(&transaction, source_id)?;
        if source.status != "processing" {
            return Err("文件当前不可写入处理结果。".into());
        }
        for unit in units {
            Self::add_unit(&transaction, source_id, unit)?;
        }
        sql(transaction.commit())
    }

    fn add_unit(tx: &Transaction<'_>, source_id: &str, unit: &Unit) -> Result<()> {
        if unit.text.is_empty() {
            return Ok(());
        }
        if unit.ordinal == 0
            || unit.text.len() > ingest::MAX_TEXT_BYTES
            || unit.locator.len() > 512
            || !matches!(unit.method.as_str(), "native" | "ocr")
            || unit
                .confidence
                .is_some_and(|confidence| !(0.0..=1.0).contains(&confidence))
        {
            return Err("内容单元无效。".into());
        }
        let changed = sql(tx.execute("INSERT OR IGNORE INTO units(source_id,kind,ordinal,locator,method,confidence) VALUES (?1,?2,?3,?4,?5,?6)",
            params![source_id,unit.kind,unit.ordinal,unit.locator,unit.method,unit.confidence]))?;
        if changed == 0 {
            return Ok(());
        }
        let unit_id = tx.last_insert_rowid();
        for (index, chunk) in crate::knowledge::chunks(&unit.text).into_iter().enumerate() {
            let id = format!("{source_id}:{}:{}", unit.ordinal, index + 1);
            sql(tx.execute(
                "INSERT INTO chunks(id,unit_id,text) VALUES (?1,?2,?3)",
                params![id, unit_id, chunk],
            ))?;
            let sequence = tx.last_insert_rowid();
            let tokens = crate::knowledge::tokens(chunk).join(" ");
            sql(tx.execute(
                "INSERT INTO chunks_fts(rowid,tokens) VALUES (?1,?2)",
                params![sequence, tokens],
            ))?;
            for (subject, relation, object) in crate::knowledge::extract(chunk) {
                sql(tx.execute(
                    "INSERT OR IGNORE INTO facts VALUES (?1,?2,?3,?4)",
                    params![id, subject, relation, object],
                ))?;
            }
        }
        Ok(())
    }

    pub fn finish(&self, id: &str) -> Result<()> {
        let changed = sql(self.connect()?.execute("UPDATE sources SET status='draft',error=NULL WHERE id=?1 AND status='processing' AND EXISTS (SELECT 1 FROM units WHERE source_id=?1)", [id]))?;
        if changed == 0 {
            return Err("该文件没有可发布的文本，或处理状态已改变。".into());
        }
        Ok(())
    }

    pub fn fail(&self, id: &str, error: &str) -> Result<()> {
        let error: String = error.chars().take(700).collect();
        sql(self.connect()?.execute(
            "UPDATE sources SET status='failed',error=?2 WHERE id=?1 AND status='processing'",
            params![id, error],
        ))?;
        Ok(())
    }

    pub fn publish(&self, corpus: &str) -> Result<u32> {
        let mut conn = self.connect()?;
        let tx = sql(conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate))?;
        let mut draft = sql(tx.prepare(
            "SELECT id,name FROM sources WHERE corpus_id=?1 AND status='draft' ORDER BY rowid",
        ))?;
        let rows = sql(draft.query_map([corpus], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        }))?;
        let rows = sql(rows.collect::<rusqlite::Result<Vec<_>>>())?;
        drop(draft);
        if rows.is_empty() {
            return Err("没有等待发布的文件。".into());
        }
        // A failed or unfinished newer document does not supersede a published version.
        for (id, name) in rows {
            sql(tx.execute("UPDATE sources SET status='archived' WHERE corpus_id=?1 AND name=?2 AND status='published'", params![corpus, name]))?;
            sql(tx.execute("UPDATE sources SET status='published' WHERE id=?1", [id]))?;
        }
        let revision: u32 = sql(tx.query_row("UPDATE corpora SET revision=revision+1,published_at=CURRENT_TIMESTAMP WHERE id=?1 RETURNING revision", [corpus], |row| row.get(0)))?;
        sql(tx.commit())?;
        Ok(revision)
    }

    pub fn evidence(&self, id: &str, admin: bool) -> Result<Evidence> {
        let conn = self.connect()?;
        sql(conn.query_row(&format!("{EVIDENCE_SELECT} WHERE c.id=?1 AND (s.status='published' OR (?2 AND s.status<>'processing'))"),
            params![id, admin], map_evidence).optional())?.ok_or_else(|| "证据未发布或已随文件版本归档。".into())
    }

    pub fn review(&self, corpus: &str) -> Result<Review> {
        let conn = self.connect()?;
        let mut statement = sql(conn.prepare(&format!(
            "{EVIDENCE_SELECT} WHERE s.status='draft' AND s.corpus_id=?1
             AND c.seq=(SELECT MIN(sample.seq) FROM chunks sample JOIN units unit ON unit.id=sample.unit_id WHERE unit.source_id=s.id)
             ORDER BY s.rowid LIMIT 30"
        )))?;
        let rows = sql(statement.query_map([corpus], map_evidence))?;
        let evidence = sql(rows.collect())?;
        let fact_count = sql(conn.query_row(
            "SELECT COUNT(*) FROM facts f JOIN chunks c ON c.id=f.chunk_id JOIN units u ON u.id=c.unit_id
             JOIN sources s ON s.id=u.source_id WHERE s.status='draft' AND s.corpus_id=?1",
            [corpus], |row| row.get(0),
        ))?;
        let (ocr_count, low_confidence_count) = sql(conn.query_row(
            "SELECT COUNT(*),COUNT(CASE WHEN u.confidence<0.75 THEN 1 END)
             FROM units u JOIN sources s ON s.id=u.source_id
             WHERE s.status='draft' AND s.corpus_id=?1 AND u.method='ocr'",
            [corpus],
            |row| Ok((row.get(0)?, row.get(1)?)),
        ))?;
        Ok(Review {
            evidence,
            fact_count,
            ocr_count,
            low_confidence_count,
        })
    }
}
