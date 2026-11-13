"""
Payment gateway client (QR / UPI auto-detect).

Admin website -> Settings -> "QR Payment Gateway":
  Gateway base URL, API token, create-order path, check-order path.

!! If your gateway uses different field names, change ONLY the two small
!! functions create() and check() below (marked  <<< ADJUST HERE >>>).
"""
import requests, json
import db

PAID_WORDS = {"paid", "success", "successful", "completed", "complete", "captured", "credit", "credited", "done"}
FAIL_WORDS = {"failed", "failure", "expired", "cancelled", "canceled", "rejected"}


def configured():
    return bool(db.get("gw_base").strip() and db.get("gw_token").strip())


def _url(path_key):
    base = db.get("gw_base").strip().rstrip("/")
    path = db.get(path_key).strip()
    if path and not path.startswith("/"):
        path = "/" + path
    return base + path


def _headers():
    t = db.get("gw_token").strip()
    return {"Authorization": "Bearer " + t, "X-API-Key": t, "Content-Type": "application/json", "Accept": "application/json"}


def _pick(d, *names):
    """find first matching key in dict (also looks inside 'data' / 'result')"""
    if not isinstance(d, dict):
        return ""
    for scope in (d, d.get("data"), d.get("result")):
        if isinstance(scope, dict):
            for n in names:
                v = scope.get(n)
                if v not in (None, "", {}):
                    return v
    return ""


def create(pay_no, amount, user, return_url, webhook_url):
    """Create an order on the gateway.
    Returns {"ok": bool, "upi_uri": str, "pay_url": str, "ref": str, "err": str}"""
    # <<< ADJUST HERE >>>  request body sent to your gateway
    body = {
        "order_id": pay_no,
        "amount": round(float(amount), 2),
        "customer_name": user["name"],
        "customer_mobile": user["phone"] or "",
        "customer_id": str(user["id"]),
        "redirect_url": return_url,
        "callback_url": webhook_url,
        "webhook_url": webhook_url,
        "remark": "RG " + pay_no,
    }
    try:
        r = requests.post(_url("gw_create_path"), headers=_headers(), data=json.dumps(body), timeout=25)
        try:
            j = r.json()
        except Exception:
            return {"ok": False, "err": f"Gateway replied HTTP {r.status_code} (not JSON)"}
    except Exception as e:
        return {"ok": False, "err": "Gateway not reachable: " + str(e)[:120]}
    # <<< ADJUST HERE >>>  field names read from your gateway's reply
    upi = _pick(j, "upi_uri", "upi_url", "upi_link", "intent_url", "upi_intent", "qr_string", "qr_data")
    pay_url = _pick(j, "payment_url", "pay_url", "checkout_url", "link", "url", "payment_link")
    ref = _pick(j, "gateway_order_id", "reference", "ref", "transaction_id", "txn_id", "order_id", "id")
    st = str(_pick(j, "status")).lower()
    ok_flag = j.get("success", j.get("ok", None)) if isinstance(j, dict) else None
    if (ok_flag is False) or st in FAIL_WORDS or not (upi or pay_url):
        msg = _pick(j, "message", "error", "msg", "detail") or "Gateway did not return a payment link"
        return {"ok": False, "err": str(msg)[:160]}
    return {"ok": True, "upi_uri": str(upi) if str(upi).lower().startswith("upi:") else "",
            "pay_url": str(pay_url), "ref": str(ref), "err": ""}


def check(pay_no):
    """Ask the gateway if the order is paid. Returns ("paid"|"pending"|"failed", txn_id)"""
    # <<< ADJUST HERE >>>  how your gateway is asked for order status
    try:
        r = requests.get(_url("gw_check_path"), headers=_headers(), params={"order_id": pay_no}, timeout=20)
        j = r.json()
    except Exception:
        return "pending", ""
    st = str(_pick(j, "status", "payment_status", "state", "txn_status")).lower()
    txn = str(_pick(j, "utr", "txn_id", "transaction_id", "bank_rrn", "rrn", "payment_id", "reference") or "")
    if st in PAID_WORDS:
        return "paid", txn
    if st in FAIL_WORDS:
        return "failed", txn
    return "pending", txn
