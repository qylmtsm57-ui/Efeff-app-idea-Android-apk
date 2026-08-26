import csv
import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path


def app_data_dir() -> Path:
    p = os.getenv("FLET_APP_STORAGE_DATA")
    if p:
        path = Path(p)
    else:
        path = Path(__file__).resolve().parent / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


class Database:
    def __init__(self):
        self.path = app_data_dir() / "freshstock.db"
        self.con = sqlite3.connect(self.path, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        cur = self.con.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                barcode TEXT DEFAULT '',
                category TEXT DEFAULT '',
                quantity REAL DEFAULT 0,
                unit TEXT DEFAULT 'قطعة',
                production_date TEXT DEFAULT '',
                expiry_date TEXT DEFAULT '',
                minimum_quantity REAL DEFAULT 0,
                price REAL DEFAULT 0,
                notes TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self.con.commit()
        defaults = {
            "onboarding_done": "0",
            "notifications": "1",
            "low_stock": "1",
            "expiry_alerts": "1",
            "expiry_days": "7",
            "dark_mode": "0",
            "language": "ar",
            "alert_time": "09:00",
        }
        for k, v in defaults.items():
            cur.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        self.con.commit()

    def get_setting(self, key, default=None):
        row = self.con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key, value):
        self.con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, str(value)))
        self.con.commit()

    def onboarding_done(self):
        return self.get_setting("onboarding_done", "0") == "1"

    def set_onboarding_done(self, value=True):
        self.set_setting("onboarding_done", "1" if value else "0")

    def add_product(self, data):
        cols = ["name", "barcode", "category", "quantity", "unit", "production_date", "expiry_date", "minimum_quantity", "price", "notes"]
        vals = [data.get(c, "") for c in cols]
        cur = self.con.execute(
            f"INSERT INTO products ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})", vals
        )
        self.con.commit()
        return cur.lastrowid

    def update_product(self, product_id, data):
        cols = ["name", "barcode", "category", "quantity", "unit", "production_date", "expiry_date", "minimum_quantity", "price", "notes"]
        self.con.execute(
            f"UPDATE products SET {','.join(c+'=?' for c in cols)}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            [data.get(c, "") for c in cols] + [product_id],
        )
        self.con.commit()

    def delete_product(self, product_id):
        self.con.execute("DELETE FROM products WHERE id=?", (product_id,))
        self.con.commit()

    def get_product(self, product_id):
        row = self.con.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        return dict(row) if row else None

    def all_products(self):
        return [dict(r) for r in self.con.execute("SELECT * FROM products ORDER BY CASE WHEN expiry_date='' THEN 1 ELSE 0 END, expiry_date ASC, name ASC").fetchall()]

    def counts(self):
        products = self.all_products()
        total = len(products)
        expired = 0
        soon = 0
        low = 0
        today = date.today()
        days = int(self.get_setting("expiry_days", "7"))
        for p in products:
            st = expiry_status(p.get("expiry_date", ""), days)
            if st == "expired": expired += 1
            elif st == "soon": soon += 1
            try:
                if float(p.get("quantity") or 0) <= float(p.get("minimum_quantity") or 0): low += 1
            except ValueError:
                pass
        return {"total": total, "expired": expired, "soon": soon, "low": low, "safe": max(total - expired - soon, 0)}

    def export_csv(self):
        products = self.all_products()
        path = app_data_dir() / f"freshstock_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        fields = ["id", "name", "barcode", "category", "quantity", "unit", "production_date", "expiry_date", "minimum_quantity", "price", "notes"]
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows({k: p.get(k, "") for k in fields} for p in products)
        return path

    def backup_json(self):
        path = app_data_dir() / f"freshstock_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        payload = {"version": 1, "created_at": datetime.now().isoformat(), "products": self.all_products(), "settings": self.all_settings()}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def all_settings(self):
        return {r["key"]: r["value"] for r in self.con.execute("SELECT key,value FROM settings")}

    def restore_json(self, raw: bytes):
        payload = json.loads(raw.decode("utf-8"))
        products = payload.get("products", [])
        settings = payload.get("settings", {})
        cur = self.con.cursor()
        cur.execute("DELETE FROM products")
        for p in products:
            data = {k: p.get(k, "") for k in ["name","barcode","category","quantity","unit","production_date","expiry_date","minimum_quantity","price","notes"]}
            self.add_product(data)
        for k, v in settings.items():
            self.set_setting(k, v)
        self.con.commit()


def parse_date(value: str):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            pass
    return None


def expiry_status(expiry_date: str, soon_days=7):
    d = parse_date(expiry_date)
    if not d:
        return "unknown"
    delta = (d - date.today()).days
    if delta < 0:
        return "expired"
    if delta <= soon_days:
        return "soon"
    return "safe"


def days_left(expiry_date: str):
    d = parse_date(expiry_date)
    return None if not d else (d - date.today()).days
