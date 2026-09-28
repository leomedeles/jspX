use crate::control::{Action, BREAKERS, Intent, Snapshot};
use crate::history::{HistoryPage, HistoryStore, RETENTION_MS};
use crate::plant::Scenario;
use axum::{
    Json, Router,
    extract::{Path, Query, State},
    http::StatusCode,
    response::{
        IntoResponse, Response,
        sse::{Event as SseEvent, KeepAlive, Sse},
    },
    routing::{get, post},
};
use chrono::{DateTime, Utc};
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    convert::Infallible,
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};
use tokio::sync::{RwLock, broadcast, mpsc};
use tokio_stream::wrappers::BroadcastStream;
use uuid::Uuid;

#[derive(Clone)]
pub struct AppState {
    pub queue: mpsc::Sender<Intent>,
    pub latest: Arc<RwLock<Option<Snapshot>>>,
    pub live: broadcast::Sender<String>,
    pub history: Arc<Mutex<HistoryStore>>,
    pub ready: Arc<AtomicBool>,
}

#[derive(Serialize)]
pub struct Accepted {
    pub request_id: String,
    pub queued: bool,
}
#[derive(Deserialize)]
pub struct CommandBody {
    pub command: Action,
}
#[derive(Deserialize)]
pub struct ScenarioBody {
    pub scenario: Scenario,
}
#[derive(Default, Deserialize)]
pub struct RangeQuery {
    pub from: Option<String>,
    pub to: Option<String>,
    pub limit: Option<usize>,
    pub cursor: Option<String>,
}

fn error(status: StatusCode, message: &str) -> Response {
    (status, Json(json!({"error":message}))).into_response()
}
fn queued(state: &AppState, intent: Intent, request_id: String) -> Response {
    if !state.ready.load(Ordering::Relaxed) {
        return error(StatusCode::SERVICE_UNAVAILABLE, "scan unavailable");
    }
    match state.queue.try_send(intent) {
        Ok(()) => (
            StatusCode::ACCEPTED,
            Json(Accepted {
                request_id,
                queued: true,
            }),
        )
            .into_response(),
        Err(_) => error(StatusCode::SERVICE_UNAVAILABLE, "command queue full"),
    }
}
async fn snapshot(State(state): State<AppState>) -> Response {
    match state.latest.read().await.clone() {
        Some(s) => Json(s).into_response(),
        None => error(StatusCode::SERVICE_UNAVAILABLE, "no completed scan"),
    }
}
async fn breaker_command(
    State(state): State<AppState>,
    Path(breaker): Path<String>,
    Json(body): Json<CommandBody>,
) -> Response {
    if !BREAKERS.contains(&breaker.as_str()) {
        return error(StatusCode::NOT_FOUND, "unknown breaker");
    }
    let request_id = Uuid::new_v4().to_string();
    queued(
        &state,
        Intent::Breaker {
            breaker,
            action: body.command,
            request_id: request_id.clone(),
        },
        request_id,
    )
}
async fn scenario_command(
    State(state): State<AppState>,
    Json(body): Json<ScenarioBody>,
) -> Response {
    let request_id = Uuid::new_v4().to_string();
    queued(
        &state,
        Intent::Scenario {
            scenario: body.scenario,
            request_id: request_id.clone(),
        },
        request_id,
    )
}
async fn stream(
    State(state): State<AppState>,
) -> Sse<impl futures_util::Stream<Item = Result<SseEvent, Infallible>>> {
    let rx = state.live.subscribe();
    let stream = BroadcastStream::new(rx).map(|r| {
        let data = match r {
            Ok(msg) => msg,
            Err(_) => r#"{"kind":"resync"}"#.to_string(),
        };
        Ok(SseEvent::default().data(data))
    });
    Sse::new(stream).keep_alive(
        KeepAlive::new()
            .interval(Duration::from_secs(10))
            .text("ping"),
    )
}

