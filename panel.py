"""
Panel API (your main website) - connect, balance, products, purchase.

Endpoints used (X-API-Key header):
  GET  /api/v1/connect     -> {"connected": true, "username": .., "balance": ..}
  GET  /api/v1/balance     -> {"balance": ..}
  GET  /api/v1/products    -> {"products": [{"product_id", "name", "plans": [{"plan_id", "name", "price"}]}]}
  POST /api/v1/purchase    -> {"success": true, "key": ".."}   body {"plan_id": N}

Website admin -> "Panel API": API token + Server URL (both changeable any time), Connect, Check Balance,
Show Products, add selected / all, reseller % and user % markup.
"""
import time, traceback
import requests
import db

DEFAULT_URL = "https://official2-qg3g.onrender.com"


class PanelError(Exception):
    """definite=True  -> the panel surely did NOT make the purchase (safe to refund automatically)
       definite=False -> unknown (timeout / broken answer): the key may have been issued, so NO automatic refund"""

    def __init__(self, msg, definite=True):
        super().__init__(msg)
        self.msg = msg
        self.definite = definite


def _base():
    return (db.get("panel_url").strip() or DEFAULT_URL).rstrip("/")


def _token():
    return db.get("panel_token").strip()


def configured():
    return bool(_token())


def _h():
    return {"X-API-Key": _token(), "Accept": "application/json", "Content-Type": "application/json"}


def _msg(r, j):
    m = ""
    if isinstance(j, dict):
        m = str(j.get("error") or j.get("message") or "")
    if r.status_code in (401, 403) and not m:
        m = "Invalid API token."
    return m or f"Panel error (HTTP {r.status_code})"


def _json(r):
    try:
        return r.json()
    except Exception:
        return None


def _get(path, **params):
    """GET -> dict. Raises PanelError (read-only calls are always safe to repeat)."""
    if not configured():
        raise PanelError("API token is not set.")
    try:
        r = requests.get(_base() + path, headers=_h(), params=params, timeout=60)
    except requests.exceptions.Timeout:
        raise PanelError("Panel did not answer in time (server may be waking up - try again).")
    except requests.exceptions.RequestException as e:
        raise PanelError("Cannot reach the panel: %s" % str(e)[:150])
    j = _json(r)
    if r.status_code >= 400 or not isinstance(j, dict):
        raise PanelError(_msg(r, j))
    return j


def connect_test():
    """-> (ok, text)"""
    try:
        d = _get("/api/v1/connect")
    except PanelError as e:
        return False, "Not connected: " + e.msg
    if d.get("connected"):
        return True, "Connect successful (%s, balance %s INR)" % (d.get("username", "-"), d.get("balance", "-"))
    return False, "Not connected: %s" % (d.get("message") or d.get("error") or "unknown reason")


def balance():
    d = _get("/api/v1/balance")
    return float(d.get("balance") or 0)


def products(ids=None):
    p = {"ids": ",".join(map(str, ids))} if ids else {}
    d = _get("/api/v1/products", **p)
    out = d.get("products")
    if not isinstance(out, list):
        raise PanelError(str(d.get("error") or d.get("message") or "Panel returned no product list."))
    return out


def buy(api_plan_id):
    """Buy ONE key from the panel. Returns the key or raises PanelError."""
    if not configured():
        raise PanelError("Panel API token is not set.", True)
    try:
        r = requests.post(_base() + "/api/v1/purchase", headers=_h(), json={"plan_id": int(api_plan_id)}, timeout=90)
    except requests.exceptions.ConnectTimeout:
        raise PanelError("Panel is not reachable (connect timeout).", True)
    except requests.exceptions.ReadTimeout:
        raise PanelError("Panel did not answer in time - the purchase may or may not have gone through.", False)
    except requests.exceptions.ConnectionError as e:
        t = str(e)
        if "NewConnectionError" in t or "Failed to establish" in t or "Name or service" in t or "Temporary failure" in t:
            raise PanelError("Panel is not reachable.", True)
        raise PanelError("Connection to the panel broke during the purchase - it may or may not have gone through.", False)
    except requests.exceptions.RequestException as e:
        raise PanelError("Panel request failed: %s" % str(e)[:120], False)
    j = _json(r)
    if isinstance(j, dict) and j.get("success") and j.get("key"):
        return str(j["key"]).strip()
    if r.status_code in (502, 503):
        raise PanelError("Panel is unavailable right now (it may be waking up).", True)
    if r.status_code >= 500:
        raise PanelError(_msg(r, j), False)                    # panel crashed: unknown if the key was made
    if isinstance(j, dict) and (j.get("error") or j.get("message")):
        raise PanelError(str(j.get("error") or j.get("message")), True)   # the panel clearly said "no"
    if 400 <= r.status_code < 500:
        raise PanelError(_msg(r, j), True)
    raise PanelError("Unclear answer from the panel (HTTP %s)." % r.status_code, False)


