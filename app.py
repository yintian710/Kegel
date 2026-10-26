from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from http import cookies
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import credits
import catalog
import donations
import practice

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"


def load_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not key.isidentifier():
            raise ValueError(f".env 第 {number} 行格式错误")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f".env 第 {number} 行引号未闭合")
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        os.environ.setdefault(key, value)


load_env()
DB_PATH = Path(os.environ.get("CHECKIN_DB", str(ROOT / "checkin.db")))
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
APP_BASE_URL = os.environ.get("APP_BASE_URL", f"http://localhost:{PORT}").rstrip("/")
APP_SECRET = (os.environ.get("APP_SECRET") or secrets.token_urlsafe(48)).encode()
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
TRIGGER_TOKEN = os.environ.get("CHECKIN_TRIGGER_TOKEN", "")
SITE_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_SETTINGS = {
    "deadline": "22:00", "min_step_seconds": 8,
    "daily_points_limit": 800,
    "reward_tiers": [{"through": 10, "amount": 1000},
                     {"through": 20, "amount": 500},
                     {"through": 50, "amount": 100}],
    "condition_url": "",
}


class APIError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@contextmanager
def db():
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_db() -> None:
    with db() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(entries)")}
        if "payout_status" in columns:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("ALTER TABLE entries RENAME TO legacy_ldc_entries")
            connection.execute("DELETE FROM sessions")
            previous = connection.execute("SELECT value FROM checkin_settings WHERE key='reward_tiers'").fetchone()
            if previous:
                tiers = [{"through": item["through"], "amount": credits.parse_points(int(Decimal(str(item["amount"])) * 1000))}
                         for item in json.loads(previous["value"])]
                connection.execute("UPDATE checkin_settings SET value=? WHERE key='reward_tiers'", (json.dumps(tiers),))
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS checkin_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS days (
                day TEXT PRIMARY KEY, opened_at REAL, open_reason TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS visits (
                id INTEGER PRIMARY KEY, day TEXT NOT NULL, subject TEXT NOT NULL,
                username TEXT NOT NULL, visitor TEXT NOT NULL, ip_hash TEXT NOT NULL,
                kind TEXT NOT NULL, created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS visits_subject_time ON visits(subject, created_at);
            CREATE INDEX IF NOT EXISTS visits_day ON visits(day);
            CREATE TABLE IF NOT EXISTS reviews (
                day TEXT NOT NULL, user_id TEXT NOT NULL, reason TEXT NOT NULL,
                approved INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(day, user_id)
            );
            CREATE TABLE IF NOT EXISTS sessions (
                day TEXT NOT NULL, user_id TEXT NOT NULL, token TEXT NOT NULL,
                step INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL,
                expires_at REAL NOT NULL, min_seconds INTEGER NOT NULL,
                PRIMARY KEY(day, user_id)
            );
            CREATE TABLE IF NOT EXISTS entries (
                day TEXT NOT NULL, user_id TEXT NOT NULL, username TEXT NOT NULL,
                rank INTEGER NOT NULL, amount INTEGER NOT NULL CHECK(amount >= 0),
                completed_at REAL NOT NULL, claimed_at REAL,
                reward_status TEXT NOT NULL CHECK(reward_status IN ('unclaimed','credited','none')),
                PRIMARY KEY(day,user_id), UNIQUE(day,rank)
            );
        """)
        credits.init_schema(connection)
        practice.init_schema(connection)
        catalog.init_schema(connection)
        donations.init_schema(connection)


def day_key(now: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if now is None else now, SITE_TZ).date().isoformat()


def iso_time(stamp: float | None) -> str | None:
    return datetime.fromtimestamp(stamp, SITE_TZ).isoformat(timespec="seconds") if stamp is not None else None


def settings(connection) -> dict[str, Any]:
    values = dict(DEFAULT_SETTINGS)
    values.update({row["key"]: json.loads(row["value"])
                   for row in connection.execute("SELECT key,value FROM checkin_settings")})
    return values


def validate_settings(body: dict[str, Any]) -> dict[str, Any]:
    if set(body) - set(DEFAULT_SETTINGS):
        raise APIError("包含不支持的配置项")
    result = {}
    if "deadline" in body:
        value = body["deadline"]
        try:
            parsed = datetime.strptime(value, "%H:%M")
        except (ValueError, TypeError):
            raise APIError("最晚开启时间需为 HH:MM") from None
        if parsed.strftime("%H:%M") != value:
            raise APIError("最晚开启时间需为 HH:MM")
        result["deadline"] = value
    if "min_step_seconds" in body:
        value = body["min_step_seconds"]
        if type(value) is not int or not 1 <= value <= 300:
            raise APIError("每组最短时长需为 1–300 秒整数")
        result["min_step_seconds"] = value
    if "daily_points_limit" in body:
        value = body["daily_points_limit"]
        if type(value) is not int or not 0 <= value <= 100_000_000:
            raise APIError("每日全站积分额度须为 0–100000000 的整数")
        result["daily_points_limit"] = value
    if "reward_tiers" in body:
        tiers = body["reward_tiers"]
        if not isinstance(tiers, list) or not 1 <= len(tiers) <= 20:
            raise APIError("奖励需配置 1–20 个连续档位")
        previous = 0
        normalized = []
        for tier in tiers:
            if not isinstance(tier, dict):
                raise APIError("奖励档位格式错误")
            through = tier.get("through")
            try:
                amount = credits.parse_points(tier.get("amount"))
            except ValueError as exc:
                raise APIError(str(exc)) from None
            if type(through) is not int or not previous < through <= 100000:
                raise APIError("档位截止名次须为递增的整数")
            normalized.append({"through": through, "amount": amount})
            previous = through
        result["reward_tiers"] = normalized
    if "condition_url" in body:
        value = body["condition_url"]
        if not isinstance(value, str) or len(value) > 2048:
            raise APIError("条件 API 地址格式错误")
        parsed = urllib.parse.urlsplit(value)
        if value and (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password):
            raise APIError("条件 API 必须是 HTTP(S) 地址，认证密钥请配置环境变量")
        result["condition_url"] = value
    return result


def ensure_day(connection, now: float) -> sqlite3.Row:
    today = day_key(now)
    connection.execute("INSERT OR IGNORE INTO days(day) VALUES (?)", (today,))
    deadline = settings(connection)["deadline"]
    if datetime.fromtimestamp(now, SITE_TZ).strftime("%H:%M") >= deadline:
        connection.execute("UPDATE days SET opened_at=?,open_reason='deadline' WHERE day=? AND opened_at IS NULL", (now, today))
    return connection.execute("SELECT * FROM days WHERE day=?", (today,)).fetchone()


def open_today(reason: str) -> None:
    with db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        now = time.time()
        today = ensure_day(connection, now)["day"]
        connection.execute("UPDATE days SET opened_at=?,open_reason=? WHERE day=? AND opened_at IS NULL", (now, reason, today))


def json_request(url: str, *, method: str = "GET", data=None, headers=None, form=False, timeout=10) -> dict:
    request_headers = dict(headers or {})
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
        request_headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read(1_000_001))
    if not isinstance(result, dict):
        raise ValueError("远端响应不是 JSON 对象")
    return result


def b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def sign_payload(payload: dict) -> str:
    body = b64encode(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{b64encode(hmac.new(APP_SECRET, body.encode(), hashlib.sha256).digest())}"


def verify_payload(token: str) -> dict | None:
    try:
        body, signature = token.split(".", 1)
        expected = b64encode(hmac.new(APP_SECRET, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if not isinstance(payload, dict) or payload.get("exp", 0) <= time.time():
            return None
        return payload
    except (ValueError, TypeError, UnicodeError):
        return None


def session_view(row, now: float) -> dict | None:
    return practice.view(row, now)


def entry_view(row) -> dict | None:
    if row is None:
        return None
    result = dict(row)
    result["completed_at"] = iso_time(row["completed_at"])
    result["claimed_at"] = iso_time(row["claimed_at"])
    return result


def check_review(connection, subject: str, today: str) -> None:
    row = connection.execute("SELECT * FROM reviews WHERE day=? AND user_id=?", (today, subject)).fetchone()
    if row and not row["approved"]:
        raise APIError(f"访问规律异常，等待管理员审核：{row['reason']}", 403)


def record_visit(connection, subject: str, username: str, visitor: str, ip: str, kind: str, now: float) -> None:
    today = day_key(now)
    ip_hash = hmac.new(APP_SECRET, ip.encode(), hashlib.sha256).hexdigest()[:24]
    connection.execute("INSERT INTO visits(day,subject,username,visitor,ip_hash,kind,created_at) VALUES (?,?,?,?,?,?,?)",
                       (today, subject, username, visitor, ip_hash, kind, now))
    recent_count = connection.execute("SELECT COUNT(*) FROM visits WHERE subject=? AND created_at>?", (subject, now - 600)).fetchone()[0]
    rows = connection.execute("SELECT created_at FROM visits WHERE subject=? AND kind=? ORDER BY id DESC LIMIT 6", (subject, kind)).fetchall()
    reason = ""
    if recent_count >= 20:
        reason = "10 分钟内访问或启动次数达到 20 次"
    elif len(rows) == 6:
        intervals = [rows[i][0] - rows[i + 1][0] for i in range(5)]
        mean = sum(intervals) / 5
        if 30 <= mean <= 172800 and max(intervals) - min(intervals) <= max(2, mean * .02):
            reason = "连续 6 次访问呈固定周期"
    if reason:
        connection.execute("INSERT INTO reviews(day,user_id,reason) VALUES (?,?,?) ON CONFLICT(day,user_id) DO UPDATE SET reason=excluded.reason", (today, subject, reason))


def quota_view(connection, today: str, limit: int | None = None) -> dict[str, int]:
    if limit is None:
        limit = settings(connection)["daily_points_limit"]
    used = connection.execute("SELECT COALESCE(SUM(amount),0) FROM entries WHERE day=? AND reward_status='credited'", (today,)).fetchone()[0]
    return {"limit": limit, "used": used, "remaining": max(0, limit - used)}


def status_view(connection, user: dict | None, now: float, subject: str = "") -> dict:
    day = ensure_day(connection, now)
    config = settings(connection)
    identity = user["id"] if user else subject
    entry = connection.execute("SELECT * FROM entries WHERE day=? AND user_id=?", (day["day"], identity)).fetchone()
    if entry and entry["reward_status"] == "unclaimed" and not entry["flow_id"]:
        entry = None
    session = connection.execute("SELECT * FROM sessions WHERE day=? AND user_id=?", (day["day"], identity)).fetchone()
    review = connection.execute("SELECT reason,approved FROM reviews WHERE day=? AND user_id=? AND approved=0", (day["day"], identity)).fetchone()
    if session and not session["eligible"] and user and day["opened_at"] is not None and not review:
        session = None
    return {"ok": True, "user": user, "day": day["day"], "is_open": day["opened_at"] is not None,
            "opened_at": iso_time(day["opened_at"]), "open_reason": day["open_reason"],
            "deadline": config["deadline"], "timezone": "Asia/Shanghai", "min_step_seconds": config["min_step_seconds"],
            "reward_tiers": config["reward_tiers"], "wallet": credits.wallet_view(connection, identity) if user else None,
            "quota": quota_view(connection, day["day"], config["daily_points_limit"]),
            "oauth_ready": bool(os.environ.get("LINUXDO_CLIENT_ID") and os.environ.get("LINUXDO_CLIENT_SECRET")),
            "total": connection.execute("SELECT COUNT(*) FROM entries WHERE day=?", (day["day"],)).fetchone()[0],
            "entry": entry_view(entry), "session": session_view(session, now), "review": dict(review) if review else None,
            "leaderboard": [dict(row) for row in connection.execute("SELECT rank,username,amount,reward_status FROM entries WHERE day=? ORDER BY rank LIMIT 50", (day["day"],))]}

def dispatch_ldc(order_no: str, user: dict, amount: str) -> tuple[str, str, str]:
    """Auto delivers LDC to user using Linux DO Credit /lpay/distribute."""
    client_id = os.environ.get("LDC_CLIENT_ID", "").strip()
    client_secret = os.environ.get("LDC_CLIENT_SECRET", "").strip()
    api_base = os.environ.get("LDC_API_BASE", "https://credit.linux.do").rstrip("/")
    live = os.environ.get("LDC_LIVE", "false").lower() == "true" or os.environ.get("LDC_AUTO_DISPATCH", "false").lower() == "true"

    if not live or not client_id or not client_secret:
        return ("simulated", f"SIM-{secrets.token_hex(6).upper()}", "")

    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    try:
        response = json_request(
            f"{api_base}/lpay/distribute",
            method="POST",
            headers={"Authorization": f"Basic {auth}"},
            data={
                "user_id": int(user["id"]),
                "username": user["username"],
                "amount": amount,
                "out_trade_no": order_no,
                "remark": f"积分兑换 {order_no}"
            },
            timeout=10
        )
        if response.get("code") == 1:
            trade_no = str((response.get("data") or {}).get("trade_no") or "")
            if not trade_no:
                return ("uncertain", "", "分发成功但缺少交易单号，需核对")
            return ("success", trade_no, "")
        else:
            err = str(response.get("error_msg") or response.get("msg") or "LDC 平台拒绝分发")
            return ("failed", "", err)
    except Exception as exc:
        return ("uncertain", "", f"请求超时或网络异常: {type(exc).__name__}")





class CheckinServer(ThreadingHTTPServer):
    request_queue_size = 128


class AppHandler(SimpleHTTPRequestHandler):
    server_version = "Checkin/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def json_response(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if getattr(self, "new_visitor", None):
            self.send_header("Set-Cookie", self.cookie("checkin_visitor", self.new_visitor, 31536000))
        self.end_headers()
        self.wfile.write(body)

    def cookie(self, key, value, age):
        secure = "; Secure" if APP_BASE_URL.startswith("https://") else ""
        return f"{key}={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={age}{secure}"

    def cookie_values(self):
        jar = cookies.SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except cookies.CookieError:
            return {}
        return {key: value.value for key, value in jar.items()}

    def current_user(self):
        payload = verify_payload(self.cookie_values().get("linuxdo_session", ""))
        if not payload or payload.get("purpose") != "session" or not str(payload.get("id", "")).isdigit() or not payload.get("username"):
            return None
        return {"id": str(payload["id"]), "username": payload["username"], "name": payload.get("name") or payload["username"]}

    def require_user(self):
        user = self.current_user()
        if not user:
            raise APIError("请先使用 LINUX DO 登录", 401)
        return user

    def require_admin(self):
        if not ADMIN_TOKEN or not hmac.compare_digest(self.headers.get("X-Admin-Token", ""), ADMIN_TOKEN):
            raise APIError("管理员口令未配置或不正确", 401)

    def visitor_id(self):
        if getattr(self, "visitor", None):
            return self.visitor
        payload = verify_payload(self.cookie_values().get("checkin_visitor", ""))
        visitor = payload.get("visitor") if payload and payload.get("purpose") == "visitor" else None
        if not visitor:
            visitor = secrets.token_urlsafe(18)
            self.new_visitor = sign_payload({"purpose": "visitor", "visitor": visitor, "exp": time.time() + 31536000})
        self.visitor = visitor
        return visitor

    def practice_identity(self):
        user = self.current_user()
        return user or {"id": f"anon:{self.visitor_id()}", "username": "匿名访客"}

    def record(self, connection, user, kind, now):
        visitor = self.visitor_id()
        subject = user["id"] if user else f"anon:{visitor}"
        record_visit(connection, subject, user["username"] if user else "匿名访客", visitor, self.client_address[0], kind, now)

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        try:
            if parsed.path == "/api/status":
                with db() as connection:
                    result = status_view(connection, self.current_user(), time.time(), self.practice_identity()["id"])
                self.json_response(result)
            elif parsed.path == "/api/shop":
                user = self.current_user()
                with db() as connection:
                    result = {"ok": True, "user": user,
                              "oauth_ready": bool(os.environ.get("LINUXDO_CLIENT_ID") and os.environ.get("LINUXDO_CLIENT_SECRET")),
                              "wallet": credits.wallet_view(connection, user["id"]) if user else None,
                              "quota": quota_view(connection, day_key()),
                              "ledger": credits.ledger_view(connection, user["id"], SITE_TZ) if user else [],
                              "products": catalog.list_products(connection, user_id=user["id"] if user else None, today=day_key()),
                              "purchases": catalog.user_purchases(connection, user["id"], SITE_TZ) if user else []}
                self.json_response(result)
            elif parsed.path == "/api/donations":
                user = self.current_user()
                with db() as connection:
                    result = {"ok": True, "user": user,
                              "oauth_ready": bool(os.environ.get("LINUXDO_CLIENT_ID") and os.environ.get("LINUXDO_CLIENT_SECRET"))}
                    result.update(donations.shop_data(connection, user, APP_BASE_URL))
                self.json_response(result)
            elif parsed.path == "/api/admin":
                self.require_admin()
                with db() as connection:
                    state = status_view(connection, self.current_user(), time.time())
                    visits = [dict(row) for row in connection.execute("""
                        SELECT v.subject AS user_id, MAX(v.username) AS username, COUNT(*) AS count,
                               MAX(v.created_at) AS last_seen, COALESCE(r.reason,'') AS reason,
                               COALESCE(r.approved,0) AS approved
                        FROM visits v LEFT JOIN reviews r ON r.day=v.day AND r.user_id=v.subject
                        WHERE v.day=? GROUP BY v.subject ORDER BY last_seen DESC LIMIT 200
                    """, (state["day"],))]
                    for item in visits:
                        item["last_seen"] = iso_time(item["last_seen"])
                    rewards = [entry_view(row) for row in connection.execute("SELECT * FROM entries ORDER BY day DESC,rank LIMIT 500")]
                    wallets = [dict(row) for row in connection.execute("SELECT user_id,username,balance FROM points_wallets ORDER BY balance DESC,user_id LIMIT 500")]
                    triggers = [dict(row) for row in connection.execute("SELECT day,user_id,username,group_no,created_at,flow_id FROM practice_triggers ORDER BY id DESC LIMIT 200")]
                    products = catalog.list_products(connection, today=state["day"], include_inactive=True)
                    purchases = catalog.all_purchases(connection, SITE_TZ)
                    result = {"ok": True, "settings": settings(connection), "status": state, "visits": visits, "rewards": rewards, "wallets": wallets, "practice_triggers": triggers, "products": products, "purchases": purchases}
                self.json_response(result)
            elif parsed.path == "/payments/ldc/notify":
                try:
                    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True, max_num_fields=30)
                    if any(len(values) != 1 for values in query.values()):
                        raise ValueError("重复的通知字段")
                    with db() as connection:
                        connection.execute("BEGIN IMMEDIATE")
                        donations.accept_notification(connection, {key: values[0] for key, values in query.items()}, time.time())
                    body, status = b"success", 200
                except ValueError:
                    body, status = b"fail", 400
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif parsed.path == "/auth/linuxdo/start":
                self.start_oauth()
            elif parsed.path == "/auth/linuxdo/callback":
                self.finish_oauth(parsed)
            elif parsed.path == "/auth/logout":
                self.send_response(303)
                self.send_header("Set-Cookie", self.cookie("linuxdo_session", "", 0))
                self.send_header("Location", "/")
                self.end_headers()
            elif parsed.path in {"/", "/admin", "/shop", "/donate", "/index.html", "/admin.html", "/shop.html", "/donate.html", "/app.js", "/admin.js", "/shop.js", "/donate.js", "/styles.css", "/favicon.svg"}:
                self.path = {"/": "/index.html", "/admin": "/admin.html", "/shop": "/shop.html", "/donate": "/donate.html"}.get(parsed.path, parsed.path)
                super().do_GET()
            else:
                raise APIError("页面或接口不存在", 404)
        except APIError as exc:
            self.json_response({"ok": False, "error": str(exc)}, exc.status)
        except (urllib.error.URLError, ValueError, KeyError) as exc:
            self.log_error("GET failed: %s", exc)
            self.json_response({"ok": False, "error": "认证服务暂不可用，请重新登录"}, 502)

    def do_POST(self):
        try:
            origin = self.headers.get("Origin")
            if origin and origin != APP_BASE_URL:
                raise APIError("请求来源不匹配", 403)
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 65536:
                raise APIError("请求体过大", 413)
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise APIError("请求体需为 JSON 对象")
            self.post_route(urllib.parse.urlsplit(self.path).path, body)
        except (APIError, practice.PracticeError) as exc:
            self.json_response({"ok": False, "error": str(exc)}, exc.status)
        except (ValueError, TypeError):
            self.json_response({"ok": False, "error": "请求数据格式错误"}, 400)
        except Exception as exc:
            self.log_error("POST failed: %s", exc)
            self.json_response({"ok": False, "error": "服务暂不可用，请稍后查看状态"}, 500)

    def post_route(self, path, body):
        if path == "/api/visit":
            user = self.current_user()
            with db() as connection:
                now = time.time()
                self.record(connection, user, "visit", now)
                result = status_view(connection, user, now, self.practice_identity()["id"])
            self.json_response(result)
        elif path == "/api/trigger/open":
            if not TRIGGER_TOKEN or not hmac.compare_digest(self.headers.get("X-Trigger-Token", ""), TRIGGER_TOKEN):
                raise APIError("触发密钥未配置或不正确", 401)
            open_today("trigger")
            self.json_response({"ok": True})
        elif path == "/api/admin/products":
            self.require_admin()
            with db() as connection:
                product = catalog.save(connection, body)
            self.json_response({"ok": True, "product": product})
        elif path.startswith("/api/admin/products/") and path.endswith("/archive"):
            self.require_admin()
            product_id = int(path.removeprefix("/api/admin/products/").removesuffix("/archive").strip("/"))
            with db() as connection:
                catalog.archive(connection, product_id)
            self.json_response({"ok": True})
        elif path.startswith("/api/admin/"):
            self.require_admin()
            self.admin_action(path, body)
        elif path == "/api/session/start":
            self.start_session()
        elif path == "/api/session/step":
            self.advance_session(body)
        elif path == "/api/session/complete":
            self.complete_session(body)
        elif path == "/api/donations/create":
            user = self.require_user()
            with db() as connection:
                connection.execute("BEGIN IMMEDIATE")
                result = donations.create_order(connection, user, body.get("amount"), APP_BASE_URL, time.time())
            self.json_response({"ok": True, **result})
        elif path == "/api/shop/purchase":
            user = self.require_user()
            try:
                product_id = int(body.get("product_id"))
            except (TypeError, ValueError):
                raise APIError("请选择有效的兑换商品")
            try:
                with db() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    result = catalog.purchase_product(connection, user, product_id, day_key(), time.time(), dispatch_ldc)
            except ValueError as exc:
                raise APIError(str(exc), 400) from None
            self.json_response({"ok": True, **result})
        elif path == "/api/claim":
            self.claim()
        else:
            raise APIError("接口不存在", 404)

    def record_practice_attempt(self):
        user = self.current_user()
        with db() as connection:
            self.record(connection, user, "trigger", time.time())

    def start_session(self):
        self.record_practice_attempt()
        user = self.current_user()
        identity = self.practice_identity()
        with db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = time.time()
            day = ensure_day(connection, now)
            review = connection.execute("SELECT 1 FROM reviews WHERE day=? AND user_id=? AND approved=0", (day["day"], identity["id"])).fetchone()
            eligible = bool(user and day["opened_at"] is not None and not review)
            row = practice.start(connection, identity, day["day"], eligible, settings(connection)["min_step_seconds"], now)
            result = session_view(row, now)
        self.json_response({"ok": True, "session": result})

    def advance_session(self, body):
        self.record_practice_attempt()
        token = body.get("token")
        if not isinstance(token, str):
            raise APIError("缺少练习凭证")
        identity = self.practice_identity()
        with db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = time.time()
            row = practice.advance(connection, identity, day_key(now), token, now)
            result = session_view(row, now)
        self.json_response({"ok": True, "session": result})

    def complete_session(self, body):
        token = body.get("token")
        if not isinstance(token, str):
            raise APIError("缺少练习凭证")
        user = self.current_user()
        identity = self.practice_identity()
        with db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = time.time()
            today = day_key(now)
            row = practice.complete(connection, identity["id"], today, token, now)
            entry = None
            if row["eligible"] and user:
                check_review(connection, user["id"], today)
                rank = connection.execute("SELECT COUNT(*)+1 FROM entries WHERE day=?", (today,)).fetchone()[0]
                amount = next((tier["amount"] for tier in settings(connection)["reward_tiers"] if rank <= tier["through"]), 0)
                connection.execute("""INSERT INTO entries(day,user_id,username,rank,amount,completed_at,reward_status,flow_id)
                    VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(day,user_id) DO UPDATE SET
                    flow_id=excluded.flow_id,completed_at=excluded.completed_at
                    WHERE entries.reward_status='unclaimed' AND entries.flow_id IS NULL""",
                    (today, user["id"], user["username"], rank, amount, now, "unclaimed" if amount > 0 else "none", row["flow_id"]))
                entry = connection.execute("SELECT * FROM entries WHERE day=? AND user_id=?", (today, user["id"])).fetchone()
            result = {"ok": True, "session": session_view(row, now), "entry": entry_view(entry)}
        self.json_response(result)

    def claim(self):
        user = self.require_user()
        with db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = time.time()
            today = day_key(now)
            check_review(connection, user["id"], today)
            row = connection.execute("SELECT * FROM entries WHERE day=? AND user_id=?", (today, user["id"])).fetchone()
            if not row:
                raise APIError("请先完成三组打卡", 409)
            if row["reward_status"] == "unclaimed":
                practice.verify(connection, row["flow_id"], user["id"], today, row["completed_at"])
                quota = quota_view(connection, today)
                if quota["remaining"] == 0:
                    raise APIError("今日全站积分额度已用完，当天不能再领取", 409)
                if row["amount"] > quota["remaining"]:
                    raise APIError(f"今日额度不足：剩余 {quota['remaining']} 分，本次奖励 {row['amount']} 分；不支持拆分领取", 409)
                credits.credit_checkin(connection, user, row["amount"], f"{today}:{user['id']}", now)
                connection.execute("UPDATE entries SET reward_status='credited',claimed_at=? WHERE day=? AND user_id=?", (now, today, user["id"]))
            row = connection.execute("SELECT * FROM entries WHERE day=? AND user_id=?", (today, user["id"])).fetchone()
            result = {"ok": True, "entry": entry_view(row), "wallet": credits.wallet_view(connection, user["id"]), "quota": quota_view(connection, today)}
        self.json_response(result)

    def admin_action(self, path, body):
        if path == "/api/admin/open":
            open_today("manual")
        elif path == "/api/admin/settings":
            values = validate_settings(body)
            with db() as connection:
                for key, value in values.items():
                    connection.execute("INSERT INTO checkin_settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))
        elif path == "/api/admin/review":
            if body.get("approved") is not True or not isinstance(body.get("user_id"), str):
                raise APIError("需指定审核账号并明确批准")
            with db() as connection:
                changed = connection.execute("UPDATE reviews SET approved=1 WHERE day=? AND user_id=?", (day_key(), body["user_id"])).rowcount
                if not changed:
                    raise APIError("没有找到待审核记录", 404)
        else:
            raise APIError("管理接口不存在", 404)
        self.json_response({"ok": True})

    def start_oauth(self):
        client_id = os.environ.get("LINUXDO_CLIENT_ID")
        if not client_id or not os.environ.get("LINUXDO_CLIENT_SECRET"):
            raise APIError("尚未配置 LINUX DO Connect", 503)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        next_path = query.get("next", ["/"])[0]
        if next_path not in {"/", "/shop", "/donate"}:
            next_path = "/"
        state = secrets.token_urlsafe(32)
        state_cookie = sign_payload({"purpose": "oauth", "state": state, "next": next_path, "exp": time.time() + 600})
        params = urllib.parse.urlencode({"client_id": client_id, "redirect_uri": os.environ.get("LINUXDO_REDIRECT_URI", APP_BASE_URL + "/auth/linuxdo/callback"), "response_type": "code", "scope": "user", "state": state})
        self.send_response(302)
        self.send_header("Set-Cookie", self.cookie("oauth_state", state_cookie, 600))
        self.send_header("Location", "https://connect.linux.do/oauth2/authorize?" + params)
        self.end_headers()

    def finish_oauth(self, parsed):
        query = urllib.parse.parse_qs(parsed.query)
        code, state = query.get("code", [""])[0], query.get("state", [""])[0]
        saved = verify_payload(self.cookie_values().get("oauth_state", ""))
        if not code or not saved or saved.get("purpose") != "oauth" or not hmac.compare_digest(state, saved.get("state", "")):
            raise APIError("OAuth 回调校验失败，请重新登录")
        auth = base64.b64encode(f"{os.environ.get('LINUXDO_CLIENT_ID', '')}:{os.environ.get('LINUXDO_CLIENT_SECRET', '')}".encode()).decode()
        token = json_request("https://connect.linux.do/oauth2/token", method="POST", form=True, headers={"Authorization": f"Basic {auth}"}, data={"grant_type": "authorization_code", "code": code, "redirect_uri": os.environ.get("LINUXDO_REDIRECT_URI", APP_BASE_URL + "/auth/linuxdo/callback")})
        if not token.get("access_token"):
            raise APIError("没有获取到登录令牌", 502)
        profile = json_request("https://connect.linux.do/api/user", headers={"Authorization": f"Bearer {token['access_token']}"})
        profile = profile.get("data", profile)
        if not str(profile.get("id", "")).isdigit() or not isinstance(profile.get("username"), str) or not profile["username"]:
            raise APIError("登录服务返回的用户身份不完整", 502)
        session = sign_payload({"purpose": "session", "id": str(profile["id"]), "username": profile["username"], "name": profile.get("name"), "exp": time.time() + 604800})
        self.send_response(303)
        self.send_header("Set-Cookie", self.cookie("linuxdo_session", session, 604800))
        self.send_header("Set-Cookie", self.cookie("oauth_state", "", 0))
        self.send_header("Location", saved.get("next") if saved.get("next") in {"/", "/shop", "/donate"} else "/")
        self.end_headers()


def scheduler(stop: threading.Event):
    next_condition = 0.0
    while not stop.is_set():
        try:
            with db() as connection:
                day = ensure_day(connection, time.time())
                url = settings(connection)["condition_url"]
            if day["opened_at"] is None and url and time.monotonic() >= next_condition:
                next_condition = time.monotonic() + 30
                token = os.environ.get("CHECKIN_CONDITION_TOKEN", "")
                result = json_request(url, headers={"Authorization": f"Bearer {token}"} if token else {}, timeout=5)
                if result.get("open") is True:
                    # Only apply a response to the day for which it was requested.
                    if day["day"] == day_key():
                        open_today("condition")
        except Exception as exc:
            print(f"开启条件检查失败: {type(exc).__name__}", flush=True)
        stop.wait(1)


def main():
    base = urllib.parse.urlsplit(APP_BASE_URL)
    if base.hostname not in {"localhost", "127.0.0.1", "::1"} and len(os.environ.get("APP_SECRET", "")) < 32:
        raise SystemExit("生产环境必须配置至少 32 字符的 APP_SECRET")
    init_db()
    stop = threading.Event()
    worker = threading.Thread(target=scheduler, args=(stop,), daemon=True)
    worker.start()
    server = CheckinServer((HOST, PORT), AppHandler)
    print(f"提肛打卡已启动: {APP_BASE_URL}", flush=True)
    print("打卡奖励为站内积分；LDC 赞助不增加积分。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        worker.join(timeout=6)


if __name__ == "__main__":
    main()
