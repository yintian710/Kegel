from __future__ import annotations

import base64
import secrets

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
    except Exception as exc:
        return ("uncertain", "", f"请求超时或网络异常: {type(exc).__name__}")