# ------------------------------------------------------------------ prices
def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def markups():
    """(reseller %, user %)"""
    return max(_f(db.get("panel_mk_reseller"), 25.0), 0.0), max(_f(db.get("panel_mk_user"), 200.0), 0.0)


def calc(base, rpct=None, upct=None):
    """panel price -> (user price, reseller price).  25% markup = price x 1.25"""
    if rpct is None or upct is None:
        rpct, upct = markups()
    base = _f(base)
    return round(base * (1 + upct / 100.0), 2), round(base * (1 + rpct / 100.0), 2)


def reprice_all(force=False):
    """recalculate user / reseller price of every panel plan from its panel price.
    force=False keeps plans whose price you edited by hand; force=True overwrites those too."""
    n = 0
    rpct, upct = markups()
    with db.conn() as c:
        for pl in c.execute("SELECT id, base_price, manual FROM plans WHERE api_plan_id>0").fetchall():
            if pl["manual"] and not force:
                continue
            up, rp = calc(pl["base_price"], rpct, upct)
            c.execute("UPDATE plans SET price=?, rprice=?, manual=0 WHERE id=?", (up, rp, pl["id"]))
            n += 1
    return n


# ------------------------------------------------------------------ import / sync
def import_products(ids=None, panel_list=None):
    """Add (or update) products from the panel. ids=None -> ALL.
    Returns (new_products, new_plans, updated_plans)."""
    plist = panel_list if panel_list is not None else products()
    want = None if ids is None else {int(i) for i in ids}
    rpct, upct = markups()
    np_, nl, ul = 0, 0, 0
    with db.conn() as c:
        for p in plist:
            try:
                pid = int(p.get("product_id"))
            except (TypeError, ValueError):
                continue
            if want is not None and pid not in want:
                continue
            row = c.execute("SELECT id FROM products WHERE api_pid=?", (pid,)).fetchone()
            if row:
                lid = row["id"]
            else:
                top = c.execute("SELECT COALESCE(MAX(sort),0) FROM products").fetchone()[0]
                lid = c.execute("INSERT INTO products(name,api_pid,sort) VALUES(?,?,?)",
                                (str(p.get("name") or f"Product {pid}").strip(), pid, top + 1)).lastrowid
                np_ += 1
            for n, pl in enumerate(p.get("plans") or []):
                try:
                    apid = int(pl.get("plan_id"))
                except (TypeError, ValueError):
                    continue
                base = _f(pl.get("price"))
                up, rp = calc(base, rpct, upct)
                ex = c.execute("SELECT id, manual FROM plans WHERE api_plan_id=?", (apid,)).fetchone()
                if ex:
                    if ex["manual"]:
                        c.execute("UPDATE plans SET base_price=? WHERE id=?", (base, ex["id"]))
                    else:
                        c.execute("UPDATE plans SET base_price=?, price=?, rprice=? WHERE id=?", (base, up, rp, ex["id"]))
                    ul += 1
                else:
                    c.execute("INSERT INTO plans(product_id,name,price,rprice,sort,api_plan_id,base_price) VALUES(?,?,?,?,?,?,?)",
                              (lid, str(pl.get("name") or f"Plan {apid}").strip(), up, rp, n, apid, base))
                    nl += 1
    return np_, nl, ul


def sync_existing():
    """refresh panel prices of products you already added (+ add plans that are new in the panel).
    Returns (updated_plans, new_plans, missing_plans)."""
    with db.conn() as c:
        ids = [r["api_pid"] for r in c.execute("SELECT api_pid FROM products WHERE api_pid>0").fetchall()]
    if not ids:
        return 0, 0, 0
    plist = products(ids)
    _np, nl, ul = import_products(ids, plist)
    seen = {int(pl.get("plan_id")) for p in plist for pl in (p.get("plans") or []) if str(pl.get("plan_id", "")).isdigit()}
    seen_prod = {int(p.get("product_id")) for p in plist if str(p.get("product_id", "")).isdigit()}
    missing = 0
    with db.conn() as c:
        for r in c.execute("""SELECT pl.api_plan_id, p.api_pid FROM plans pl JOIN products p ON p.id=pl.product_id
                              WHERE pl.api_plan_id>0 AND pl.active=1""").fetchall():
            if r["api_pid"] in seen_prod and r["api_plan_id"] not in seen:
                missing += 1
    db.put("panel_last_sync", str(int(time.time())))
    return ul, nl, missing


def sync_loop(on_error=None):
    """background: keeps panel prices (and your markup) up to date automatically"""
    time.sleep(90)
    while True:
        time.sleep(60)
        try:
            if not configured() or db.get("panel_autosync") != "1":
                continue
            gap = max(int(_f(db.get("panel_sync_min"), 60)), 5) * 60
            if time.time() - _f(db.get("panel_last_sync")) >= gap:
                sync_existing()
        except Exception:
            traceback.print_exc()
            db.put("panel_last_sync", str(int(time.time())))   # do not hammer a broken panel
