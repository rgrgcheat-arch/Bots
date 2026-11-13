import sqlite3, os, time, random, secrets
from contextlib import contextmanager

DB_PATH = os.getenv("DB_PATH", "data.db")

# key: (fallback emoji, where it is used)
EMOJI_DEFAULTS = {
    "top": ("🔝", "Main menu title"),
    "party": ("🎉", "Welcome line"),
    "bars": ("📶", "Store highlights title"),
    "key": ("🔑", "Premium Game Keys"),
    "fire": ("🔥", "Instant Delivery"),
    "shield": ("🛡️", "Secure Payments"),
    "gift": ("🎁", "VIP Rewards"),
    "h24": ("🕐", "24/7 Support line"),
    "tap": ("👆", "Tap Product Store line"),
    "sale": ("💥", "Shop Now button"),
    "money": ("💰", "Add Balance button / titles"),
    "history": ("📜", "All History button"),
    "user": ("👤", "My Profile button"),
    "share": ("🔗", "Referral button"),
    "yt": ("▶️", "Tutorial / Watch Video"),
    "folder": ("📁", "All Update File button"),
    "support": ("💬", "Support button"),
    "cart": ("🛒", "Orders"),
    "diamond": ("💎", "Spent / lifetime spent"),
    "check": ("✅", "ID / success"),
    "cancel": ("❌", "Cancel button"),
    "confirm": ("✅", "Confirm button"),
    "back": ("➡️", "Back buttons"),
    "download": ("📥", "Download All Keys"),
    "telegram": ("✈️", "Chat on Telegram"),
    "whatsapp": ("📞", "Chat on WhatsApp"),
    "megaphone": ("📣", "Invite link line"),
    "chart": ("📊", "Deposit limits"),
    "calendar": ("📅", "Joined date"),
    "wallet": ("👛", "Balance"),
    "info": ("ℹ️", "Notes"),
    "phone": ("📱", "Phone"),
    "globe": ("🌐", "Country"),
    "gift2": ("🎀", "Referral balance"),
    "fire2": ("🔥", "Name line"),
    "time": ("⏱", "Order time"),
    "box": ("📦", "Stock lines"),
    "bag": ("🛍️", "Buy Now button"),
    "wait": ("⏳", "Pending payment / admin alerts"),
    "paid": ("💳", "I Have Paid button"),
    "qr": ("📲", "QR payment title"),
    "receipt": ("🧾", "Order summary title"),
    "idcard": ("🆔", "User ID line"),
    "coupon": ("🎟️", "Coupon button / line"),
    "success": ("✅", "Payment successful title"),
    "txn": ("🔖", "Transaction ID line"),
    "upi": ("💳", "Pay UPI button"),
    "binance": ("🟡", "Pay Binance button"),
    "local": ("🏦", "Pay Local (bKash/bank) button"),
}

SETTINGS_DEFAULTS = {
    "shop_name": "RG CHEAT SHOP",
    "min_dep": "1",
    "max_dep": "10000",
    "ref_reward": "2",
    "support_tg_on": "1",
    "support_tg": "",
    "support_wa_on": "1",
    "support_wa": "",
    "tutorial_url": "",
    "update_url": "",
    "upi_id": "",
    "upi_name": "RG CHEAT SHOP",
    "pay_other_text": "",
    "ref_percent": "5",
    "maint": "0",
    "maint_text": "We are updating the store. Please try again in a few minutes.",
    "low_stock": "3",
    "gw_base": "",
    "gw_token": "",
    "gw_create_path": "/api/create-order",
    "gw_check_path": "/api/check-order",
    "gw_secret": "",
    "pay_expire": "10",
    "pay_name": "RG CHEAT SHOP",
    "pay_upi_on": "1",
    "pay_binance_on": "1",
    "binance_text": "",
    "emoji_mode": "ok",
}
RATES = {"INR": 1, "BDT": 1.4, "PKR": 3.3, "NPR": 1.6, "LKR": 3.6, "AED": 0.044, "USD": 0.012, "GBP": 0.0095}
for _c, _r in RATES.items():
    SETTINGS_DEFAULTS["rate_" + _c] = str(_r)

