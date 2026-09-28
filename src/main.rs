use chrono::{SecondsFormat, Utc};
use jspx::{
    api::{self, AppState},
    control::{Intent, Simulator},
    history::HistoryStore,
};
use std::{
    path::PathBuf,
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, Instant},
};
use tokio::{
    sync::{RwLock, broadcast, mpsc},
    time::{MissedTickBehavior, interval},
};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let address = std::env::var("JSPX_BIND").unwrap_or_else(|_| "127.0.0.1:8088".into());
    let db_path =
        PathBuf::from(std::env::var("JSPX_DB").unwrap_or_else(|_| "data/history.redb".into()));
    let history = Arc::new(Mutex::new(HistoryStore::open(&db_path)?));
    let (queue, mut incoming) = mpsc::channel::<Intent>(1024);
    let (live, _) = broadcast::channel(2048);
    let state = AppState {
        queue,
        latest: Arc::new(RwLock::new(None)),
        live,
        history,
        ready: Arc::new(AtomicBool::new(false)),
    };
    let scanner = state.clone();
    tokio::spawn(async move {
        let mut simulator = Simulator::default();
        let start = Instant::now();
        let mut ticks = interval(Duration::from_millis(50));
        ticks.set_missed_tick_behavior(MissedTickBehavior::Skip);
        let mut next_publish = Instant::now();
        loop {
            ticks.tick().await;
            let publish_due = Instant::now() >= next_publish;
            if publish_due {
                next_publish = Instant::now() + Duration::from_secs(1);
            }
            let intent = incoming.try_recv().ok();
            let now_ms = start.elapsed().as_millis() as u64;
            let wall = Utc::now();
            let ts = wall.to_rfc3339_opts(SecondsFormat::Millis, true);
            let result = simulator.scan(now_ms, ts, intent, publish_due);
            let stored = scanner
                .history
                .lock()
                .unwrap()
                .append(&result, wall.timestamp_millis());
            if let Err(e) = stored {
                eprintln!("historian write failed; stopping scan: {e}");
                scanner.ready.store(false, Ordering::Relaxed);
                std::process::exit(1);
            }
            *scanner.latest.write().await = Some(result.snapshot.clone());
            scanner.ready.store(true, Ordering::Relaxed);
            if result.telemetry_due || result.statuses_changed {
                api::publish_live(
                    &scanner,
                    "snapshot",
                    serde_json::to_value(&result.snapshot).unwrap(),
                );
            }
            for event in result.events {
                api::publish_live(&scanner, "event", serde_json::to_value(event).unwrap());
            }
        }
    });
    let app = api::router(state);
    let listener = tokio::net::TcpListener::bind(address).await?;
    println!("jspx Rust v1 listening on {}", listener.local_addr()?);
    axum::serve(listener, app).await?;
    Ok(())
}
