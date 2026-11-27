from __future__ import annotations

import base64
import secrets
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

import httpx

from app.common.http_client import json_request
from app.config import Settings

CONNECT_AUTHORIZE_URL = "https://connect.linux.do/oauth2/authorize"
CONNECT_TOKEN_URL = "https://connect.linux.do/oauth2/token"
CONNECT_USER_URL = "https://connect.linux.do/api/user"


def _basic(client_id: str, client_secret: str) -> str:
    return "Basic " + base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()


async def exchange_code(code: str) -> dict:
    """Trade an OAuth authorization code for the user's Connect profile."""
    token = await json_request(
        CONNECT_TOKEN_URL, method="POST", form=True,
        headers={"Authorization": _basic(Settings.LINUXDO_CLIENT_ID, Settings.LINUXDO_CLIENT_SECRET)},
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": Settings.LINUXDO_REDIRECT_URI})
    if not token.get("access_token"):
        return {}
    profile = await json_request(CONNECT_USER_URL, headers={"Authorization": f"Bearer {token['access_token']}"})
    return profile.get("data", profile)


async def dispatch_ldc(order_no: str, user: dict, amount: str) -> tuple[str, str, str]:
    """Deliver LDC to a user via Linux DO Credit /lpay/distribute -> (status, trade_no, error)."""
    if not Settings.LDC_LIVE or not Settings.LDC_CLIENT_ID or not Settings.LDC_CLIENT_SECRET:
        return ("simulated", f"SIM-{secrets.token_hex(6).upper()}", "")
    try:
        response = await json_request(
            f"{Settings.LDC_API_BASE}/lpay/distribute", method="POST",
            headers={"Authorization": _basic(Settings.LDC_CLIENT_ID, Settings.LDC_CLIENT_SECRET)},
            data={"user_id": int(user["id"]), "username": user["username"], "amount": amount,
                  "out_trade_no": order_no, "remark": f"积分兑换 {order_no}"},
            timeout=10)
        data = response.get("data") or {}
        trade_no = str(data.get("trade_no") or "").strip()
        if trade_no:
            return ("success", trade_no, "")
        if response.get("code") == 1:
            return ("uncertain", "", "分发成功但缺少交易单号，需核对")
        error = str(response.get("error_msg") or response.get("message") or response.get("msg") or "").strip()
        if error:
            return ("failed", "", error)
        return ("uncertain", "", "分发响应缺少交易单号及明确错误，需核对")
    except httpx.HTTPStatusError as exc:
        # 响应已到达但非 2xx：保留 Credit 返回的原因，是否已发货仍交给订单查询判定。
        payload = getattr(exc, "payload", None) or {}
        reason = str(payload.get("error_msg") or payload.get("message") or payload.get("msg") or "").strip()
        return ("uncertain", "", f"Credit 返回 HTTP {exc.response.status_code}：{reason or '无错误说明'}"[:300])
    except Exception as exc:
        return ("uncertain", "", f"请求超时或网络异常: {type(exc).__name__}")


async def query_ldc_order(order_no: str, amount: str) -> tuple[str, str, str]:
    """Ask Credit whether a /lpay/distribute order exists -> (state, trade_no, detail).

    state: "delivered"（Credit 记录为成功，且单号、金额一致）| "missing"（Credit 明确无此订单）| "unknown"（其他一律不下结论）
    """
    if not Settings.LDC_LIVE or not Settings.LDC_CLIENT_ID or not Settings.LDC_CLIENT_SECRET:
        return ("unknown", "", "未启用真实发货，无法向 Credit 查询")
    url = f"{Settings.LDC_API_BASE}/epay/api.php?" + urlencode({
        "act": "order", "pid": Settings.LDC_CLIENT_ID, "key": Settings.LDC_CLIENT_SECRET, "out_trade_no": order_no})
    try:
        response = await json_request(url, timeout=10)
    except httpx.HTTPStatusError as exc:
        payload = getattr(exc, "payload", None) or {}
        message = str(payload.get("msg") or payload.get("error_msg") or "").strip()
        if exc.response.status_code == 404 and payload.get("code") == -1 and "不存在" in message:
            return ("missing", "", message)
        return ("unknown", "", f"Credit 返回 HTTP {exc.response.status_code}：{message or '无说明'}"[:200])
    except Exception as exc:
        return ("unknown", "", f"查询失败: {type(exc).__name__}")
    trade_no = str(response.get("trade_no") or "").strip()
    if response.get("code") == 1 and str(response.get("status")) == "1" and trade_no:
        try:
            same_amount = Decimal(str(response.get("money"))) == Decimal(amount)
        except (InvalidOperation, ValueError):
            same_amount = False
        if str(response.get("out_trade_no") or "") == order_no and same_amount:
            return ("delivered", trade_no, "")
        return ("unknown", "", "Credit 返回的单号或金额与本地订单不一致")
    return ("unknown", "", f"Credit 状态 {response.get('status')}：{response.get('msg') or '无说明'}"[:200])
