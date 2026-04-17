use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::Manager;
use uuid::Uuid;

const DB_NAME: &str = "desktop-chat.db";
const DEFAULT_SESSION_TITLE: &str = "New chat";
const ACTIVE_SESSION_KEY: &str = "active_session_id";

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct ChatSessionMetadata {
    pub target_agent: Option<String>,
    pub selected_model: Option<String>,
    pub selected_provider: Option<String>,
    pub base_url: Option<String>,
    pub teaching_mode: Option<bool>,
    pub autonomy_mode: Option<String>,
    pub project_context_id: Option<String>,
    pub channel_style_profile: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct ChatSessionMetadataInput {
    pub target_agent: Option<String>,
    pub selected_model: Option<String>,
    pub selected_provider: Option<String>,
    pub base_url: Option<String>,
    pub teaching_mode: Option<bool>,
    pub autonomy_mode: Option<String>,
    pub project_context_id: Option<String>,
    pub channel_style_profile: Option<Value>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ChatSessionSummary {
    pub session_id: String,
    pub title: String,
    pub created_at: i64,
    pub updated_at: i64,
    pub last_message_at: i64,
    pub message_count: i64,
    pub preview: String,
    pub draft: String,
    pub metadata: ChatSessionMetadata,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PersistedChatMessage {
    pub message_id: String,
    pub role: String,
    pub content: String,
    pub timestamp: String,
    pub confidence: Option<f64>,
    #[serde(rename = "tool_calls")]
    pub tool_calls: Vec<Value>,
    pub metadata: Value,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ChatBootstrap {
    pub active_session_id: String,
    pub sessions: Vec<ChatSessionSummary>,
    pub messages: Vec<PersistedChatMessage>,
    pub draft: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ChatSessionPayload {
    pub active_session_id: String,
    pub messages: Vec<PersistedChatMessage>,
    pub draft: String,
    pub metadata: ChatSessionMetadata,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PersistedChatMessageInput {
    pub role: String,
    pub content: String,
    pub timestamp: Option<String>,
    pub confidence: Option<f64>,
    #[serde(rename = "tool_calls")]
    pub tool_calls: Option<Vec<Value>>,
    pub metadata: Option<Value>,
}

fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis() as i64)
        .unwrap_or(0)
}

fn database_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let mut dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("failed to resolve app data dir: {e}"))?;
    fs::create_dir_all(&dir).map_err(|e| format!("failed to create app data dir: {e}"))?;
    dir.push(DB_NAME);
    Ok(dir)
}

fn open_db(app: &tauri::AppHandle) -> Result<Connection, String> {
    let path = database_path(app)?;
    let conn = Connection::open(path).map_err(|e| format!("failed to open chat database: {e}"))?;
    conn.execute_batch(
        "
        PRAGMA journal_mode = WAL;
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS chat_sessions (
            session_id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT 'New chat',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            last_message_at INTEGER NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            message_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            confidence REAL,
            tool_calls_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL,
            FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS chat_drafts (
            session_id TEXT PRIMARY KEY,
            content TEXT NOT NULL DEFAULT '',
            updated_at INTEGER NOT NULL,
            FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_chat_sessions_last_message_at ON chat_sessions(last_message_at DESC);
        CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created_at ON chat_messages(session_id, created_at ASC);
        ",
    )
    .map_err(|e| format!("failed to initialize chat database: {e}"))?;

    if !has_column(&conn, "chat_sessions", "metadata_json")? {
        conn.execute(
            "ALTER TABLE chat_sessions ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'",
            [],
        )
        .map_err(|e| format!("failed to migrate chat session metadata: {e}"))?;
    }
    if !has_column(&conn, "chat_messages", "metadata_json")? {
        conn.execute(
            "ALTER TABLE chat_messages ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'",
            [],
        )
        .map_err(|e| format!("failed to migrate chat message metadata: {e}"))?;
    }
    Ok(conn)
}

fn has_column(conn: &Connection, table: &str, column: &str) -> Result<bool, String> {
    let mut stmt = conn
        .prepare(&format!("PRAGMA table_info({table})"))
        .map_err(|e| format!("failed to inspect table schema: {e}"))?;
    let rows = stmt
        .query_map([], |row| row.get::<_, String>(1))
        .map_err(|e| format!("failed to read table schema: {e}"))?;

    for row in rows {
        if row.map_err(|e| format!("failed to parse table schema: {e}"))? == column {
            return Ok(true);
        }
    }
    Ok(false)
}

fn metadata_to_json(metadata: Option<ChatSessionMetadataInput>) -> Result<String, String> {
    serde_json::to_string(&metadata.unwrap_or_default())
        .map_err(|e| format!("failed to serialize chat metadata: {e}"))
}

fn parse_metadata(raw: &str) -> ChatSessionMetadata {
    serde_json::from_str::<ChatSessionMetadata>(raw).unwrap_or_default()
}

fn create_session_record(
    conn: &Connection,
    title: Option<String>,
    metadata: Option<ChatSessionMetadataInput>,
) -> Result<String, String> {
    let now = now_ms();
    let session_id = Uuid::new_v4().to_string();
    let session_title = title
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| DEFAULT_SESSION_TITLE.to_string());
    let metadata_json = metadata_to_json(metadata)?;

    conn.execute(
        "INSERT INTO chat_sessions (session_id, title, created_at, updated_at, last_message_at, metadata_json)
         VALUES (?1, ?2, ?3, ?3, ?3, ?4)",
        params![session_id, session_title, now, metadata_json],
    )
    .map_err(|e| format!("failed to create chat session: {e}"))?;

    conn.execute(
        "INSERT INTO app_meta (key, value) VALUES (?1, ?2)
         ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        params![ACTIVE_SESSION_KEY, session_id],
    )
    .map_err(|e| format!("failed to set active session: {e}"))?;

    Ok(session_id)
}

fn session_exists(conn: &Connection, session_id: &str) -> Result<bool, String> {
    conn.query_row(
        "SELECT 1 FROM chat_sessions WHERE session_id = ?1 LIMIT 1",
        params![session_id],
        |_| Ok(()),
    )
    .optional()
    .map(|row| row.is_some())
    .map_err(|e| format!("failed to check chat session: {e}"))
}

fn ensure_active_session(conn: &Connection) -> Result<String, String> {
    let active = conn
        .query_row(
            "SELECT value FROM app_meta WHERE key = ?1",
            params![ACTIVE_SESSION_KEY],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|e| format!("failed to read active session: {e}"))?;

    if let Some(session_id) = active {
        if session_exists(conn, &session_id)? {
            return Ok(session_id);
        }
    }

    let existing = conn
        .query_row(
            "SELECT session_id FROM chat_sessions ORDER BY last_message_at DESC, created_at DESC LIMIT 1",
            [],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|e| format!("failed to load chat sessions: {e}"))?;

    let session_id = if let Some(session_id) = existing {
        session_id
    } else {
        create_session_record(conn, None, None)?
    };

    conn.execute(
        "INSERT INTO app_meta (key, value) VALUES (?1, ?2)
         ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        params![ACTIVE_SESSION_KEY, session_id],
    )
    .map_err(|e| format!("failed to persist active session: {e}"))?;

    Ok(session_id)
}

fn sanitize_title(content: &str) -> String {
    let trimmed = content.trim();
    if trimmed.is_empty() {
        return DEFAULT_SESSION_TITLE.to_string();
    }
    let mut title = trimmed.replace('\n', " ");
    if title.chars().count() > 60 {
        title = title.chars().take(60).collect::<String>().trim().to_string();
        title.push_str("...");
    }
    title
}

fn update_session_title_from_message(conn: &Connection, session_id: &str, role: &str, content: &str) -> Result<(), String> {
    if role != "user" {
        return Ok(());
    }
    let current_title = conn
        .query_row(
            "SELECT title FROM chat_sessions WHERE session_id = ?1",
            params![session_id],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|e| format!("failed to read chat session title: {e}"))?;

    let Some(current_title) = current_title else {
        return Ok(());
    };

    if current_title != DEFAULT_SESSION_TITLE {
        return Ok(());
    }

    let next_title = sanitize_title(content);
    conn.execute(
        "UPDATE chat_sessions SET title = ?2, updated_at = ?3 WHERE session_id = ?1",
        params![session_id, next_title, now_ms()],
    )
    .map_err(|e| format!("failed to update chat session title: {e}"))?;

    Ok(())
}

fn load_sessions(conn: &Connection) -> Result<Vec<ChatSessionSummary>, String> {
    let mut stmt = conn
        .prepare(
            "
            SELECT
                s.session_id,
                s.title,
                s.created_at,
                s.updated_at,
                s.last_message_at,
                COALESCE((SELECT COUNT(*) FROM chat_messages m WHERE m.session_id = s.session_id), 0) AS message_count,
                COALESCE((SELECT content FROM chat_messages m WHERE m.session_id = s.session_id ORDER BY m.created_at DESC LIMIT 1), '') AS preview,
                COALESCE((SELECT content FROM chat_drafts d WHERE d.session_id = s.session_id), '') AS draft,
                COALESCE(s.metadata_json, '{}') AS metadata_json
            FROM chat_sessions s
            ORDER BY s.last_message_at DESC, s.updated_at DESC
            ",
        )
        .map_err(|e| format!("failed to prepare chat sessions query: {e}"))?;

    let rows = stmt
        .query_map([], |row| {
            Ok(ChatSessionSummary {
                session_id: row.get(0)?,
                title: row.get(1)?,
                created_at: row.get(2)?,
                updated_at: row.get(3)?,
                last_message_at: row.get(4)?,
                message_count: row.get(5)?,
                preview: row.get(6)?,
                draft: row.get(7)?,
                metadata: parse_metadata(&row.get::<_, String>(8)?),
            })
        })
        .map_err(|e| format!("failed to load chat sessions: {e}"))?;

    rows.collect::<Result<Vec<_>, _>>()
        .map_err(|e| format!("failed to read chat sessions: {e}"))
}

fn load_messages(conn: &Connection, session_id: &str) -> Result<Vec<PersistedChatMessage>, String> {
    let mut stmt = conn
        .prepare(
            "
            SELECT message_id, role, content, timestamp, confidence, tool_calls_json, metadata_json
            FROM chat_messages
            WHERE session_id = ?1
            ORDER BY created_at ASC, rowid ASC
            ",
        )
        .map_err(|e| format!("failed to prepare chat messages query: {e}"))?;

    let rows = stmt
        .query_map(params![session_id], |row| {
            let tool_calls_json: String = row.get(5)?;
            let tool_calls = serde_json::from_str::<Vec<Value>>(&tool_calls_json).unwrap_or_default();
            let metadata_json: String = row.get(6)?;
            let metadata = serde_json::from_str::<Value>(&metadata_json).unwrap_or(Value::Object(Default::default()));
            Ok(PersistedChatMessage {
                message_id: row.get(0)?,
                role: row.get(1)?,
                content: row.get(2)?,
                timestamp: row.get(3)?,
                confidence: row.get(4)?,
                tool_calls,
                metadata,
            })
        })
        .map_err(|e| format!("failed to load chat messages: {e}"))?;

    rows.collect::<Result<Vec<_>, _>>()
        .map_err(|e| format!("failed to read chat messages: {e}"))
}

fn load_draft(conn: &Connection, session_id: &str) -> Result<String, String> {
    conn.query_row(
        "SELECT content FROM chat_drafts WHERE session_id = ?1",
        params![session_id],
        |row| row.get::<_, String>(0),
    )
    .optional()
    .map(|value| value.unwrap_or_default())
    .map_err(|e| format!("failed to load chat draft: {e}"))
}

fn load_metadata(conn: &Connection, session_id: &str) -> Result<ChatSessionMetadata, String> {
    conn.query_row(
        "SELECT metadata_json FROM chat_sessions WHERE session_id = ?1",
        params![session_id],
        |row| row.get::<_, String>(0),
    )
    .optional()
    .map(|value| parse_metadata(&value.unwrap_or_else(|| "{}".to_string())))
    .map_err(|e| format!("failed to load chat metadata: {e}"))
}

fn build_bootstrap(conn: &Connection, session_id: String) -> Result<ChatBootstrap, String> {
    Ok(ChatBootstrap {
        active_session_id: session_id.clone(),
        sessions: load_sessions(conn)?,
        messages: load_messages(conn, &session_id)?,
        draft: load_draft(conn, &session_id)?,
    })
}

#[tauri::command]
pub fn get_chat_bootstrap(app: tauri::AppHandle) -> Result<ChatBootstrap, String> {
    let conn = open_db(&app)?;
    let active_session_id = ensure_active_session(&conn)?;
    build_bootstrap(&conn, active_session_id)
}

#[tauri::command]
pub fn create_chat_session(app: tauri::AppHandle, title: Option<String>) -> Result<ChatBootstrap, String> {
    let conn = open_db(&app)?;
    let session_id = create_session_record(&conn, title, None)?;
    build_bootstrap(&conn, session_id)
}

#[tauri::command]
pub fn create_chat_session_with_metadata(
    app: tauri::AppHandle,
    title: Option<String>,
    metadata: Option<ChatSessionMetadataInput>,
) -> Result<ChatBootstrap, String> {
    let conn = open_db(&app)?;
    let session_id = create_session_record(&conn, title, metadata)?;
    build_bootstrap(&conn, session_id)
}

#[tauri::command]
pub fn switch_chat_session(app: tauri::AppHandle, session_id: String) -> Result<ChatSessionPayload, String> {
    let conn = open_db(&app)?;
    if !session_exists(&conn, &session_id)? {
        return Err("Chat session not found".to_string());
    }
    conn.execute(
        "INSERT INTO app_meta (key, value) VALUES (?1, ?2)
         ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        params![ACTIVE_SESSION_KEY, session_id],
    )
    .map_err(|e| format!("failed to switch chat session: {e}"))?;

    Ok(ChatSessionPayload {
        active_session_id: session_id.clone(),
        messages: load_messages(&conn, &session_id)?,
        draft: load_draft(&conn, &session_id)?,
        metadata: load_metadata(&conn, &session_id)?,
    })
}

#[tauri::command]
pub fn rename_chat_session(app: tauri::AppHandle, session_id: String, title: String) -> Result<Vec<ChatSessionSummary>, String> {
    let conn = open_db(&app)?;
    let next_title = title.trim();
    if next_title.is_empty() {
        return Err("Title cannot be empty".to_string());
    }
    conn.execute(
        "UPDATE chat_sessions SET title = ?2, updated_at = ?3 WHERE session_id = ?1",
        params![session_id, next_title, now_ms()],
    )
    .map_err(|e| format!("failed to rename chat session: {e}"))?;
    load_sessions(&conn)
}

#[tauri::command]
pub fn delete_chat_session(app: tauri::AppHandle, session_id: String) -> Result<ChatBootstrap, String> {
    let conn = open_db(&app)?;
    conn.execute("DELETE FROM chat_sessions WHERE session_id = ?1", params![session_id])
        .map_err(|e| format!("failed to delete chat session: {e}"))?;
    let next_active = ensure_active_session(&conn)?;
    build_bootstrap(&conn, next_active)
}

#[tauri::command]
pub fn clear_chat_session(app: tauri::AppHandle, session_id: String) -> Result<Vec<ChatSessionSummary>, String> {
    let conn = open_db(&app)?;
    conn.execute("DELETE FROM chat_messages WHERE session_id = ?1", params![session_id])
        .map_err(|e| format!("failed to clear chat session messages: {e}"))?;
    conn.execute("DELETE FROM chat_drafts WHERE session_id = ?1", params![session_id])
        .map_err(|e| format!("failed to clear chat session draft: {e}"))?;
    conn.execute(
        "UPDATE chat_sessions SET title = ?2, updated_at = ?3, last_message_at = ?3, metadata_json = '{}' WHERE session_id = ?1",
        params![session_id, DEFAULT_SESSION_TITLE, now_ms()],
    )
    .map_err(|e| format!("failed to reset chat session: {e}"))?;
    load_sessions(&conn)
}

#[tauri::command]
pub fn update_chat_session_metadata(
    app: tauri::AppHandle,
    session_id: String,
    metadata: Option<ChatSessionMetadataInput>,
) -> Result<Vec<ChatSessionSummary>, String> {
    let conn = open_db(&app)?;
    if !session_exists(&conn, &session_id)? {
        return Err("Chat session not found".to_string());
    }

    let metadata_json = metadata_to_json(metadata)?;
    conn.execute(
        "UPDATE chat_sessions SET metadata_json = ?2, updated_at = ?3 WHERE session_id = ?1",
        params![session_id, metadata_json, now_ms()],
    )
    .map_err(|e| format!("failed to update chat metadata: {e}"))?;
    load_sessions(&conn)
}

#[tauri::command]
pub fn reset_all_chat_sessions(app: tauri::AppHandle) -> Result<ChatBootstrap, String> {
    let conn = open_db(&app)?;
    conn.execute("DELETE FROM chat_messages", [])
        .map_err(|e| format!("failed to clear chat messages: {e}"))?;
    conn.execute("DELETE FROM chat_drafts", [])
        .map_err(|e| format!("failed to clear chat drafts: {e}"))?;
    conn.execute("DELETE FROM chat_sessions", [])
        .map_err(|e| format!("failed to clear chat sessions: {e}"))?;
    conn.execute("DELETE FROM app_meta", [])
        .map_err(|e| format!("failed to clear chat metadata: {e}"))?;

    let session_id = create_session_record(&conn, Some(DEFAULT_SESSION_TITLE.to_string()), None)?;
    build_bootstrap(&conn, session_id)
}

#[tauri::command]
pub fn save_chat_draft(app: tauri::AppHandle, session_id: String, content: String) -> Result<(), String> {
    let conn = open_db(&app)?;
    if content.trim().is_empty() {
        conn.execute("DELETE FROM chat_drafts WHERE session_id = ?1", params![session_id])
            .map_err(|e| format!("failed to clear chat draft: {e}"))?;
        return Ok(());
    }

    conn.execute(
        "
        INSERT INTO chat_drafts (session_id, content, updated_at) VALUES (?1, ?2, ?3)
        ON CONFLICT(session_id) DO UPDATE SET content = excluded.content, updated_at = excluded.updated_at
        ",
        params![session_id, content, now_ms()],
    )
    .map_err(|e| format!("failed to save chat draft: {e}"))?;
    Ok(())
}

#[tauri::command]
pub fn save_chat_message(
    app: tauri::AppHandle,
    session_id: String,
    message: PersistedChatMessageInput,
) -> Result<Vec<ChatSessionSummary>, String> {
    let conn = open_db(&app)?;
    if !session_exists(&conn, &session_id)? {
        return Err("Chat session not found".to_string());
    }

    let now = now_ms();
    let timestamp = message
        .timestamp
        .clone()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| now.to_string());
    let tool_calls_json = serde_json::to_string(&message.tool_calls.unwrap_or_default())
        .map_err(|e| format!("failed to serialize tool calls: {e}"))?;
    let metadata_json = serde_json::to_string(&message.metadata.unwrap_or(Value::Object(Default::default())))
        .map_err(|e| format!("failed to serialize message metadata: {e}"))?;

    conn.execute(
        "
        INSERT INTO chat_messages (message_id, session_id, role, content, timestamp, confidence, tool_calls_json, metadata_json, created_at)
        VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)
        ",
        params![
            Uuid::new_v4().to_string(),
            session_id,
            message.role,
            message.content,
            timestamp,
            message.confidence,
            tool_calls_json,
            metadata_json,
            now,
        ],
    )
    .map_err(|e| format!("failed to save chat message: {e}"))?;

    update_session_title_from_message(&conn, &session_id, &message.role, &message.content)?;
    conn.execute(
        "UPDATE chat_sessions SET updated_at = ?2, last_message_at = ?2 WHERE session_id = ?1",
        params![session_id, now],
    )
    .map_err(|e| format!("failed to update chat session metadata: {e}"))?;

    Ok(load_sessions(&conn)?)
}
