"""SQLite 状态存储：事件去重、仓位基线、快照历史。"""

import json
import os
import sqlite3
import threading


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id      TEXT PRIMARY KEY,
    ts      INTEGER NOT NULL,
    address TEXT NOT NULL,
    kind    TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
    address   TEXT NOT NULL,
    coin      TEXT NOT NULL,
    szi       TEXT NOT NULL,
    entry_px  TEXT NOT NULL,
    notional  TEXT NOT NULL,
    open_time_ms INTEGER,
    leverage  TEXT,
    peak_notional TEXT,
    updated_ms INTEGER NOT NULL,
    PRIMARY KEY (address, coin)
);
CREATE TABLE IF NOT EXISTS spot_balances (
    address    TEXT NOT NULL,
    coin       TEXT NOT NULL,
    total      TEXT NOT NULL,
    hold       TEXT NOT NULL,
    updated_ms INTEGER NOT NULL,
    PRIMARY KEY (address, coin)
);
CREATE TABLE IF NOT EXISTS snapshots (
    address        TEXT NOT NULL,
    ts             INTEGER NOT NULL,
    account_value  REAL,
    total_ntl_pos  REAL,
    withdrawable   REAL
);
CREATE TABLE IF NOT EXISTS subscriptions (
    chat_id    TEXT NOT NULL,
    address    TEXT NOT NULL,
    alias      TEXT NOT NULL DEFAULT '',
    active     INTEGER NOT NULL DEFAULT 1,
    updated_ms INTEGER NOT NULL,
    PRIMARY KEY (chat_id, address)
);
CREATE TABLE IF NOT EXISTS chat_settings (
    chat_id    TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    updated_ms INTEGER NOT NULL,
    PRIMARY KEY (chat_id, key)
);
CREATE TABLE IF NOT EXISTS collected_accounts (
    address            TEXT PRIMARY KEY,
    alias              TEXT NOT NULL DEFAULT '',
    account_value      TEXT NOT NULL,
    volume             TEXT NOT NULL,
    pnl                TEXT NOT NULL,
    roi                TEXT NOT NULL,
    win_rate           TEXT NOT NULL,
    weighted_win_rate  TEXT NOT NULL,
    profit_factor      TEXT NOT NULL,
    score              TEXT NOT NULL,
    sample_size        INTEGER NOT NULL,
    scanned_at         INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS auto_accounts (
    chat_id       TEXT NOT NULL,
    address       TEXT NOT NULL,
    alias         TEXT NOT NULL DEFAULT '',
    account_value REAL NOT NULL DEFAULT 0,
    scanned_at    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, address)
);
CREATE TABLE IF NOT EXISTS auto_process_accounts (
    chat_id       TEXT NOT NULL,
    proc          TEXT NOT NULL,
    address       TEXT NOT NULL,
    alias         TEXT NOT NULL DEFAULT '',
    account_value REAL NOT NULL DEFAULT 0,
    scanned_at    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, proc, address)
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_snapshots_addr_ts ON snapshots(address, ts);
"""


class EventStore:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("PRAGMA busy_timeout = 5000")
        with self._lock:
            self.conn.executescript(SCHEMA)
            self._ensure_column("positions", "open_time_ms", "INTEGER")
            self._ensure_column("positions", "leverage", "TEXT")
            self._ensure_column("positions", "peak_notional", "TEXT")
            self.conn.commit()

    def _ensure_column(self, table, column, column_type):
        rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        if column not in {row[1] for row in rows}:
            self.conn.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {column_type}"
            )

    def event_exists(self, key):
        with self._lock:
            row = self.conn.execute(
                "SELECT 1 FROM events WHERE id = ?", (key,)
            ).fetchone()
        return row is not None

    def save_event(self, key, ts, address, kind, text, data):
        """返回 True 表示新事件已写入（之前不存在）。"""
        with self._lock:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO events(id, ts, address, kind, payload) VALUES (?,?,?,?,?)",
                (
                    key,
                    int(ts or 0),
                    address,
                    kind,
                    json.dumps({"text": text, "data": data}, ensure_ascii=False),
                ),
            )
            self.conn.commit()
        return cur.rowcount > 0

    def recent_events(self, limit=30):
        with self._lock:
            rows = self.conn.execute(
                "SELECT ts, address, kind, payload FROM events ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for ts, address, kind, payload in rows:
            body = json.loads(payload)
            out.append(
                {
                    "time": ts,
                    "address": address,
                    "kind": kind,
                    "text": body.get("text", ""),
                    "data": body.get("data", {}),
                }
            )
        return out

    def get_positions(self, address):
        with self._lock:
            rows = self.conn.execute(
                "SELECT coin, szi, entry_px, notional, open_time_ms, leverage, peak_notional"
                " FROM positions WHERE address = ?",
                (address,),
            ).fetchall()
        return {
            coin: {
                "szi": szi,
                "entry_px": entry_px,
                "notional": notional,
                "open_time_ms": open_time_ms,
                "leverage": leverage,
                "peak_notional": peak_notional,
            }
            for coin, szi, entry_px, notional, open_time_ms, leverage, peak_notional in rows
        }

    def save_positions(self, address, positions, ts):
        with self._lock:
            self.conn.execute("DELETE FROM positions WHERE address = ?", (address,))
            self.conn.executemany(
                "INSERT INTO positions(address, coin, szi, entry_px, notional, open_time_ms, leverage, peak_notional, updated_ms)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                [
                    (
                        address,
                        coin,
                        str(pos["szi"]),
                        str(pos.get("entry_px", "")),
                        str(pos.get("notional", pos.get("positionValue", "0"))),
                        int(pos.get("open_time_ms") or 0),
                        str(pos.get("leverage", "") or ""),
                        str(pos.get("peak_notional", "") or ""),
                        int(ts or 0),
                    )
                    for coin, pos in positions.items()
                ],
            )
            self.conn.commit()

    def get_spot_balances(self, address):
        with self._lock:
            rows = self.conn.execute(
                "SELECT coin, total, hold FROM spot_balances WHERE address = ?",
                (address,),
            ).fetchall()
        return {
            coin: {"total": total, "hold": hold}
            for coin, total, hold in rows
        }

    def save_spot_balances(self, address, balances, ts):
        with self._lock:
            self.conn.execute(
                "DELETE FROM spot_balances WHERE address = ?", (address,)
            )
            self.conn.executemany(
                "INSERT INTO spot_balances(address, coin, total, hold, updated_ms)"
                " VALUES (?,?,?,?,?)",
                [
                    (
                        address,
                        coin,
                        str(balance.get("total", "0")),
                        str(balance.get("hold", "0")),
                        int(ts or 0),
                    )
                    for coin, balance in balances.items()
                ],
            )
            self.conn.commit()

    def upsert_collected_account(self, account):
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO collected_accounts("
                "address, alias, account_value, volume, pnl, roi, win_rate,"
                " weighted_win_rate, profit_factor, score, sample_size, scanned_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(account.get("address", "")).lower(),
                    str(account.get("alias", "") or ""),
                    str(account.get("account_value", 0)),
                    str(account.get("volume", 0)),
                    str(account.get("pnl", 0)),
                    str(account.get("roi", 0)),
                    str(account.get("win_rate", 0)),
                    str(account.get("weighted_win_rate", 0)),
                    str(account.get("profit_factor", 0)),
                    str(account.get("score", 0)),
                    int(account.get("sample_size", 0)),
                    int(account.get("scanned_at") or 0),
                ),
            )
            self.conn.commit()

    def get_collected_accounts(self):
        with self._lock:
            rows = self.conn.execute(
                "SELECT address, alias, account_value, volume, pnl, roi, win_rate,"
                " weighted_win_rate, profit_factor, score, sample_size, scanned_at"
                " FROM collected_accounts ORDER BY score DESC"
            ).fetchall()
        return [
            {
                "address": address,
                "alias": alias,
                "account_value": _as_float(account_value, 0),
                "volume": _as_float(volume, 0),
                "pnl": _as_float(pnl, 0),
                "roi": _as_float(roi, 0),
                "win_rate": _as_float(win_rate, 0),
                "weighted_win_rate": _as_float(weighted_win_rate, 0),
                "profit_factor": _as_float(profit_factor, 0),
                "score": _as_float(score, 0),
                "sample_size": int(sample_size or 0),
                "scanned_at": int(scanned_at or 0),
            }
            for address, alias, account_value, volume, pnl, roi, win_rate,
            weighted_win_rate, profit_factor, score, sample_size, scanned_at in rows
        ]

    def upsert_auto_account(self, chat_id, proc, account, ts=None):
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO auto_process_accounts("
                " chat_id, proc, address, alias, account_value, scanned_at)"
                " VALUES (?,?,?,?,?,?)",
                (
                    str(chat_id),
                    str(proc or "default"),
                    str(account.get("address", "")).lower(),
                    str(account.get("alias") or ""),
                    _as_float(account.get("account_value"), 0.0),
                    int(ts or account.get("scanned_at") or 0),
                ),
            )
            self.conn.commit()

    def get_auto_accounts(self, chat_id, proc):
        with self._lock:
            rows = self.conn.execute(
                "SELECT address, alias, account_value, scanned_at"
                " FROM auto_process_accounts"
                " WHERE chat_id = ? AND proc = ?"
                " ORDER BY scanned_at DESC, account_value DESC",
                (str(chat_id), str(proc or "default")),
            ).fetchall()
        return [
            {
                "address": address,
                "alias": alias,
                "account_value": account_value,
                "scanned_at": int(scanned_at or 0),
            }
            for address, alias, account_value, scanned_at in rows
        ]

    def remove_auto_accounts(self, chat_id, proc):
        with self._lock:
            self.conn.execute(
                "DELETE FROM auto_process_accounts WHERE chat_id = ? AND proc = ?",
                (str(chat_id), str(proc or "default")),
            )
            self.conn.commit()

    def get_autohunt_names(self, chat_id):
        with self._lock:
            rows = self.conn.execute(
                "SELECT key FROM chat_settings"
                " WHERE chat_id = ? AND key LIKE 'autohunt_proc:%:coins'",
                (str(chat_id),),
            ).fetchall()
        names = []
        prefix = "autohunt_proc:"
        for (key,) in rows:
            name = key[len(prefix):-len(":coins")]
            if name and name not in names:
                names.append(name)
        return names

    def enabled_autohunt_processes(self):
        with self._lock:
            rows = self.conn.execute(
                "SELECT chat_id, key FROM chat_settings"
                " WHERE key LIKE 'autohunt_proc:%:enabled' AND value = '1'",
            ).fetchall()
        out = []
        prefix = "autohunt_proc:"
        for chat_id, key in rows:
            name = key[len(prefix):-len(":enabled")]
            if name:
                out.append((str(chat_id), name))
        return out

    def chat_ids_with_setting(self, key, value="1"):
        with self._lock:
            rows = self.conn.execute(
                "SELECT chat_id FROM chat_settings WHERE key = ? AND value = ?",
                (key, value),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def delete_collected_account(self, address):
        with self._lock:
            self.conn.execute(
                "DELETE FROM collected_accounts WHERE address = ?",
                (str(address).lower(),),
            )
            self.conn.commit()

    def get_last_snapshot(self, address):
        with self._lock:
            row = self.conn.execute(
                "SELECT account_value, total_ntl_pos, withdrawable, ts"
                " FROM snapshots WHERE address = ? ORDER BY ts DESC LIMIT 1",
                (address,),
            ).fetchone()
        if row is None:
            return None
        return {
            "account_value": row[0],
            "total_ntl_pos": row[1],
            "withdrawable": row[2],
            "time": row[3],
        }

    def save_snapshot(self, address, account_value, total_ntl_pos, withdrawable, ts):
        with self._lock:
            self.conn.execute(
                "INSERT INTO snapshots(address, ts, account_value, total_ntl_pos, withdrawable)"
                " VALUES (?,?,?,?,?)",
                (address, int(ts or 0), account_value, total_ntl_pos, withdrawable),
            )
            self.conn.commit()

    def subscribe(self, chat_id, address, alias="", active=True, ts=None):
        with self._lock:
            self.conn.execute(
                "INSERT INTO subscriptions(chat_id, address, alias, active, updated_ms)"
                " VALUES (?,?,?,?,?)"
                " ON CONFLICT(chat_id, address) DO UPDATE SET"
                " alias = excluded.alias,"
                " active = excluded.active,"
                " updated_ms = excluded.updated_ms",
                (
                    str(chat_id),
                    address.lower(),
                    alias or "",
                    1 if active else 0,
                    int(ts or 0),
                ),
            )
            self.conn.commit()

    def set_subscription_alias(self, chat_id, address, alias, ts=None):
        with self._lock:
            self.conn.execute(
                "UPDATE subscriptions SET alias = ?, updated_ms = ?"
                " WHERE chat_id = ? AND address = ?",
                (
                    alias or "",
                    int(ts or 0),
                    str(chat_id),
                    address.lower(),
                ),
            )
            self.conn.commit()

    def unsubscribe(self, chat_id, address):
        with self._lock:
            self.conn.execute(
                "DELETE FROM subscriptions WHERE chat_id = ? AND address = ?",
                (str(chat_id), address.lower()),
            )
            self.conn.commit()

    def clear_subscriptions(self, chat_id):
        with self._lock:
            self.conn.execute(
                "DELETE FROM subscriptions WHERE chat_id = ?",
                (str(chat_id),),
            )
            self.conn.commit()

    def set_chat_active(self, chat_id, active, ts=None):
        with self._lock:
            self.conn.execute(
                "UPDATE subscriptions SET active = ?, updated_ms = ? WHERE chat_id = ?",
                (1 if active else 0, int(ts or 0), str(chat_id)),
            )
            self.conn.commit()

    def get_subscriptions(self, chat_id=None, active_only=True):
        query = (
            "SELECT chat_id, address, alias, active, updated_ms"
            " FROM subscriptions"
        )
        params = []
        if chat_id is not None:
            query += " WHERE chat_id = ?"
            params.append(str(chat_id))
        if active_only:
            query += " AND active = 1" if chat_id is not None else " WHERE active = 1"
        query += " ORDER BY updated_ms DESC"
        with self._lock:
            rows = self.conn.execute(query, params).fetchall()
        return [
            {
                "chat_id": chat_id,
                "address": address,
                "alias": alias,
                "active": bool(active),
                "updated_ms": updated_ms,
            }
            for chat_id, address, alias, active, updated_ms in rows
        ]

    def subscribed_chats(self, address, active_only=True):
        query = (
            "SELECT chat_id FROM subscriptions WHERE address = ?"
        )
        if active_only:
            query += " AND active = 1"
        with self._lock:
            rows = self.conn.execute(query, (address.lower(),)).fetchall()
        return [row[0] for row in rows]

    def all_watched_addresses(self, active_only=True):
        query = "SELECT DISTINCT address FROM subscriptions"
        if active_only:
            query += " WHERE active = 1"
        with self._lock:
            rows = self.conn.execute(query).fetchall()
        return [row[0] for row in rows]

    def get_chat_setting(self, chat_id, key, default=None):
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM chat_settings WHERE chat_id = ? AND key = ?",
                (str(chat_id), key),
            ).fetchone()
        if row is None:
            return default
        if row[0] == "None":
            self.conn.execute(
                "DELETE FROM chat_settings WHERE chat_id = ? AND key = ?",
                (str(chat_id), key),
            )
            self.conn.commit()
            return default
        return row[0]

    def set_chat_setting(self, chat_id, key, value, ts=None):
        with self._lock:
            if value is None:
                self.conn.execute(
                    "DELETE FROM chat_settings WHERE chat_id = ? AND key = ?",
                    (str(chat_id), key),
                )
            else:
                self.conn.execute(
                    "INSERT INTO chat_settings(chat_id, key, value, updated_ms)"
                    " VALUES (?,?,?,?)"
                    " ON CONFLICT(chat_id, key) DO UPDATE SET"
                    " value = excluded.value,"
                    " updated_ms = excluded.updated_ms",
                    (str(chat_id), key, str(value), int(ts or 0)),
                )
            self.conn.commit()

    def close(self):
        with self._lock:
            self.conn.close()
