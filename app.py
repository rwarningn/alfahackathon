"""Local, synthetic hackathon prototype. Run: python app.py."""
import json
import math
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from scoring import assess

ROOT = Path(__file__).parent
DB_PATH = Path(os.environ.get("DB_PATH", ROOT / "data" / "credit.db"))
# Explicit demo identities; fixed passwords are intended only for local synthetic data.
USERS = {"client": ("client-demo", "client", "Руслан · ООО Вектор"),
         "other": ("other-demo", "client", "ООО Другой клиент"),
         "bank": ("bank-demo", "bank", "Егор · Кредитный аналитик")}
SESSIONS = {}
STATUSES = {"submitted", "review", "approved", "declined"}


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS applications (
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, data TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('submitted','review','approved','declined')),
          assessment TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          application_id TEXT NOT NULL REFERENCES applications(id),
          actor TEXT NOT NULL, status TEXT NOT NULL, comment TEXT NOT NULL,
          created_at TEXT NOT NULL);
        """)


def validate(data):
    fields = {"company", "amount", "term_months", "monthly_revenue",
              "monthly_expenses", "existing_payment", "business_months"}
    if set(data) != fields:
        raise ValueError("Передайте только обязательные поля заявки")
    if not isinstance(data["company"], str) or not 2 <= len(data["company"].strip()) <= 120:
        raise ValueError("Название компании: от 2 до 120 символов")
    bounds = {"amount": (50000, 5000000), "term_months": (3, 36),
              "monthly_revenue": (1, 100000000), "monthly_expenses": (0, 100000000),
              "existing_payment": (0, 10000000), "business_months": (1, 1200)}
    for key, (low, high) in bounds.items():
        value = data[key]
        if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
            raise ValueError(f"{key}: допустимый диапазон {low}–{high}")
        if key in ("term_months", "business_months") and int(value) != value:
            raise ValueError(f"{key}: требуется целое число")
    return {**data, "company": data["company"].strip()}


def pack(db, row):
    result = dict(row)
    result["data"] = json.loads(result["data"])
    result["assessment"] = json.loads(result["assessment"])
    result["events"] = [dict(e) for e in db.execute(
        "SELECT actor,status,comment,created_at FROM events WHERE application_id=? ORDER BY id", (row["id"],))]
    return result


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Do not log credentials or submitted financial data.
        super().log_message(fmt, *args)

    def send_json(self, status, payload, cookie=None):
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.headers_common("application/json; charset=utf-8", len(body))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def headers_common(self, content_type, length):
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'")

    def read_json(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size <= 0 or size > 16384:
            raise ValueError("Размер запроса должен быть от 1 до 16384 байт")
        value = json.loads(self.rfile.read(size))
        if not isinstance(value, dict):
            raise ValueError("Ожидается JSON-объект")
        return value

    def identity(self):
        cookies = dict(part.strip().split("=", 1) for part in self.headers.get("Cookie", "").split(";") if "=" in part)
        session = SESSIONS.get(cookies.get("session"))
        if not session:
            return None
        if session[1] < datetime.now(timezone.utc).timestamp():
            return None
        return session[0]

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        try:
            self.route(method)
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json(400, {"error": str(error)})
        except sqlite3.Error:
            self.send_json(503, {"error": "Хранилище временно недоступно"})

    def route(self, method):
        path = urlsplit(self.path).path
        if method == "GET" and path in ("/", "/app.js", "/style.css"):
            name = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}[path]
            body = (ROOT / "web" / name).read_bytes()
            self.send_response(200)
            self.headers_common({"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8", "style.css": "text/css; charset=utf-8"}[name], len(body))
            self.end_headers()
            self.wfile.write(body)
            return
        if method == "GET" and path == "/api/health":
            with connect() as db:
                db.execute("SELECT 1 FROM applications LIMIT 1")
            return self.send_json(200, {"status": "ok"})
        if method == "POST":
            # Browser mutations must come from this origin. Non-browser API clients may omit Origin.
            origin = self.headers.get("Origin")
            if origin and origin not in (f"http://{self.headers.get('Host')}", f"https://{self.headers.get('Host')}"):
                return self.send_json(403, {"error": "Недопустимый источник запроса"})
        if method == "POST" and path == "/api/login":
            data = self.read_json()
            username = data.get("username")
            user = USERS.get(username) if isinstance(username, str) else None
            if not user or data.get("password") != user[0]:
                return self.send_json(401, {"error": "Неверный логин или пароль"})
            token = secrets.token_urlsafe(32)
            SESSIONS[token] = (username, datetime.now(timezone.utc).timestamp() + 28800)
            return self.send_json(200, {"role": user[1], "name": user[2]}, f"session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=28800")
        username = self.identity()
        if not username:
            return self.send_json(401, {"error": "Войдите в демо-кабинет"})
        role = USERS[username][1]
        if method == "POST" and path == "/api/logout":
            for token, session in list(SESSIONS.items()):
                if session[0] == username:
                    del SESSIONS[token]
            return self.send_json(200, {"ok": True}, "session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0")
        if method == "GET" and path == "/api/me":
            return self.send_json(200, {"role": role, "name": USERS[username][2]})
        if method == "GET" and path == "/api/applications":
            with connect() as db:
                rows = db.execute("SELECT * FROM applications ORDER BY created_at DESC") if role == "bank" else db.execute("SELECT * FROM applications WHERE owner=? ORDER BY created_at DESC", (username,))
                return self.send_json(200, [pack(db, row) for row in rows.fetchall()])
        if method == "POST" and path == "/api/applications":
            if role != "client":
                return self.send_json(403, {"error": "Заявку создаёт клиент"})
            data = validate(self.read_json())
            assessment = assess(data)
            app_id = secrets.token_hex(6)
            timestamp = now()
            with connect() as db:
                db.execute("INSERT INTO applications VALUES (?,?,?,?,?,?)", (app_id, username, json.dumps(data), "submitted", json.dumps(assessment), timestamp))
                db.execute("INSERT INTO events(application_id,actor,status,comment,created_at) VALUES (?,?,?,?,?)", (app_id, username, "submitted", "Заявка принята. Ожидает проверки аналитиком", timestamp))
                result = pack(db, db.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone())
            return self.send_json(201, result)
        if method == "POST" and path.startswith("/api/applications/") and path.endswith("/transition"):
            if role != "bank":
                return self.send_json(403, {"error": "Статус меняет только аналитик банка"})
            app_id = path.split("/")[3]
            data = self.read_json()
            target, comment = data.get("status"), data.get("comment", "")
            if not isinstance(target, str) or target not in STATUSES or not isinstance(comment, str) or not 5 <= len(comment.strip()) <= 1000:
                raise ValueError("Укажите статус и комментарий от 5 до 1000 символов")
            allowed = {"submitted": {"review"}, "review": {"approved", "declined"}}
            with connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
                if not row:
                    return self.send_json(404, {"error": "Заявка не найдена"})
                if target not in allowed.get(row["status"], set()):
                    return self.send_json(409, {"error": "Недопустимый переход состояния"})
                db.execute("UPDATE applications SET status=? WHERE id=?", (target, app_id))
                db.execute("INSERT INTO events(application_id,actor,status,comment,created_at) VALUES (?,?,?,?,?)", (app_id, username, target, comment.strip(), now()))
                result = pack(db, db.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone())
            return self.send_json(200, result)
        self.send_json(404, {"error": "Маршрут не найден"})


if __name__ == "__main__":
    init_db()
    print("Demo credit cabinet: http://localhost:" + os.environ.get("PORT", "8000"), flush=True)
    ThreadingHTTPServer((os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8000"))), Handler).serve_forever()
