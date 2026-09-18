"""SQLite 状态存储：事件去重、仓位基线、快照历史。"""

import json
import os
import sqlite3
import threading


# Web 面板在 subscriptions / whale_* 表里使用的虚拟 chat_id。
WEB_CHAT_ID = "__web__"


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
CREATE TABLE IF NOT EXISTS auto_scanned (
    chat_id     TEXT NOT NULL,
    proc        TEXT NOT NULL,
    address     TEXT NOT NULL,
    scanned_at  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, proc, address)
);
CREATE TABLE IF NOT EXISTS whale_watches (
    chat_id         TEXT NOT NULL,
    chain           TEXT NOT NULL,
    token           TEXT NOT NULL,
    address         TEXT NOT NULL,
    symbol          TEXT NOT NULL DEFAULT '',
    label           TEXT NOT NULL DEFAULT '',
    decimals        INTEGER,
    last_balance    REAL,
    last_checked_ms INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT NOT NULL DEFAULT '',
    interval_s      REAL NOT NULL DEFAULT 300,
    min_delta_pct   REAL NOT NULL DEFAULT 2,
    min_delta_abs   REAL NOT NULL DEFAULT 0,
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_ms      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, chain, token, address)
);
CREATE TABLE IF NOT EXISTS whale_tokens (
    chat_id          TEXT NOT NULL,
    chain            TEXT NOT NULL,
    token            TEXT NOT NULL,
    symbol           TEXT NOT NULL DEFAULT '',
    label            TEXT NOT NULL DEFAULT '',
    last_top_address TEXT NOT NULL DEFAULT '',
    last_top_pct     REAL,
    last_score       REAL,
    last_scan_ms     INTEGER NOT NULL DEFAULT 0,
    last_error       TEXT NOT NULL DEFAULT '',
    interval_s       REAL NOT NULL DEFAULT 21600,
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_ms       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, chain, token)
);
CREATE TABLE IF NOT EXISTS whale_scans (
    chain      TEXT NOT NULL,
    token      TEXT NOT NULL,
    payload    TEXT NOT NULL,
    scanned_ms INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chain, token)
);
CREATE TABLE IF NOT EXISTS whale_scan_history (
    chain         TEXT NOT NULL,
    token         TEXT NOT NULL,
    scanned_ms    INTEGER NOT NULL,
    whale_address TEXT NOT NULL DEFAULT '',
    whale_pct     REAL,
    top10_pct     REAL,
    score         REAL,
    PRIMARY KEY (chain, token, scanned_ms)
);
CREATE TABLE IF NOT EXISTS whale_txs (
    chat_id      TEXT NOT NULL,
    chain        TEXT NOT NULL,
    token        TEXT NOT NULL,
    address      TEXT NOT NULL,
    tx_hash      TEXT NOT NULL,
    ts           INTEGER NOT NULL DEFAULT 0,
    direction    TEXT NOT NULL DEFAULT '',
    counterparty TEXT NOT NULL DEFAULT '',
    value        REAL,
    asset        TEXT NOT NULL DEFAULT '',
    url          TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (chat_id, chain, token, address, tx_hash)
);
CREATE INDEX IF NOT EXISTS idx_whale_txs_ts ON whale_txs(ts);
CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_ms INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_whale_watches_chat ON whale_watches(chat_id);
CREATE INDEX IF NOT EXISTS idx_whale_tokens_chat ON whale_tokens(chat_id);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_snapshots_addr_ts ON snapshots(address, ts);
"""


class EventStore:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        # Telegram bot 和 Web 面板会同时打开这个库，用 WAL 让读写并发，
        # 配合 busy_timeout 避免两边互相锁死。
        try:
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.conn.execute("PRAGMA synchronous = NORMAL")
        except sqlite3.DatabaseError:
            pass
        self.conn.execute("PRAGMA busy_timeout = 5000")
        with self._lock:
            self.conn.executescript(SCHEMA)
            self._ensure_column("positions", "open_time_ms", "INTEGER")
            self._ensure_column("positions", "leverage", "TEXT")
            self._ensure_column("positions", "peak_notional", "TEXT")
            self._ensure_column(
                "whale_watches", "last_tx_ms", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column(
                "whale_watches", "tx_error", "TEXT NOT NULL DEFAULT ''"
            )
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

    def record_auto_scanned(self, chat_id, proc, addresses, ts=None):
        if not addresses:
            return
        ts = int(ts or 0)
        with self._lock:
            self.conn.executemany(
                "INSERT OR REPLACE INTO auto_scanned("
                " chat_id, proc, address, scanned_at) VALUES (?,?,?,?)",
                [
                    (str(chat_id), str(proc or "default"), str(addr).lower(), ts)
                    for addr in addresses
                ],
            )
            self.conn.commit()

    def recent_auto_scanned(self, chat_id, proc, since_ms):
        with self._lock:
            rows = self.conn.execute(
                "SELECT address FROM auto_scanned"
                " WHERE chat_id = ? AND proc = ? AND scanned_at >= ?",
                (str(chat_id), str(proc or "default"), int(since_ms)),
            ).fetchall()
        return {str(row[0]) for row in rows}

    def purge_auto_scanned(self, chat_id, proc, before_ms):
        with self._lock:
            self.conn.execute(
                "DELETE FROM auto_scanned"
                " WHERE chat_id = ? AND proc = ? AND scanned_at < ?",
                (str(chat_id), str(proc or "default"), int(before_ms)),
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

    def all_autohunt_configs(self):
        """跨聊天汇总所有 autohunt 进程配置。"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT chat_id, key, value FROM chat_settings"
                " WHERE key LIKE 'autohunt_proc:%'"
            ).fetchall()
        grouped = {}
        prefix = "autohunt_proc:"
        for chat_id, key, value in rows:
            rest = str(key)[len(prefix):]
            if ":" not in rest:
                continue
            name, field = rest.rsplit(":", 1)
            if not name:
                continue
            grouped.setdefault((str(chat_id), name), {})[field] = value
        return [
            {"chat_id": chat_id, "name": name, "settings": settings}
            for (chat_id, name), settings in sorted(grouped.items())
        ]
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

    def delete_subscriptions_by_address(self, address):
        """把某个地址从所有聊天里取消订阅，返回受影响的行数。"""
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM subscriptions WHERE address = ?",
                (str(address).lower(),),
            )
            self.conn.commit()
        return cur.rowcount

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

    @staticmethod
    def merge_whale_rows(rows, key_fields):
        """把不同 chat_id 里的同一目标合并成一行。

        网页面板展示的是并集，但告警仍按各自的 chat_id 发送，
        所以这里保住 chat_ids 列表；监控参数取最严格的一组。
        """
        merged = {}
        for row in rows:
            key = tuple(str(row.get(field) or "") for field in key_fields)
            item = merged.get(key)
            if item is None:
                item = dict(row)
                item["chat_ids"] = [str(row.get("chat_id") or "")]
                merged[key] = item
                continue
            chat_id = str(row.get("chat_id") or "")
            if chat_id not in item["chat_ids"]:
                item["chat_ids"].append(chat_id)
            if str(row.get("label") or "") and not item.get("label"):
                item["label"] = row["label"]
            if str(row.get("symbol") or "") and not item.get("symbol"):
                item["symbol"] = row["symbol"]
            for field in ("min_delta_pct", "min_delta_abs", "interval_s"):
                value = row.get(field)
                if field in row and value is not None:
                    if item.get(field) is None:
                        item[field] = value
                    elif field == "interval_s":
                        item[field] = min(item[field], value)
                    else:
                        item[field] = max(item[field], value)
        return list(merged.values())

    def all_whale_watches_merged(self, enabled_only=True):
        """所有聊天订阅的监控地址，按目标合并后的并集。"""
        return self.merge_whale_rows(
            self.get_whale_watches(chat_id=None, enabled_only=enabled_only),
            ("chain", "token", "address"),
        )

    def all_whale_tokens_merged(self, enabled_only=True):
        """所有聊天订阅的代币，按目标合并后的并集。"""
        return self.merge_whale_rows(
            self.get_whale_tokens(chat_id=None, enabled_only=enabled_only),
            ("chain", "token"),
        )

    def mark_whale_watch_tx(
        self,
        chat_id,
        chain,
        token,
        address,
        checked_ms=None,
        last_tx_ms=None,
        error="",
    ):
        """记录成交监控结果。

        last_tx_ms 为 None 时只更新错误信息，不推进游标。
        """
        fields = ["tx_error = ?"]
        params = [str(error or "")]
        if last_tx_ms is not None:
            fields.append("last_tx_ms = ?")
            params.append(int(last_tx_ms or 0))
        params.extend(
            [str(chat_id), str(chain), str(token), str(address)]
        )
        with self._lock:
            self.conn.execute(
                "UPDATE whale_watches SET "
                + ", ".join(fields)
                + " WHERE chat_id = ? AND chain = ? AND token = ? AND address = ?",
                tuple(params),
            )
            self.conn.commit()

    def save_whale_txs(self, chat_id, chain, token, address, rows, ts=None):
        """写入链上成交明细，并保留最近 500 条。"""
        if not rows:
            return
        with self._lock:
            self.conn.executemany(
                "INSERT OR IGNORE INTO whale_txs("
                " chat_id, chain, token, address, tx_hash, ts, direction,"
                " counterparty, value, asset, url) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        str(chat_id),
                        str(chain),
                        str(token),
                        str(address),
                        str(row.get("hash") or ""),
                        int(row.get("time_ms") or 0),
                        str(row.get("direction") or ""),
                        str(row.get("counterparty") or ""),
                        _as_float(row.get("value"), 0.0),
                        str(row.get("asset") or ""),
                        str(row.get("url") or ""),
                    )
                    for row in rows
                    if row.get("hash")
                ],
            )
            self.conn.execute(
                "DELETE FROM whale_txs WHERE rowid NOT IN ("
                " SELECT rowid FROM whale_txs ORDER BY ts DESC LIMIT 500)"
            )
            self.conn.commit()

    def recent_whale_txs(self, chat_id=None, limit=50):
        query = (
            "SELECT chain, token, address, tx_hash, ts, direction,"
            " counterparty, value, asset, url FROM whale_txs"
        )
        params = []
        if chat_id is not None:
            query += " WHERE chat_id = ?"
            params.append(str(chat_id))
        query += " ORDER BY ts DESC LIMIT ?"
        params.append(int(limit))
        with self._lock:
            rows = self.conn.execute(query, params).fetchall()
        return [
            {
                "chain": row[0],
                "token": row[1],
                "address": row[2],
                "hash": row[3],
                "time": int(row[4] or 0),
                "direction": row[5],
                "counterparty": row[6],
                "value": row[7],
                "asset": row[8],
                "url": row[9],
            }
            for row in rows
        ]

    # ------------------------------------------------------------ 应用设置

    def get_app_settings(self):
        """读取全部应用级设置（与聊天无关）。"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT key, value FROM app_settings"
            ).fetchall()
        return {str(key): str(value) for key, value in rows}

    def set_app_settings(self, values, ts=None):
        """写入设置；value 为 None 表示删除该项，回落到默认值。"""
        now_ms = int(ts or 0)
        upserts = []
        deletes = []
        for key, value in (values or {}).items():
            if value is None:
                deletes.append((str(key),))
            else:
                upserts.append((str(key), str(value), now_ms))
        with self._lock:
            if upserts:
                self.conn.executemany(
                    "INSERT INTO app_settings(key, value, updated_ms) VALUES (?,?,?)"
                    " ON CONFLICT(key) DO UPDATE SET"
                    " value = excluded.value, updated_ms = excluded.updated_ms",
                    upserts,
                )
            if deletes:
                self.conn.executemany(
                    "DELETE FROM app_settings WHERE key = ?", deletes
                )
            self.conn.commit()
    # ---------------------------------------------------------------- 链上大户

    WHALE_WATCH_COLUMNS = (
        "chat_id, chain, token, address, symbol, label, decimals, last_balance,"
        " last_checked_ms, last_error, interval_s, min_delta_pct, min_delta_abs,"
        " enabled, created_ms, last_tx_ms, tx_error"
    )

    WHALE_TOKEN_COLUMNS = (
        "chat_id, chain, token, symbol, label, last_top_address, last_top_pct,"
        " last_score, last_scan_ms, last_error, interval_s, enabled, created_ms"
    )

    @staticmethod
    def _whale_watch_row(row):
        return {
            "chat_id": str(row[0]),
            "chain": str(row[1]),
            "token": str(row[2]),
            "address": str(row[3]),
            "symbol": str(row[4] or ""),
            "label": str(row[5] or ""),
            "decimals": row[6],
            "last_balance": row[7],
            "last_checked_ms": int(row[8] or 0),
            "last_error": str(row[9] or ""),
            "interval_s": float(row[10] or 300.0),
            "min_delta_pct": float(row[11] or 0.0),
            "min_delta_abs": float(row[12] or 0.0),
            "enabled": bool(row[13]),
            "created_ms": int(row[14] or 0),
            "last_tx_ms": int(row[15] or 0),
            "tx_error": str(row[16] or ""),
        }

    @staticmethod
    def _whale_token_row(row):
        return {
            "chat_id": str(row[0]),
            "chain": str(row[1]),
            "token": str(row[2]),
            "symbol": str(row[3] or ""),
            "label": str(row[4] or ""),
            "last_top_address": str(row[5] or ""),
            "last_top_pct": row[6],
            "last_score": row[7],
            "last_scan_ms": int(row[8] or 0),
            "last_error": str(row[9] or ""),
            "interval_s": float(row[10] or 21600.0),
            "enabled": bool(row[11]),
            "created_ms": int(row[12] or 0),
        }

    def upsert_whale_watch(self, chat_id, entry, ts=None):
        """新增或更新一个监控地址；重复添加不会清掉已记录的余额基线。"""
        now_ms = int(ts or 0)
        with self._lock:
            self.conn.execute(
                "INSERT INTO whale_watches("
                " chat_id, chain, token, address, symbol, label, decimals,"
                " interval_s, min_delta_pct, min_delta_abs, enabled, created_ms,"
                " last_checked_ms, last_error)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,'')"
                " ON CONFLICT(chat_id, chain, token, address) DO UPDATE SET"
                " symbol = excluded.symbol,"
                " label = excluded.label,"
                " decimals = excluded.decimals,"
                " interval_s = excluded.interval_s,"
                " min_delta_pct = excluded.min_delta_pct,"
                " min_delta_abs = excluded.min_delta_abs,"
                " enabled = excluded.enabled",
                (
                    str(chat_id),
                    str(entry.get("chain") or "").lower(),
                    str(entry.get("token") or ""),
                    str(entry.get("address") or ""),
                    str(entry.get("symbol") or ""),
                    str(entry.get("label") or ""),
                    int(entry["decimals"]) if entry.get("decimals") is not None else None,
                    float(entry.get("interval_s") or 300.0),
                    float(entry.get("min_delta_pct") or 0.0),
                    float(entry.get("min_delta_abs") or 0.0),
                    1 if entry.get("enabled", True) else 0,
                    now_ms,
                ),
            )
            self.conn.commit()

    def remove_whale_watch(self, chat_id, chain, token, address, all_chats=False):
        """删除监控地址；all_chats 时忽略 chat_id，供网页并集操作使用。"""
        with self._lock:
            if all_chats:
                cur = self.conn.execute(
                    "DELETE FROM whale_watches WHERE chain = ? AND token = ?"
                    " AND address = ?",
                    (str(chain), str(token), str(address)),
                )
            else:
                cur = self.conn.execute(
                    "DELETE FROM whale_watches WHERE chat_id = ? AND chain = ?"
                    " AND token = ? AND address = ?",
                    (str(chat_id), str(chain), str(token), str(address)),
                )
            self.conn.commit()
        return cur.rowcount > 0

    def get_whale_watches(self, chat_id=None, enabled_only=True):
        query = f"SELECT {self.WHALE_WATCH_COLUMNS} FROM whale_watches"
        clauses = []
        params = []
        if chat_id is not None:
            clauses.append("chat_id = ?")
            params.append(str(chat_id))
        if enabled_only:
            clauses.append("enabled = 1")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_ms DESC, address ASC"
        with self._lock:
            rows = self.conn.execute(query, params).fetchall()
        return [self._whale_watch_row(row) for row in rows]

    def due_whale_watches(self, now_ms, force=False, chat_id=None):
        query = f"SELECT {self.WHALE_WATCH_COLUMNS} FROM whale_watches WHERE enabled = 1"
        params = []
        if not force:
            query += " AND (last_checked_ms + CAST(interval_s * 1000 AS INTEGER)) <= ?"
            params.append(int(now_ms))
        if chat_id is not None:
            query += " AND chat_id = ?"
            params.append(str(chat_id))
        query += " ORDER BY last_checked_ms ASC"
        with self._lock:
            rows = self.conn.execute(query, params).fetchall()
        return [self._whale_watch_row(row) for row in rows]

    def mark_whale_watch(
        self, chat_id, chain, token, address, checked_ms, balance=None, error=""
    ):
        with self._lock:
            if balance is None:
                self.conn.execute(
                    "UPDATE whale_watches SET last_checked_ms = ?, last_error = ?"
                    " WHERE chat_id = ? AND chain = ? AND token = ? AND address = ?",
                    (
                        int(checked_ms or 0),
                        str(error or ""),
                        str(chat_id),
                        str(chain),
                        str(token),
                        str(address),
                    ),
                )
            else:
                self.conn.execute(
                    "UPDATE whale_watches SET last_checked_ms = ?, last_error = ?,"
                    " last_balance = ? WHERE chat_id = ? AND chain = ?"
                    " AND token = ? AND address = ?",
                    (
                        int(checked_ms or 0),
                        str(error or ""),
                        float(balance),
                        str(chat_id),
                        str(chain),
                        str(token),
                        str(address),
                    ),
                )
            self.conn.commit()

    def upsert_whale_token(self, chat_id, entry, ts=None):
        now_ms = int(ts or 0)
        with self._lock:
            self.conn.execute(
                "INSERT INTO whale_tokens("
                " chat_id, chain, token, symbol, label, interval_s, enabled,"
                " created_ms, last_scan_ms, last_error)"
                " VALUES (?,?,?,?,?,?,?,?,0,'')"
                " ON CONFLICT(chat_id, chain, token) DO UPDATE SET"
                " symbol = excluded.symbol,"
                " label = excluded.label,"
                " interval_s = excluded.interval_s,"
                " enabled = excluded.enabled",
                (
                    str(chat_id),
                    str(entry.get("chain") or "").lower(),
                    str(entry.get("token") or ""),
                    str(entry.get("symbol") or ""),
                    str(entry.get("label") or ""),
                    float(entry.get("interval_s") or 21600.0),
                    1 if entry.get("enabled", True) else 0,
                    now_ms,
                ),
            )
            self.conn.commit()

    def remove_whale_token(self, chat_id, chain, token, all_chats=False):
        """删除订阅代币；all_chats 时忽略 chat_id，供网页并集操作使用。"""
        with self._lock:
            if all_chats:
                cur = self.conn.execute(
                    "DELETE FROM whale_tokens WHERE chain = ? AND token = ?",
                    (str(chain), str(token)),
                )
            else:
                cur = self.conn.execute(
                    "DELETE FROM whale_tokens WHERE chat_id = ? AND chain = ? AND token = ?",
                    (str(chat_id), str(chain), str(token)),
                )
            self.conn.commit()
        return cur.rowcount > 0

    def get_whale_tokens(self, chat_id=None, enabled_only=True):
        query = f"SELECT {self.WHALE_TOKEN_COLUMNS} FROM whale_tokens"
        clauses = []
        params = []
        if chat_id is not None:
            clauses.append("chat_id = ?")
            params.append(str(chat_id))
        if enabled_only:
            clauses.append("enabled = 1")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_ms DESC, token ASC"
        with self._lock:
            rows = self.conn.execute(query, params).fetchall()
        return [self._whale_token_row(row) for row in rows]

    def due_whale_tokens(self, now_ms, force=False, chat_id=None):
        query = f"SELECT {self.WHALE_TOKEN_COLUMNS} FROM whale_tokens WHERE enabled = 1"
        params = []
        if not force:
            query += " AND (last_scan_ms + CAST(interval_s * 1000 AS INTEGER)) <= ?"
            params.append(int(now_ms))
        if chat_id is not None:
            query += " AND chat_id = ?"
            params.append(str(chat_id))
        query += " ORDER BY last_scan_ms ASC"
        with self._lock:
            rows = self.conn.execute(query, params).fetchall()
        return [self._whale_token_row(row) for row in rows]

    def mark_whale_token(
        self,
        chat_id,
        chain,
        token,
        scanned_ms,
        top_address=None,
        top_pct=None,
        score=None,
        error="",
    ):
        with self._lock:
            if top_address is None:
                self.conn.execute(
                    "UPDATE whale_tokens SET last_scan_ms = ?, last_error = ?"
                    " WHERE chat_id = ? AND chain = ? AND token = ?",
                    (
                        int(scanned_ms or 0),
                        str(error or ""),
                        str(chat_id),
                        str(chain),
                        str(token),
                    ),
                )
            else:
                self.conn.execute(
                    "UPDATE whale_tokens SET last_scan_ms = ?, last_error = ?,"
                    " last_top_address = ?, last_top_pct = ?, last_score = ?"
                    " WHERE chat_id = ? AND chain = ? AND token = ?",
                    (
                        int(scanned_ms or 0),
                        str(error or ""),
                        str(top_address),
                        float(top_pct or 0.0),
                        float(score or 0.0),
                        str(chat_id),
                        str(chain),
                        str(token),
                    ),
                )
            self.conn.commit()

    def save_whale_scan(self, report, ts=None):
        payload = json.dumps(report.to_dict(), ensure_ascii=False)
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO whale_scans(chain, token, payload, scanned_ms)"
                " VALUES (?,?,?,?)",
                (
                    str(report.chain),
                    str(report.token),
                    payload,
                    int(ts or report.scanned_ms or 0),
                ),
            )
            self.conn.commit()

    def get_whale_scan(self, chain, token):
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM whale_scans WHERE chain = ? AND token = ?",
                (str(chain), str(token)),
            ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except ValueError:
            return None

    def record_whale_history(self, report, ts=None):
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO whale_scan_history("
                " chain, token, scanned_ms, whale_address, whale_pct, top10_pct, score)"
                " VALUES (?,?,?,?,?,?,?)",
                (
                    str(report.chain),
                    str(report.token),
                    int(ts or report.scanned_ms or 0),
                    str(report.whale_address or ""),
                    float(report.whale_pct or 0.0),
                    float(report.top10_pct or 0.0),
                    float(report.score or 0.0),
                ),
            )
            self.conn.commit()

    def get_whale_history(self, chain, token, limit=10):
        with self._lock:
            rows = self.conn.execute(
                "SELECT scanned_ms, whale_address, whale_pct, top10_pct, score"
                " FROM whale_scan_history WHERE chain = ? AND token = ?"
                " ORDER BY scanned_ms DESC LIMIT ?",
                (str(chain), str(token), int(limit)),
            ).fetchall()
        return [
            {
                "scanned_ms": int(row[0] or 0),
                "whale_address": str(row[1] or ""),
                "whale_pct": row[2],
                "top10_pct": row[3],
                "score": row[4],
            }
            for row in rows
        ]
    def close(self):
        with self._lock:
            self.conn.close()