fn range(q: &RangeQuery) -> Result<(i64, i64, usize), &'static str> {
    let now = Utc::now().timestamp_millis();
    let parse = |s: &str| {
        DateTime::parse_from_rfc3339(s)
            .map(|d| d.timestamp_millis())
            .map_err(|_| "expected ISO-8601 UTC time")
    };
    let to = match &q.to {
        Some(v) => parse(v)?,
        None => now,
    };
    let from = match &q.from {
        Some(v) => parse(v)?,
        None => to - 15 * 60 * 1000,
    };
    if from > to
        || to - from > 24 * 60 * 60 * 1000
        || from < now - RETENTION_MS
        || to > now + 60_000
    {
        return Err("range must be within retained 30 days and at most 24 hours");
    }
    let limit = q.limit.unwrap_or(5000);
    if !(1..=10000).contains(&limit) {
        return Err("limit must be 1..10000");
    }
    Ok((from, to, limit))
}
async fn history(State(state): State<AppState>, Query(q): Query<RangeQuery>) -> Response {
    let (from, to, limit) = match range(&q) {
        Ok(v) => v,
        Err(e) => return error(StatusCode::BAD_REQUEST, e),
    };
    let result: Result<HistoryPage<Snapshot>, String> =
        state
            .history
            .lock()
            .unwrap()
            .snapshots(from, to, limit, q.cursor.as_deref());
    match result {
        Ok(page) => Json(page).into_response(),
        Err(e) => {
            eprintln!("history read error: {e}");
            error(StatusCode::SERVICE_UNAVAILABLE, "history read failed")
        }
    }
}
async fn events(State(state): State<AppState>, Query(q): Query<RangeQuery>) -> Response {
    let (from, to, limit) = match range(&q) {
        Ok(v) => v,
        Err(e) => return error(StatusCode::BAD_REQUEST, e),
    };
    let result = state
        .history
        .lock()
        .unwrap()
        .events(from, to, limit, q.cursor.as_deref());
    match result {
        Ok(page) => Json(page).into_response(),
        Err(e) => {
            eprintln!("event read error: {e}");
            error(StatusCode::SERVICE_UNAVAILABLE, "event read failed")
        }
    }
}
async fn live() -> StatusCode {
    StatusCode::OK
}
async fn ready(State(state): State<AppState>) -> StatusCode {
    if state.ready.load(Ordering::Relaxed) {
        StatusCode::OK
    } else {
        StatusCode::SERVICE_UNAVAILABLE
    }
}

pub fn publish_live(state: &AppState, kind: &str, data: Value) {
    let _ = state
        .live
        .send(json!({"kind":kind,"data":data}).to_string());
}

pub fn router(state: AppState) -> Router {
    Router::new()
        .route("/api/v1/snapshot", get(snapshot))
        .route("/api/v1/stream", get(stream))
        .route("/api/v1/breakers/{id}/commands", post(breaker_command))
        .route("/api/v1/test/scenarios", post(scenario_command))
        .route("/api/v1/history", get(history))
        .route("/api/v1/events", get(events))
        .route("/health/live", get(live))
        .route("/health/ready", get(ready))
        .with_state(state)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn command_acknowledges_queue_only() {
        let path = std::env::temp_dir().join(format!("jspx-api-{}.redb", Uuid::new_v4()));
        let (tx, mut rx) = mpsc::channel(1);
        let (live, _) = broadcast::channel(4);
        let state = AppState {
            queue: tx,
            latest: Arc::new(RwLock::new(None)),
            live,
            history: Arc::new(Mutex::new(HistoryStore::open(&path).unwrap())),
            ready: Arc::new(AtomicBool::new(true)),
        };
        let response = breaker_command(
            State(state.clone()),
            Path("BRK_R1".into()),
            Json(CommandBody {
                command: Action::Open,
            }),
        )
        .await;
        assert_eq!(response.status(), StatusCode::ACCEPTED);
        assert!(
            matches!(rx.try_recv(),Ok(Intent::Breaker{breaker,action:Action::Open,..}) if breaker=="BRK_R1")
        );
        let unknown = breaker_command(
            State(state.clone()),
            Path("BAD".into()),
            Json(CommandBody {
                command: Action::Open,
            }),
        )
        .await;
        assert_eq!(unknown.status(), StatusCode::NOT_FOUND);
        drop(state);
        let _ = std::fs::remove_file(path);
    }
}
