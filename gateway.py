"""
Payment gateway client for YOUR OWN gateway (FamPay + Paytm, UPI QR, auto detect).
API docs: payment-gateway-api-docs.txt   ->  POST /api/v1/payment/create , GET /api/verify.php
Website admin -> Settings -> Payment Gateway: choose gateway, paste API token, Save & Connect.
The Base URL is changeable there, everything else stays the same.
"""
import hmac, hashlib, time, requests
import db

DEFAULT_BASE = "https://paymentgateway-0km8.onrender.com"


def _base():
    return (db.get("gw_base").strip() or DEFAULT_BASE).rstrip("/")


def _token():
    return db.get("gw_token").strip()


def configured():
    return bool(_token())


def gateway_name():
    return "fampay" if db.get("gw_gateway") == "fampay" else "paytm"


def _h():
    return {"X-API-Key": _token(), "Content-Type": "application/json", "Accept": "application/json"}


def _err(r, j):
    msg = ""
    if isinstance(j, dict):
        msg = str(j.get("error") or j.get("message") or "")
    if r.status_code == 401:
        return "Invalid API token."
    if r.status_code == 403:
        return msg or "Gateway not included in your plan / limit reached."
    if r.status_code == 429:
        return "Too many requests, try again in a minute."
    if r.status_code >= 500:
        return "Gateway could not reach the payment provider, try again shortly."
    return msg or f"Gateway error (HTTP {r.status_code})"


def create(pay_no, amount, user, return_url="", webhook_url=""):
    """Create a UPI QR payment. Returns
    {"ok", "upi_uri", "pay_url", "ref", "pay_amount", "err"}   pay_amount = EXACT amount the customer must pay (FamPay may add paise)"""
    body = {"amount": round(float(amount), 2), "order_id": pay_no, "gateway": gateway_name(),
            "customer": {"name": user["name"], "telegram_id": str(user["id"])}}
    try:
        r = requests.post(_base() + "/api/v1/payment/create", headers=_h(), json=body, timeout=25)
        try:
            j = r.json()
        except Exception:
            return {"ok": False, "err": f"Gateway replied HTTP {r.status_code} (not JSON)"}
    except Exception as e:
        return {"ok": False, "err": "Gateway not reachable: " + str(e)[:100]}
    if r.status_code >= 300 or not isinstance(j, dict) or not j.get("success"):
        return {"ok": False, "err": _err(r, j)}
    upi = str(j.get("upi_uri") or "")
    pay_url = str(j.get("payment_url") or "")
    if not (upi or pay_url):
        return {"ok": False, "err": "Gateway did not return a QR."}
    try:
        pa = float(j.get("amount") or amount)
    except (TypeError, ValueError):
        pa = float(amount)
    return {"ok": True, "upi_uri": upi, "pay_url": pay_url, "ref": str(j.get("pay_id") or ""), "pay_amount": pa, "err": ""}


def check(pay_no):
    """Ask the gateway. Returns ("paid"|"pending"|"failed", txn_id, amount). Only SUCCESS means paid."""
    try:
        r = requests.get(_base() + "/api/verify.php", headers=_h(), params={"order_id": pay_no}, timeout=20)
        j = r.json()
    except Exception:
        return "pending", "", 0.0
    if not isinstance(j, dict):
        return "pending", "", 0.0
    st = str(j.get("status") or "").lower()
    d = j.get("data") if isinstance(j.get("data"), dict) else {}
    if st == "success":
        try:
            amt = float(d.get("amount") or 0)
        except (TypeError, ValueError):
            amt = 0.0
        return "paid", str(d.get("utr") or d.get("transaction_id") or ""), amt
    if st in ("failed", "expired"):
        return "failed", "", 0.0
    return "pending", "", 0.0


def connect_test():
    """Used by the 'Save & Connect' button. Returns (ok, message)."""
    if not _token():
        return False, "Paste the API token first."
    try:
        r = requests.get(_base() + "/api/verify.php", headers=_h(), params={"order_id": "RG-CONNECT-TEST"}, timeout=20)
    except Exception as e:
        return False, "Cannot reach the gateway at " + _base() + " : " + str(e)[:100]
    try:
        j = r.json()
    except Exception:
        j = {}
    if r.status_code == 401:
        return False, "Invalid API token."
    if r.status_code == 403:
        return False, _err(r, j)
    if r.status_code == 429:
        return False, "Gateway is rate limiting, press Connect again in a minute."
    if r.status_code >= 500:
        return False, f"Gateway error (HTTP {r.status_code})."
    return True, f"Connected successfully! Gateway: {gateway_name().upper()} · {_base()}"


def verify_signature(secret, ts, sig, raw_body):
    """X-Payment-Gateway-Signature = sha256=HMAC_SHA256(secret, ts + '.' + rawBody)"""
    try:
        if abs(time.time() - int(ts)) > 300:
            return False
    except (TypeError, ValueError):
        return False
    exp = "sha256=" + hmac.new(secret.encode(), (str(ts) + "." + raw_body).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(exp, sig or "")
