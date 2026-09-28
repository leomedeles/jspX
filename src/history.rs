//! Durable, bounded history. Keys sort first by UTC milliseconds and then by
//! in-run sequence, so event ordering is stable even within one control scan.
use crate::control::{Event, ScanResult, Snapshot};
use redb::{Database, ReadableDatabase, ReadableTable, TableDefinition};
use serde::{Deserialize, Serialize};
use std::path::Path;

const SNAPSHOTS: TableDefinition<&str, &[u8]> = TableDefinition::new("snapshots_v1");
const EVENTS: TableDefinition<&str, &[u8]> = TableDefinition::new("events_v1");
pub const RETENTION_MS: i64 = 30 * 24 * 60 * 60 * 1000;

#[derive(Debug, Serialize, Deserialize)]
pub struct HistoryPage<T> {
    pub items: Vec<T>,
    pub next_cursor: Option<String>,
}

pub struct HistoryStore {
    db: Database,
    last_prune_ms: i64,
}

impl HistoryStore {
    pub fn open(path: &Path) -> Result<Self, String> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let db = Database::create(path).map_err(|e| e.to_string())?;
        let write = db.begin_write().map_err(|e| e.to_string())?;
        {
            write.open_table(SNAPSHOTS).map_err(|e| e.to_string())?;
            write.open_table(EVENTS).map_err(|e| e.to_string())?;
        }
        write.commit().map_err(|e| e.to_string())?;
        Ok(Self {
            db,
            last_prune_ms: 0,
        })
    }

    pub fn append(&mut self, result: &ScanResult, now_ms: i64) -> Result<(), String> {
        let write = self.db.begin_write().map_err(|e| e.to_string())?;
        if result.telemetry_due || result.statuses_changed {
            let key = format!(
                "{now_ms:013}-{:016}-{}",
                result.snapshot.seq, result.snapshot.run_id
            );
            let value = serde_json::to_vec(&result.snapshot).map_err(|e| e.to_string())?;
            {
                let mut table = write.open_table(SNAPSHOTS).map_err(|e| e.to_string())?;
                table
                    .insert(key.as_str(), value.as_slice())
                    .map_err(|e| e.to_string())?;
            }
        }
        if !result.events.is_empty() {
            let mut table = write.open_table(EVENTS).map_err(|e| e.to_string())?;
            for event in &result.events {
                let key = format!("{now_ms:013}-{}", event.event_id);
                let value = serde_json::to_vec(event).map_err(|e| e.to_string())?;
                table
                    .insert(key.as_str(), value.as_slice())
                    .map_err(|e| e.to_string())?;
            }
        }
        write.commit().map_err(|e| e.to_string())?;
        if now_ms - self.last_prune_ms >= 24 * 60 * 60 * 1000 {
            self.prune(now_ms)?;
            self.last_prune_ms = now_ms;
        }
        Ok(())
    }

    pub fn prune(&self, now_ms: i64) -> Result<(), String> {
        let cutoff = now_ms - RETENTION_MS;
        let bound = format!("{cutoff:013}-");
        let write = self.db.begin_write().map_err(|e| e.to_string())?;
        for def in [SNAPSHOTS, EVENTS] {
            let mut table = write.open_table(def).map_err(|e| e.to_string())?;
            let keys: Vec<String> = table
                .range(..bound.as_str())
                .map_err(|e| e.to_string())?
                .map(|r| {
                    r.map(|(k, _)| k.value().to_string())
                        .map_err(|e| e.to_string())
                })
                .collect::<Result<_, _>>()?;
            for key in keys {
                table.remove(key.as_str()).map_err(|e| e.to_string())?;
            }
        }
        write.commit().map_err(|e| e.to_string())
    }

    fn query<T: for<'de> Deserialize<'de>>(
        &self,
        def: TableDefinition<&str, &[u8]>,
        from_ms: i64,
        to_ms: i64,
        limit: usize,
        cursor: Option<&str>,
    ) -> Result<HistoryPage<T>, String> {
        let lower = cursor
            .map(str::to_string)
            .unwrap_or_else(|| format!("{from_ms:013}-"));
        let upper = format!("{to_ms:013}-~");
        let read = self.db.begin_read().map_err(|e| e.to_string())?;
        let table = read.open_table(def).map_err(|e| e.to_string())?;
        let mut items = Vec::new();
        let mut next_cursor = None;
        let mut last_key = None;
        for pair in table
            .range(lower.as_str()..=upper.as_str())
            .map_err(|e| e.to_string())?
        {
            let (k, v) = pair.map_err(|e| e.to_string())?;
            if cursor.is_some_and(|c| k.value() == c) {
                continue;
            }
            if items.len() == limit {
                next_cursor = last_key;
                break;
            }
            last_key = Some(k.value().to_string());
            items.push(serde_json::from_slice(v.value()).map_err(|e| e.to_string())?);
        }
        Ok(HistoryPage { items, next_cursor })
    }
    pub fn snapshots(
        &self,
        from_ms: i64,
        to_ms: i64,
        limit: usize,
        cursor: Option<&str>,
    ) -> Result<HistoryPage<Snapshot>, String> {
        self.query(SNAPSHOTS, from_ms, to_ms, limit, cursor)
    }
    pub fn events(
        &self,
        from_ms: i64,
        to_ms: i64,
        limit: usize,
        cursor: Option<&str>,
    ) -> Result<HistoryPage<Event>, String> {
        self.query(EVENTS, from_ms, to_ms, limit, cursor)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::control::Simulator;
    #[test]
    fn history_is_durable_ordered_and_prunes_after_thirty_days() {
        let path = std::env::temp_dir().join(format!("jspx-history-{}.redb", uuid::Uuid::new_v4()));
        let old = 1_800_000_000_000i64;
        let mut sim = Simulator::default();
        {
            let mut db = HistoryStore::open(&path).unwrap();
            let first = sim.scan(0, "2027-01-15T08:00:00Z".into(), None, true);
            db.append(&first, old).unwrap();
            assert_eq!(db.snapshots(old, old, 10, None).unwrap().items.len(), 1);
            assert!(
                db.events(old, old, 10, None)
                    .unwrap()
                    .items
                    .iter()
                    .any(|e| e.event == "RUN_STARTED")
            );
        }
        let db = HistoryStore::open(&path).unwrap();
        assert_eq!(db.snapshots(old, old, 10, None).unwrap().items.len(), 1);
        db.prune(old + RETENTION_MS + 1).unwrap();
        assert!(db.snapshots(old, old, 10, None).unwrap().items.is_empty());
        drop(db);
        let _ = std::fs::remove_file(path);
    }
}
