"""Durable event receipt and delivery state; no AstrBot dependency."""
from __future__ import annotations
import json
import sqlite3
import time
from pathlib import Path


class Inbox:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT "pending", attempts INTEGER NOT NULL DEFAULT 0, available REAL NOT NULL, created REAL NOT NULL, error TEXT NOT NULL DEFAULT "")')
        path.chmod(0o600)

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def accept(self, event: dict) -> bool:
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM events WHERE id=?', (event['id'],)).fetchone():
                return True
            if db.execute('SELECT count(*) FROM events WHERE state!="sent"').fetchone()[0] >= 1000:
                return False
            now = time.time()
            db.execute('INSERT INTO events(id,payload,available,created) VALUES(?,?,?,?)', (event['id'], json.dumps(event, ensure_ascii=False), now, now))
            return True

    def next(self):
        with self.connect() as db:
            row = db.execute('SELECT id,payload,attempts FROM events WHERE state="pending" AND available<=? ORDER BY available,id LIMIT 1', (time.time(),)).fetchone()
        return (row[0], json.loads(row[1]), row[2]) if row else None

    def finish(self, event_id: str, attempts: int, error: bool = False):
        with self.connect() as db:
            if error:
                attempts += 1
                db.execute('UPDATE events SET state=?,attempts=?,available=?,error=? WHERE id=?', ('failed' if attempts >= 10 else 'pending', attempts, time.time()+min(30*2**min(attempts-1,7),3600), '通知发送失败，请检查平台连接和绑定会话', event_id))
            else:
                db.execute('UPDATE events SET state="sent",error="" WHERE id=?', (event_id,))
                db.execute('DELETE FROM events WHERE state="sent" AND created<?', (time.time()-30*86400,))

    def status(self):
        with self.connect() as db:
            return dict(db.execute('SELECT state,count(*) FROM events GROUP BY state').fetchall())

    def retry(self):
        with self.connect() as db:
            return db.execute('UPDATE events SET state="pending",attempts=0,available=?,error="" WHERE state="failed"', (time.time(),)).rowcount