# phone prefix -> (country, currency, symbol)
COUNTRIES = [
    ("880", "BD", "BDT", "৳"), ("91", "IN", "INR", "₹"), ("92", "PK", "PKR", "Rs"),
    ("977", "NP", "NPR", "Rs"), ("94", "LK", "LKR", "Rs"), ("971", "AE", "AED", "AED "),
    ("1", "US", "USD", "$"), ("44", "GB", "GBP", "£"),
]


DIRTY = {"v": False}


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
        if c.total_changes:
            DIRTY["v"] = True
    finally:
        c.close()


def init():
    with conn() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY, name TEXT, username TEXT, phone TEXT,
            country TEXT DEFAULT 'IN', currency TEXT DEFAULT 'INR', symbol TEXT DEFAULT '₹',
            balance REAL DEFAULT 0, ref_balance REAL DEFAULT 0, ref_by INTEGER,
            joined INTEGER, verified INTEGER DEFAULT 0, role TEXT DEFAULT 'user', banned INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS emojis(k TEXT PRIMARY KEY, fallback TEXT, eid TEXT DEFAULT '', note TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT, order_no TEXT, user_id INTEGER,
            product TEXT, plan TEXT, price REAL, key TEXT, created INTEGER);
        CREATE TABLE IF NOT EXISTS deposits(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL,
            status TEXT DEFAULT 'pending', created INTEGER, utr TEXT DEFAULT '', proof TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, descr TEXT DEFAULT '', active INTEGER DEFAULT 1, sort INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS plans(
            id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER, name TEXT, price REAL DEFAULT 0,
            rprice REAL DEFAULT 0, active INTEGER DEFAULT 1, sort INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS keys(
            id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id INTEGER, code TEXT, used INTEGER DEFAULT 0, order_no TEXT);
        CREATE TABLE IF NOT EXISTS pay_orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT, pay_no TEXT UNIQUE, token TEXT UNIQUE, user_id INTEGER,
            kind TEXT, plan_id INTEGER DEFAULT 0, coupon TEXT DEFAULT '', amount REAL, status TEXT DEFAULT 'pending',
            upi_uri TEXT DEFAULT '', pay_url TEXT DEFAULT '', gw_ref TEXT DEFAULT '', txn TEXT DEFAULT '',
            chat_id INTEGER DEFAULT 0, msg_id INTEGER DEFAULT 0, order_no TEXT DEFAULT '',
            title TEXT DEFAULT '', created INTEGER, paid_at INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS coupons(
            code TEXT PRIMARY KEY, kind TEXT DEFAULT 'percent', value REAL DEFAULT 0, max_uses INTEGER DEFAULT 0,
            used INTEGER DEFAULT 0, expires INTEGER DEFAULT 0, active INTEGER DEFAULT 1, created INTEGER);
        CREATE TABLE IF NOT EXISTS coupon_uses(code TEXT, user_id INTEGER, created INTEGER);
        CREATE INDEX IF NOT EXISTS ix_pay_status ON pay_orders(status, created);
        CREATE INDEX IF NOT EXISTS ix_keys_plan ON keys(plan_id, used);
        CREATE INDEX IF NOT EXISTS ix_orders_user ON orders(user_id);
        """)
        for ddl in ("ALTER TABLE pay_orders ADD COLUMN method TEXT DEFAULT 'qr'",
                    "ALTER TABLE pay_orders ADD COLUMN proof TEXT DEFAULT ''",
                    "ALTER TABLE deposits ADD COLUMN utr TEXT DEFAULT ''",
                    "ALTER TABLE deposits ADD COLUMN proof TEXT DEFAULT ''"):
            try:
                c.execute(ddl)
            except sqlite3.OperationalError:
                pass
        for k, v in SETTINGS_DEFAULTS.items():
            c.execute("INSERT OR IGNORE INTO settings(k,v) VALUES(?,?)", (k, v))
        if not (c.execute("SELECT v FROM settings WHERE k='gw_secret'").fetchone()["v"] or "").strip():
            c.execute("UPDATE settings SET v=? WHERE k='gw_secret'", (secrets.token_hex(12),))
        for k, (fb, note) in EMOJI_DEFAULTS.items():
            c.execute("INSERT OR IGNORE INTO emojis(k,fallback,eid,note) VALUES(?,?,?,?)", (k, fb, "", note))


# ---------- settings ----------
def get(k, default=""):
    with conn() as c:
        r = c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def put(k, v):
    with conn() as c:
        c.execute("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))


# ---------- emojis ----------
_ec = {"t": 0, "d": {}}


def emoji_clear():
    _ec["t"] = 0


def emoji(key):
    if time.time() - _ec["t"] > 5:
        with conn() as c:
            m = c.execute("SELECT v FROM settings WHERE k='emoji_mode'").fetchone()
            blocked = bool(m and m["v"] == "blocked")
            _ec["d"] = {r["k"]: (r["fallback"], "" if blocked else r["eid"]) for r in c.execute("SELECT * FROM emojis")}
        _ec["t"] = time.time()
    return _ec["d"].get(key, ("", ""))


# ---------- users ----------
def user(uid):
    with conn() as c:
        return c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def ensure_user(fr, ref=None):
    uid = fr["id"]
    name = (fr.get("first_name") or "") + ((" " + fr["last_name"]) if fr.get("last_name") else "")
    with conn() as c:
        r = c.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone()
        if not r:
            refby = ref if (ref and ref != uid and c.execute("SELECT 1 FROM users WHERE id=?", (ref,)).fetchone()) else None
            c.execute("INSERT INTO users(id,name,username,ref_by,joined) VALUES(?,?,?,?,?)",
                      (uid, name.strip() or "User", fr.get("username"), refby, int(time.time())))
        else:
            c.execute("UPDATE users SET name=?, username=? WHERE id=?", (name.strip() or "User", fr.get("username"), uid))
    return user(uid)


def detect_country(phone):
    for pre, cc, cur, sym in COUNTRIES:
        if phone.startswith(pre):
            return cc, cur, sym
    return "XX", "USD", "$"


def verify(uid, phone):
    """Marks verified. Returns referrer id if this verification should pay a referral reward."""
    cc, cur, sym = detect_country(phone)
    with conn() as c:
        u = c.execute("SELECT verified, ref_by FROM users WHERE id=?", (uid,)).fetchone()
        first = u and not u["verified"]
        c.execute("UPDATE users SET phone=?, country=?, currency=?, symbol=?, verified=1 WHERE id=?",
                  (phone, cc, cur, sym, uid))
        if first and u["ref_by"]:
            return u["ref_by"]
    return None


def add_ref_balance(uid, amt):
    with conn() as c:
        c.execute("UPDATE users SET ref_balance=ref_balance+? WHERE id=?", (amt, uid))


def stats(uid):
    with conn() as c:
        o = c.execute("SELECT COUNT(*) n, COALESCE(SUM(price),0) s FROM orders WHERE user_id=?", (uid,)).fetchone()
        d = c.execute("SELECT COALESCE(SUM(amount),0) s FROM deposits WHERE user_id=? AND status='paid'", (uid,)).fetchone()
    return o["n"], o["s"], d["s"]


def orders(uid, since=None):
    with conn() as c:
        if since:
            return c.execute("SELECT * FROM orders WHERE user_id=? AND created>=? ORDER BY id DESC", (uid, since)).fetchall()
        return c.execute("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall()


# ---------- keypad + temporary state (memory only) ----------
_mem = {"kp": {}, "st": {}}


def kp_get(uid):
    return _mem["kp"].get(uid, "")


def kp_set(uid, amt):
    _mem["kp"][uid] = amt


def st_get(uid):
    return _mem["st"].get(uid, "")


def st_set(uid, v):
    _mem["st"][uid] = v


# ---------- shop ----------
def rate(cur):
    try:
        return float(get("rate_" + cur, "1"))
    except ValueError:
        return 1.0


def price_for(u, pl):
    base = pl["rprice"] if (u["role"] == "reseller" and pl["rprice"] and pl["rprice"] > 0) else pl["price"]
    return round(base * rate(u["currency"]), 2)


def products(active_only=True):
    q = """SELECT p.*,
      (SELECT COUNT(*) FROM keys k JOIN plans pl ON pl.id=k.plan_id WHERE pl.product_id=p.id AND k.used=0) stock,
      (SELECT COUNT(*) FROM plans pl WHERE pl.product_id=p.id) nplans FROM products p"""
    if active_only:
        q += " WHERE p.active=1"
    with conn() as c:
        return c.execute(q + " ORDER BY p.sort, p.id").fetchall()


def product(pid):
    with conn() as c:
        return c.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()


def plans_of(pid, active_only=True):
    q = """SELECT pl.*, (SELECT COUNT(*) FROM keys k WHERE k.plan_id=pl.id AND k.used=0) stock,
           (SELECT COUNT(*) FROM keys k WHERE k.plan_id=pl.id AND k.used=1) sold
           FROM plans pl WHERE pl.product_id=?"""
    if active_only:
        q += " AND pl.active=1"
    with conn() as c:
        return c.execute(q + " ORDER BY pl.sort, pl.id", (pid,)).fetchall()


def plan(plid):
    with conn() as c:
        return c.execute("""SELECT pl.*, p.name pname, p.active pactive,
            (SELECT COUNT(*) FROM keys k WHERE k.plan_id=pl.id AND k.used=0) stock
            FROM plans pl JOIN products p ON p.id=pl.product_id WHERE pl.id=?""", (plid,)).fetchone()


def add_keys(plan_id, text):
    lines, seen = [], set()
    for ln in text.splitlines():
        ln = ln.strip()
        if ln and ln not in seen:
            seen.add(ln)
            lines.append(ln)
    n = 0
    with conn() as c:
        have = {r["code"] for r in c.execute("SELECT code FROM keys WHERE plan_id=? AND used=0", (plan_id,))}
        for ln in lines:
            if ln not in have:
                c.execute("INSERT INTO keys(plan_id,code) VALUES(?,?)", (plan_id, ln))
                n += 1
    return n


def new_order_no():
    return "WAL" + time.strftime("%Y%m%d%H%M%S") + "".join(random.choice("0123456789") for _ in range(9))


def _coupon_discount(c, u, pl, code, base):
    """returns (discount, err). Runs inside an open connection."""
    cp = c.execute("SELECT * FROM coupons WHERE code=?", (code.upper(),)).fetchone()
    if not cp or not cp["active"]:
        return 0, "Invalid coupon code."
    if cp["expires"] and cp["expires"] < time.time():
        return 0, "This coupon has expired."
    if cp["max_uses"] and cp["used"] >= cp["max_uses"]:
        return 0, "This coupon has been fully used."
    if c.execute("SELECT 1 FROM coupon_uses WHERE code=? AND user_id=?", (cp["code"], u["id"])).fetchone():
        return 0, "You have already used this coupon."
    if cp["kind"] == "percent":
        d = base * min(cp["value"], 100) / 100
    else:
        d = cp["value"] * rate(u["currency"])
    return round(min(d, base), 2), ""


def coupon_calc(u, pl, code):
    """Preview for the order summary. Returns (final_price, discount, err)."""
    base = price_for(u, pl)
    if not code:
        return base, 0, ""
    with conn() as c:
        d, err = _coupon_discount(c, u, pl, code, base)
    if err:
        return base, 0, err
    return round(base - d, 2), d, ""


_mem["cp"] = {}


def cp_set(uid, plid, code):
    _mem["cp"][uid] = (plid, code)


def cp_get(uid, plid):
    v = _mem["cp"].get(uid)
    return v[1] if v and v[0] == plid else ""


def buy(uid, plan_id, coupon="", ext_price=None):
    """Atomic purchase. ext_price = amount already paid by QR (wallet is not charged).
    Returns ('ok', order, stock_left) | ('bal', price) | ('stock',) | ('gone',) | ('coupon', msg) | ('refund', amount)"""
    with conn() as c:
        c.execute("BEGIN IMMEDIATE")
        u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        pl = c.execute("""SELECT pl.*, p.name pname FROM plans pl JOIN products p ON p.id=pl.product_id
                          WHERE pl.id=? AND pl.active=1 AND p.active=1""", (plan_id,)).fetchone()
        if not u or not pl:
            if ext_price and u:
                c.execute("UPDATE users SET balance=balance+? WHERE id=?", (ext_price, uid))
                return ("refund", ext_price)
            return ("gone",)
        price = price_for(u, pl)
        if ext_price is not None:
            price = ext_price
        elif coupon:
            d, err = _coupon_discount(c, u, pl, coupon, price)
            if err:
                return ("coupon", err)
            price = round(price - d, 2)
        if ext_price is None and u["balance"] < price:
            return ("bal", price)
        k = c.execute("SELECT id, code FROM keys WHERE plan_id=? AND used=0 ORDER BY id LIMIT 1", (plan_id,)).fetchone()
        if not k:
            if ext_price is not None:
                c.execute("UPDATE users SET balance=balance+? WHERE id=?", (ext_price, uid))
                return ("refund", ext_price)
            return ("stock",)
        no = new_order_no()
        c.execute("UPDATE keys SET used=1, order_no=? WHERE id=?", (no, k["id"]))
        if ext_price is None:
            c.execute("UPDATE users SET balance=balance-? WHERE id=?", (price, uid))
        if coupon and ext_price is None:
            c.execute("UPDATE coupons SET used=used+1 WHERE code=?", (coupon.upper(),))
            c.execute("INSERT INTO coupon_uses(code,user_id,created) VALUES(?,?,?)", (coupon.upper(), uid, int(time.time())))
        now = int(time.time())
        c.execute("INSERT INTO orders(order_no,user_id,product,plan,price,key,created) VALUES(?,?,?,?,?,?,?)",
                  (no, uid, pl["pname"], pl["name"], price, k["code"], now))
        left = c.execute("SELECT COUNT(*) FROM keys WHERE plan_id=? AND used=0", (plan_id,)).fetchone()[0]
        order = {"order_no": no, "product": pl["pname"], "plan": pl["name"], "price": price, "key": k["code"],
                 "created": now, "plan_id": plan_id}
        return ("ok", order, left)


def coupon_consume(uid, code):
    """used when a coupon-priced purchase is paid by QR"""
    if not code:
        return
    with conn() as c:
        c.execute("UPDATE coupons SET used=used+1 WHERE code=?", (code.upper(),))
        c.execute("INSERT INTO coupon_uses(code,user_id,created) VALUES(?,?,?)", (code.upper(), uid, int(time.time())))


# ---------- QR / gateway payment orders ----------
def pay_new_no():
    return "ZP" + time.strftime("%y%m%d%H%M%S") + "".join(random.choice("0123456789") for _ in range(6))


def pay_create(uid, kind, amount, plan_id=0, coupon="", title="", method="qr"):
    no, tok = pay_new_no(), secrets.token_urlsafe(18)
    with conn() as c:
        # only one open payment per user: close older ones
        c.execute("UPDATE pay_orders SET status='cancelled' WHERE user_id=? AND status='pending'", (uid,))
        c.execute("""INSERT INTO pay_orders(pay_no,token,user_id,kind,plan_id,coupon,amount,title,created,method)
                     VALUES(?,?,?,?,?,?,?,?,?,?)""", (no, tok, uid, kind, plan_id, coupon, amount, title, int(time.time()), method))
    return pay_get(no)


def pay_get(no):
    with conn() as c:
        return c.execute("SELECT * FROM pay_orders WHERE pay_no=?", (no,)).fetchone()


def pay_by_token(tok):
    with conn() as c:
        return c.execute("SELECT * FROM pay_orders WHERE token=?", (tok,)).fetchone()


def pay_update(no, **kw):
    if not kw:
        return
    with conn() as c:
        c.execute("UPDATE pay_orders SET " + ",".join(f"{k}=?" for k in kw) + " WHERE pay_no=?", (*kw.values(), no))


def pay_resolve(no, txn=""):
    """pending/expired -> paid exactly once (late payments are still honoured). Returns the row if THIS call did it."""
    with conn() as c:
        c.execute("BEGIN IMMEDIATE")
        p = c.execute("SELECT * FROM pay_orders WHERE pay_no=? AND status IN ('pending','expired','review')", (no,)).fetchone()
        if not p:
            return None
        c.execute("UPDATE pay_orders SET status='paid', txn=?, paid_at=? WHERE pay_no=?", (txn or "", int(time.time()), no))
        return p


def pay_pending():
    """only automatic (gateway QR) payments are watched; manual ones wait for the admin"""
    with conn() as c:
        return c.execute("SELECT * FROM pay_orders WHERE status='pending' AND method='qr' ORDER BY id").fetchall()


def pay_submit(no, txn, proof):
    with conn() as c:
        c.execute("UPDATE pay_orders SET status='review', txn=?, proof=? WHERE pay_no=? AND status='pending'", (txn, proof, no))


def pay_txn_used(txn):
    with conn() as c:
        a = c.execute("SELECT 1 FROM pay_orders WHERE txn=? AND txn<>'' AND status IN ('review','paid')", (txn,)).fetchone()
        b = c.execute("SELECT 1 FROM deposits WHERE utr=? AND utr<>'' AND status IN ('review','paid')", (txn,)).fetchone()
    return bool(a or b)


def pay_reject(no):
    with conn() as c:
        c.execute("BEGIN IMMEDIATE")
        p = c.execute("SELECT * FROM pay_orders WHERE pay_no=? AND status IN ('pending','review','expired')", (no,)).fetchone()
        if not p:
            return None
        c.execute("UPDATE pay_orders SET status='rejected' WHERE pay_no=?", (no,))
        return p


def add_balance(uid, amt):
    with conn() as c:
        c.execute("UPDATE users SET balance=balance+? WHERE id=?", (amt, uid))


def dep_record_paid(uid, amt, txn):
    """so 'Total deposited' counts QR top-ups"""
    with conn() as c:
        c.execute("INSERT INTO deposits(user_id,amount,status,created,utr) VALUES(?,?,'paid',?,?)",
                  (uid, amt, int(time.time()), txn or ""))


# ---------- deposits ----------
def dep_create(uid, amt):
    with conn() as c:
        c.execute("UPDATE deposits SET status='cancelled' WHERE user_id=? AND status='pending'", (uid,))
        cur = c.execute("INSERT INTO deposits(user_id,amount,status,created) VALUES(?,?,'pending',?)",
                        (uid, amt, int(time.time())))
        return cur.lastrowid


def dep_get(did):
    with conn() as c:
        return c.execute("SELECT * FROM deposits WHERE id=?", (did,)).fetchone()


def dep_utr_used(utr):
    with conn() as c:
        return c.execute("SELECT 1 FROM deposits WHERE utr=? AND utr<>'' AND status IN ('review','paid')", (utr,)).fetchone() is not None


def dep_submit(did, utr, proof):
    with conn() as c:
        c.execute("UPDATE deposits SET status='review', utr=?, proof=? WHERE id=? AND status='pending'", (utr, proof, did))


def dep_cancel(did, uid):
    with conn() as c:
        c.execute("UPDATE deposits SET status='cancelled' WHERE id=? AND user_id=? AND status='pending'", (did, uid))


def dep_resolve(did, ok):
    """Approve/reject once. Returns the deposit row if this call changed it, else None."""
    with conn() as c:
        c.execute("BEGIN IMMEDIATE")
        d = c.execute("SELECT * FROM deposits WHERE id=? AND status IN ('pending','review')", (did,)).fetchone()
        if not d:
            return None
        c.execute("UPDATE deposits SET status=? WHERE id=?", ("paid" if ok else "rejected", did))
        if ok:
            c.execute("UPDATE users SET balance=balance+? WHERE id=?", (d["amount"], d["user_id"]))
        return d


# ---------- referral commission / claim ----------
def pay_commission(buyer_id, price):
    """Give the referrer a % of the purchase. Returns (referrer_id, amount_in_referrer_currency) or None."""
    try:
        pct = float(get("ref_percent", "0"))
    except ValueError:
        pct = 0
    if pct <= 0:
        return None
    with conn() as c:
        b = c.execute("SELECT ref_by, currency FROM users WHERE id=?", (buyer_id,)).fetchone()
        if not b or not b["ref_by"]:
            return None
        r = c.execute("SELECT id, currency FROM users WHERE id=?", (b["ref_by"],)).fetchone()
        if not r:
            return None
        amt = round(price / rate(b["currency"]) * rate(r["currency"]) * pct / 100, 2)
        if amt <= 0:
            return None
        c.execute("UPDATE users SET ref_balance=ref_balance+? WHERE id=?", (amt, r["id"]))
        return r["id"], amt


def claim_ref(uid):
    with conn() as c:
        c.execute("BEGIN IMMEDIATE")
        u = c.execute("SELECT ref_balance FROM users WHERE id=?", (uid,)).fetchone()
        if not u or u["ref_balance"] <= 0:
            return 0
        amt = u["ref_balance"]
        c.execute("UPDATE users SET balance=balance+?, ref_balance=0 WHERE id=?", (amt, uid))
        return amt


def broadcast_targets():
    with conn() as c:
        return [r["id"] for r in c.execute("SELECT id FROM users WHERE verified=1 AND banned=0")]
