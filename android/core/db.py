"""SQLite storage for receipts, products and shopping lists.

Schema and queries are identical to the original desktop app. The only change
is that the storage folder is injectable: on Android we pass the app's writable
``user_data_dir`` (since ``~`` is not writable there), while on desktop it
defaults to ``~/.lidl_receipts`` exactly as before.
"""
import os
import sqlite3
from datetime import datetime


def default_data_dir():
    return os.path.join(os.path.expanduser('~'), '.lidl_receipts')


class DB:
    def __init__(self, folder=None):
        folder = folder or default_data_dir()
        os.makedirs(folder, exist_ok=True)
        self.path = os.path.join(folder, 'receipts.db')
        # check_same_thread=False: Kivy may touch the DB from clock callbacks.
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        c = self.conn.cursor()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY,
            store TEXT, rdate TEXT, trn_id TEXT UNIQUE,
            total REAL, imported_at TEXT
        );
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY,
            receipt_id INTEGER, name TEXT, qty INTEGER,
            unit_price REAL, line_total REAL, vat TEXT,
            FOREIGN KEY(receipt_id) REFERENCES receipts(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS lists (
            id INTEGER PRIMARY KEY, name TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS list_items (
            id INTEGER PRIMARY KEY,
            list_id INTEGER, name TEXT, price REAL,
            qty INTEGER DEFAULT 1, checked INTEGER DEFAULT 0,
            FOREIGN KEY(list_id) REFERENCES lists(id) ON DELETE CASCADE
        );
        """)
        self.conn.commit()

    # ----- receipts -----
    def save_receipt(self, parsed):
        """Returns (status, count). status in {'ok','duplicate','empty'}."""
        if not parsed['items']:
            return ('empty', 0)
        trn = parsed['trn_id']
        if trn:
            existing = self.conn.execute(
                "SELECT id FROM receipts WHERE trn_id=?", (trn,)).fetchone()
            if existing:
                return ('duplicate', 0)
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO receipts (store,rdate,trn_id,total,imported_at) "
            "VALUES (?,?,?,?,?)",
            (parsed['store'], parsed['date'], trn, parsed['total'],
             datetime.now().isoformat(timespec='seconds')))
        rid = cur.lastrowid
        for it in parsed['items']:
            cur.execute(
                "INSERT INTO purchases (receipt_id,name,qty,unit_price,line_total,vat) "
                "VALUES (?,?,?,?,?,?)",
                (rid, it['name'], it['qty'], it['unit_price'],
                 it['line_total'], it['vat']))
        self.conn.commit()
        return ('ok', len(parsed['items']))

    def products(self, search=''):
        q = """
        SELECT name,
               ROUND(AVG(unit_price),2) AS avg_price,
               ROUND(MIN(unit_price),2) AS min_price,
               ROUND(MAX(unit_price),2) AS max_price,
               COUNT(*) AS times,
               MAX(rdate) AS last_seen
        FROM purchases p JOIN receipts r ON p.receipt_id = r.id
        """
        params = ()
        if search:
            q += " WHERE name LIKE ?"
            params = ('%' + search + '%',)
        q += " GROUP BY name ORDER BY name COLLATE NOCASE"
        return self.conn.execute(q, params).fetchall()

    def latest_price(self, name):
        row = self.conn.execute(
            "SELECT unit_price FROM purchases p JOIN receipts r ON p.receipt_id=r.id "
            "WHERE name=? ORDER BY r.rdate DESC, p.id DESC LIMIT 1", (name,)).fetchone()
        return row['unit_price'] if row else 0.0

    def receipt_count(self):
        return self.conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]

    # ----- lists -----
    def lists(self):
        return self.conn.execute(
            "SELECT * FROM lists ORDER BY created_at DESC, id DESC").fetchall()

    def create_list(self, name):
        cur = self.conn.cursor()
        cur.execute("INSERT INTO lists (name,created_at) VALUES (?,?)",
                    (name, datetime.now().isoformat(timespec='seconds')))
        self.conn.commit()
        return cur.lastrowid

    def rename_list(self, list_id, name):
        self.conn.execute("UPDATE lists SET name=? WHERE id=?", (name, list_id))
        self.conn.commit()

    def delete_list(self, list_id):
        self.conn.execute("DELETE FROM list_items WHERE list_id=?", (list_id,))
        self.conn.execute("DELETE FROM lists WHERE id=?", (list_id,))
        self.conn.commit()

    def list_items(self, list_id):
        return self.conn.execute(
            "SELECT * FROM list_items WHERE list_id=? ORDER BY checked, id",
            (list_id,)).fetchall()

    def add_item(self, list_id, name, price, qty=1):
        self.conn.execute(
            "INSERT INTO list_items (list_id,name,price,qty,checked) VALUES (?,?,?,?,0)",
            (list_id, name, price, qty))
        self.conn.commit()

    def set_checked(self, item_id, checked):
        self.conn.execute("UPDATE list_items SET checked=? WHERE id=?",
                          (1 if checked else 0, item_id))
        self.conn.commit()

    def remove_item(self, item_id):
        self.conn.execute("DELETE FROM list_items WHERE id=?", (item_id,))
        self.conn.commit()

    def clear_checked(self, list_id):
        self.conn.execute("DELETE FROM list_items WHERE list_id=? AND checked=1",
                          (list_id,))
        self.conn.commit()
