import os, time, secrets, hmac
from flask import Flask, request, session, redirect, url_for, render_template_string, flash, Response
from datetime import datetime, timezone, timedelta
from jinja2 import DictLoader
import io, csv, threading
import db, bot, backup

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "")
if not ADMIN_PASS:
    ADMIN_PASS = secrets.token_urlsafe(10)
    print("!!! ADMIN_PASS not set. Temporary admin password for this run:", ADMIN_PASS)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.getenv("RENDER_EXTERNAL_URL", "").startswith("https"),
                  PERMANENT_SESSION_LIFETIME=12 * 3600, MAX_CONTENT_LENGTH=60 * 1024 * 1024)
FAILS = {}  # ip -> [count, locked_until]


def client_ip():
    return (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "?")


@app.after_request
def secure_headers(r):
    r.headers["X-Frame-Options"] = "DENY"
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Referrer-Policy"] = "no-referrer"
    r.headers["Cache-Control"] = "no-store"
    return r

BASE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title or 'Admin' }}</title><style>
:root{--bg:#0b0d12;--card:#141824;--line:#232a3b;--tx:#e8ecf6;--mu:#8b94ad;--ac:#5b7cff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font-family:system-ui,Segoe UI,Roboto,sans-serif}
nav{display:flex;gap:6px;flex-wrap:wrap;padding:12px;background:var(--card);border-bottom:1px solid var(--line);position:sticky;top:0}
nav a{color:var(--mu);text-decoration:none;padding:8px 12px;border-radius:8px;font-size:14px}nav a.on,nav a:hover{background:var(--ac);color:#fff}
main{max-width:980px;margin:0 auto;padding:16px}.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:16px}
h1{font-size:20px;margin:4px 0 14px}h3{margin:0 0 10px}label{display:block;color:var(--mu);font-size:13px;margin:10px 0 4px}
textarea{width:100%;padding:10px;background:#0e1220;border:1px solid var(--line);border-radius:8px;color:var(--tx);font-size:14px;font-family:monospace}
input,select{width:100%;padding:10px;background:#0e1220;border:1px solid var(--line);border-radius:8px;color:var(--tx);font-size:14px}
button{background:var(--ac);color:#fff;border:0;padding:10px 16px;border-radius:8px;font-size:14px;cursor:pointer;margin-top:12px}
button.red{background:#d64545}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
.stat b{font-size:24px;display:block}.stat span{color:var(--mu);font-size:13px}table{width:100%;border-collapse:collapse;font-size:13px}
td,th{padding:8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}.tw{overflow-x:auto}
.msg{background:#16301f;border:1px solid #245c37;padding:10px;border-radius:8px;margin-bottom:12px}.mu{color:var(--mu);font-size:13px}
.bd{padding:2px 8px;border-radius:99px;background:#232a3b;font-size:12px}.ok{color:#4cd07d}.no{color:#ff6b6b}.wt{color:#ffc857}a.lk{color:var(--ac);text-decoration:none}
.row{display:flex;gap:8px;align-items:center}.row input{flex:1}
</style></head><body>
{% if session.get('ok') %}<nav>
<a href="/" class="{{ 'on' if tab=='home' }}">Dashboard</a><a href="/emojis" class="{{ 'on' if tab=='emojis' }}">Premium Emoji</a>
<a href="/products" class="{{ 'on' if tab=='products' }}">Products</a><a href="/deposits" class="{{ 'on' if tab=='deposits' }}">Deposits</a>
<a href="/orders" class="{{ 'on' if tab=='orders' }}">Orders</a><a href="/users" class="{{ 'on' if tab=='users' }}">Users</a>
<a href="/broadcast" class="{{ 'on' if tab=='broadcast' }}">Broadcast</a><a href="/backup" class="{{ 'on' if tab=='backup' }}">Backup</a>
<a href="/settings" class="{{ 'on' if tab=='settings' }}">Settings</a>
<a href="/logout" style="margin-left:auto">Logout</a></nav>{% endif %}
<main>{% for m in get_flashed_messages() %}<div class="msg">{{ m }}</div>{% endfor %}{% block body %}{% endblock %}</main></body></html>"""

LOGIN = """{% extends 'base.html' %}{% block body %}<div class="card" style="max-width:360px;margin:60px auto">
<h1>Admin Login</h1><form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}">
<label>Username</label><input name="u" autocomplete="username"><label>Password</label><input name="p" type="password" autocomplete="current-password">
<button style="width:100%">Login</button></form></div>{% endblock %}"""

HOME = """{% extends 'base.html' %}{% block body %}<h1>Dashboard</h1><div class="grid">
<div class="card stat"><b>{{ s.users }}</b><span>Total users</span></div><div class="card stat"><b>{{ s.ver }}</b><span>Verified</span></div>
<div class="card stat"><b>{{ s.orders }}</b><span>Orders</span></div><div class="card stat"><b>{{ '%.2f'|format(s.bal) }}</b><span>Total wallet balance</span></div>
<div class="card stat"><b><a class="lk" href="/deposits?s=review">{{ s.pend }}</a></b><span>Deposits to review</span></div>
<div class="card stat"><b>{{ s.stock }}</b><span>Keys in stock</span></div>
<div class="card stat"><b>{{ s.o_today }}</b><span>Orders today</span></div><div class="card stat"><b>{{ s.u_today }}</b><span>New users today</span></div></div>
<div class="card"><h3>Bot status</h3><p class="mu">All parts live: shop, deposits, backup/restore, broadcast, referral commission, maintenance mode, login protection.</p></div>{% endblock %}"""

EMOJIS = """{% extends 'base.html' %}{% block body %}<h1>Premium Emoji</h1>
<div class="card"><p class="mu"><b>How to get an emoji ID:</b> open the bot with your admin Telegram account (Premium) and send any premium emoji as a message.
The bot replies with the ID. Paste it below. Leave blank to use the normal emoji. Changes apply in a few seconds.</p></div>
<form method="post" action="/emojis"><input type="hidden" name="csrf" value="{{ csrf() }}"><div class="card tw"><table>
<tr><th>Used in</th><th>Normal emoji</th><th>Premium emoji ID</th><th></th></tr>
{% for e in rows %}<tr><td>{{ e.note }}<br><span class="mu">{{ e.k }}</span></td>
<td><input name="fb_{{ e.k }}" value="{{ e.fallback }}" style="width:70px"></td>
<td><input name="id_{{ e.k }}" value="{{ e.eid }}" placeholder="e.g. 5368324170671202286"></td>
<td><a class="mu" href="/emojis/clear/{{ e.k }}" onclick="return confirm('Remove premium ID?')">clear</a></td></tr>{% endfor %}
</table><button>Save all</button></div></form>{% endblock %}"""

SETTINGS = """{% extends 'base.html' %}{% block body %}<h1>Settings</h1><form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}">
<div class="card"><h3>Store</h3><label>Shop name (main menu title)</label><input name="shop_name" value="{{ gs('shop_name') }}">
<label>Minimum deposit</label><input name="min_dep" value="{{ gs('min_dep') }}"><label>Maximum deposit</label><input name="max_dep" value="{{ gs('max_dep') }}">
<label>Referral reward (when friend verifies phone)</label><input name="ref_reward" value="{{ gs('ref_reward') }}"></div>
<div class="card"><h3>Payment (deposits)</h3><label>UPI ID (India users get a QR for this)</label><input name="upi_id" value="{{ gs('upi_id') }}" placeholder="name@bank">
<label>UPI payee name</label><input name="upi_name" value="{{ gs('upi_name') }}">
<label>Payment instructions for other countries (bKash / bank / crypto etc.)</label><textarea name="pay_other_text" rows="4">{{ gs('pay_other_text') }}</textarea></div>
<div class="card"><h3>Currency rates (1 INR = ?)</h3><p class="mu">Product prices are set in INR. Users in other countries see price × rate.</p>
<div class="grid">{% for c in rate_keys %}<div><label>{{ c }}</label><input name="rate_{{ c }}" value="{{ gs('rate_' ~ c) }}"></div>{% endfor %}</div></div>
<div class="card"><h3>Extras</h3><label>Referral commission % on friend's purchases (0 = off)</label><input name="ref_percent" value="{{ gs('ref_percent') }}">
<label>Low-stock alert at (keys left)</label><input name="low_stock" value="{{ gs('low_stock') }}">
<label>Maintenance mode (users cannot use the bot)</label><select name="maint"><option value="0" {{ 'selected' if gs('maint')!='1' }}>OFF</option><option value="1" {{ 'selected' if gs('maint')=='1' }}>ON</option></select>
<label>Maintenance message</label><input name="maint_text" value="{{ gs('maint_text') }}"></div>
<div class="card"><h3>Support</h3>
<label>Telegram support</label><select name="support_tg_on"><option value="1" {{ 'selected' if gs('support_tg_on')=='1' }}>ON</option><option value="0" {{ 'selected' if gs('support_tg_on')!='1' }}>OFF</option></select>
<label>Telegram username or link</label><input name="support_tg" value="{{ gs('support_tg') }}" placeholder="@username">
<label>WhatsApp support</label><select name="support_wa_on"><option value="1" {{ 'selected' if gs('support_wa_on')=='1' }}>ON</option><option value="0" {{ 'selected' if gs('support_wa_on')!='1' }}>OFF</option></select>
<label>WhatsApp number (with country code)</label><input name="support_wa" value="{{ gs('support_wa') }}" placeholder="919XXXXXXXXX"></div>
<div class="card"><h3>Links</h3><label>Tutorial video link (Watch Guide Video)</label><input name="tutorial_url" value="{{ gs('tutorial_url') }}" placeholder="https://youtube.com/...">
<label>All Update File link</label><input name="update_url" value="{{ gs('update_url') }}" placeholder="https://t.me/... or drive link"></div>
<button>Save settings</button></form>{% endblock %}"""

USERS = """{% extends 'base.html' %}{% block body %}<h1>Users</h1><form class="row" method="get"><input name="q" value="{{ q }}" placeholder="Search ID / name / phone"><button style="margin:0">Search</button></form><br>
<div class="card tw"><table><tr><th>ID</th><th>Name</th><th>Phone</th><th>Balance</th><th>Role</th><th>Actions</th></tr>
{% for u in rows %}<tr><td>{{ u.id }}</td><td>{{ u.name }}</td><td>{{ u.phone or '-' }}</td><td>{{ u.symbol }}{{ '%.2f'|format(u.balance) }}</td>
<td>{{ u.role }}{{ ' (banned)' if u.banned }}</td><td><form method="post" action="/users/{{ u.id }}" class="row"><input type="hidden" name="csrf" value="{{ csrf() }}">
<input name="amt" placeholder="+100 / -50" style="width:90px;flex:none"><button name="a" value="bal" style="margin:0">Balance</button>
<button name="a" value="role" style="margin:0">{{ 'Make user' if u.role=='reseller' else 'Make reseller' }}</button>
<button name="a" value="ban" class="red" style="margin:0">{{ 'Unban' if u.banned else 'Ban' }}</button></form></td></tr>{% endfor %}</table></div>{% endblock %}"""

PRODUCTS = """{% extends 'base.html' %}{% block body %}<h1>Products</h1>
<div class="card"><h3>Add product</h3><form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="add">
<label>Name</label><input name="name" required><label>Description (optional)</label><input name="descr"><button>Add product</button></form></div>
<div class="card tw"><table><tr><th>Name</th><th>Plans</th><th>Stock</th><th>Status</th><th></th></tr>
{% for p in rows %}<tr><td><a class="lk" href="/products/{{ p.id }}">{{ p.name }}</a></td><td>{{ p.nplans }}</td><td>{{ p.stock }}</td>
<td>{{ 'Visible' if p.active else 'Hidden' }}</td><td><a class="lk" href="/products/{{ p.id }}">Open</a></td></tr>{% endfor %}</table></div>{% endblock %}"""

PRODUCT = """{% extends 'base.html' %}{% block body %}<h1>{{ p.name }}</h1>
<div class="card"><h3>Product</h3><form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="edit">
<label>Name</label><input name="name" value="{{ p.name }}"><label>Description</label><input name="descr" value="{{ p.descr }}">
<label>Sort order (small = first)</label><input name="sort" value="{{ p.sort }}">
<label>Visibility</label><select name="active"><option value="1" {{ 'selected' if p.active }}>Visible</option><option value="0" {{ 'selected' if not p.active }}>Hidden</option></select>
<button>Save</button></form>
<form method="post" onsubmit="return confirm('Delete this product, its plans and unsold keys?')"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="del"><button class="red">Delete product</button></form></div>
<div class="card tw"><h3>Plans (prices in INR)</h3><table><tr><th>Plan name</th><th>Price</th><th>Reseller price</th><th>Show</th><th>Stock / Sold</th><th></th></tr>
{% for pl in plans %}<tr><form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="plan_id" value="{{ pl.id }}">
<td><input name="name" value="{{ pl.name }}"></td><td><input name="price" value="{{ pl.price }}" style="width:80px"></td><td><input name="rprice" value="{{ pl.rprice }}" style="width:80px"></td>
<td><select name="active"><option value="1" {{ 'selected' if pl.active }}>Yes</option><option value="0" {{ 'selected' if not pl.active }}>No</option></select></td>
<td>{{ pl.stock }} / {{ pl.sold }}<br><a class="lk" href="/plans/{{ pl.id }}">Manage keys</a></td>
<td><button name="a" value="saveplan" style="margin:0">Save</button> <button name="a" value="delplan" class="red" style="margin:0" onclick="return confirm('Delete plan and unsold keys?')">X</button></td></form></tr>{% endfor %}</table></div>
<div class="card"><h3>Add plan</h3><form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="addplan">
<label>Plan name (e.g. 30 Days)</label><input name="name" required><label>Price (INR)</label><input name="price" required><label>Reseller price (INR, 0 = same as price)</label><input name="rprice" value="0">
<button>Add plan</button></form></div>{% endblock %}"""

PLAN = """{% extends 'base.html' %}{% block body %}<h1>{{ pl.pname }} · {{ pl.name }}</h1>
<p class="mu"><a class="lk" href="/products/{{ pl.product_id }}">← back to product</a> · In stock: <b>{{ pl.stock }}</b></p>
<div class="card"><h3>Add keys</h3><form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="add">
<label>One key per line (duplicates are skipped)</label><textarea name="keys" rows="8" required></textarea><button>Add keys</button></form></div>
<div class="card tw"><h3>Unsold keys (first 200)</h3><table>{% for k in keys %}<tr><td><code>{{ k.code }}</code></td><td>
<form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="delkey"><input type="hidden" name="kid" value="{{ k.id }}"><button class="red" style="margin:0">Delete</button></form></td></tr>{% endfor %}</table>
{% if keys %}<form method="post" onsubmit="return confirm('Delete ALL unsold keys of this plan?')"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="clear"><button class="red">Delete all unsold keys</button></form>{% endif %}</div>{% endblock %}"""

DEPOSITS = """{% extends 'base.html' %}{% block body %}<h1>Deposits</h1>
<p>{% for k,l in tabs %}<a class="lk" href="/deposits?s={{ k }}" style="margin-right:12px;{{ 'font-weight:bold' if k==s }}">{{ l }}</a>{% endfor %}</p>
<div class="card tw"><table><tr><th>#</th><th>User</th><th>Amount</th><th>UTR</th><th>Proof</th><th>Status</th><th>Time</th><th></th></tr>
{% for d in rows %}<tr><td>{{ d.id }}</td><td>{{ d.user_id }}<br><span class="mu">{{ d.name }}</span></td><td>{{ d.symbol }}{{ '%.2f'|format(d.amount) }}</td><td>{{ d.utr or '-' }}</td>
<td>{% if d.proof %}<a class="lk" target="_blank" href="/proof/{{ d.id }}">view</a>{% else %}-{% endif %}</td><td><span class="bd {{ 'ok' if d.status=='paid' else 'no' if d.status in ('rejected','cancelled') else 'wt' }}">{{ d.status }}</span></td><td>{{ d.created|ts }}</td>
<td>{% if d.status in ('pending','review') %}<form method="post" action="/deposits/{{ d.id }}" class="row"><input type="hidden" name="csrf" value="{{ csrf() }}">
<button name="a" value="ok" style="margin:0" onclick="return confirm('Credit {{ d.symbol }}{{ d.amount }} to user?')">Approve</button><button name="a" value="no" class="red" style="margin:0">Reject</button></form>{% endif %}</td></tr>{% endfor %}</table></div>{% endblock %}"""

ORDERS = """{% extends 'base.html' %}{% block body %}<h1>Orders</h1><p><a class="lk" href="/orders.csv">Export all as CSV</a></p><form class="row" method="get"><input name="q" value="{{ q }}" placeholder="User ID or order number"><button style="margin:0">Search</button></form><br>
<div class="card tw"><table><tr><th>Order</th><th>User</th><th>Product</th><th>Price</th><th>Key</th><th>Time</th></tr>
{% for o in rows %}<tr><td>{{ o.order_no }}</td><td>{{ o.user_id }}</td><td>{{ o.product }} · {{ o.plan }}</td><td>{{ o.price }}</td><td><code>{{ o.key }}</code></td><td>{{ o.created|ts }}</td></tr>{% endfor %}</table></div>{% endblock %}"""

BACKUP = """{% extends 'base.html' %}{% block body %}<h1>Backup &amp; Restore</h1>
<div class="card"><h3>Status</h3><p>GitHub backup: <b class="{{ 'ok' if gh else 'no' }}">{{ 'configured' if gh else 'NOT configured' }}</b><br>
Last successful backup: <b>{{ st.last_ok|ts if st.last_ok else 'never' }}</b> {% if st.size %}({{ (st.size/1024)|round(1) }} KB){% endif %}<br>
{% if st.last_err %}<span class="no">Last error: {{ st.last_err }}</span>{% endif %}</p>
{% if not gh %}<p class="mu">Add env vars on Render: <b>GH_TOKEN</b> (fine-grained token, Contents: read &amp; write), <b>GH_REPO</b> (e.g. yourname/rg-backup — keep it PRIVATE). Without it, data is lost when Render restarts.</p>{% endif %}
<form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}"><button name="a" value="now">Backup now</button>
<button name="a" value="tg">Backup now + send to my Telegram</button></form></div>
<div class="card"><h3>Download</h3><a class="lk" href="/backup/download">Download database file (.db.gz)</a></div>
<div class="card"><h3>Restore</h3><p class="mu">Upload a .db or .db.gz backup. This REPLACES all current data.</p>
<form method="post" enctype="multipart/form-data" onsubmit="return confirm('Replace ALL current data with this backup?')"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="restore">
<input type="file" name="f" required><button class="red">Restore</button></form></div>{% endblock %}"""

BROADCAST = """{% extends 'base.html' %}{% block body %}<h1>Broadcast</h1>
<div class="card"><form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}">
<label>Message (Telegram HTML allowed: &lt;b&gt;bold&lt;/b&gt;, &lt;i&gt;italic&lt;/i&gt;, &lt;code&gt;code&lt;/code&gt;)</label><textarea name="text" rows="7" required></textarea>
<label>Send to</label><select name="to"><option value="me">Only me (test)</option><option value="all">All verified users</option></select>
<button>Send</button></form>{% if last %}<p class="mu">Last broadcast: {{ last }}</p>{% endif %}</div>{% endblock %}"""

app.jinja_loader = DictLoader({"backup.html": BACKUP, "broadcast.html": BROADCAST,"products.html": PRODUCTS, "product.html": PRODUCT, "plan.html": PLAN, "deposits.html": DEPOSITS, "orders.html": ORDERS,"base.html": BASE, "login.html": LOGIN, "home.html": HOME, "emojis.html": EMOJIS, "settings.html": SETTINGS, "users.html": USERS})


def csrf():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


IST = timezone(timedelta(hours=5, minutes=30))
app.jinja_env.globals.update(csrf=csrf, gs=lambda k: db.get(k))
app.jinja_env.filters["ts"] = lambda t: datetime.fromtimestamp(t or 0, IST).strftime("%d %b %H:%M")


@app.before_request
def guard():
    if request.method == "POST" and not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "x")):
        return "Bad request", 400
    if request.endpoint in ("login", "health", "static"):
        return
    if not session.get("ok"):
        return redirect(url_for("login"))


def page(name, **kw):
    return render_template_string("{% extends '" + name + ".html' %}", **kw)


@app.route("/health")
def health():
    return "ok"


@app.route("/login", methods=["GET", "POST"])
def login():
    ip = client_ip()
    f = FAILS.get(ip, [0, 0])
    if request.method == "POST":
        if f[1] > time.time():
            flash(f"Too many attempts. Try again in {int((f[1] - time.time()) // 60) + 1} min.")
            return page("login", title="Login")
        ok = hmac.compare_digest(request.form.get("u", ""), ADMIN_USER) & hmac.compare_digest(request.form.get("p", ""), ADMIN_PASS)
        if ok:
            FAILS.pop(ip, None)
            session.clear()
            session["ok"] = True
            session.permanent = True
            return redirect("/")
        f[0] += 1
        if f[0] >= 5:
            f = [0, time.time() + 900]
        FAILS[ip] = f
        time.sleep(1.5)
        flash("Wrong username or password")
    return page("login", title="Login")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/")
def home():
    day0 = int(datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    with db.conn() as c:
        s = {"users.html": c.execute("SELECT COUNT(*) FROM users").fetchone()[0],
             "ver": c.execute("SELECT COUNT(*) FROM users WHERE verified=1").fetchone()[0],
             "orders": c.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
             "bal": c.execute("SELECT COALESCE(SUM(balance),0) FROM users").fetchone()[0],
             "pend": c.execute("SELECT COUNT(*) FROM deposits WHERE status='review'").fetchone()[0],
             "stock": c.execute("SELECT COUNT(*) FROM keys WHERE used=0").fetchone()[0],
             "o_today": c.execute("SELECT COUNT(*) FROM orders WHERE created>=?", (day0,)).fetchone()[0],
             "u_today": c.execute("SELECT COUNT(*) FROM users WHERE joined>=?", (day0,)).fetchone()[0]}
    return page("home", s=s, tab="home")


@app.route("/emojis", methods=["GET", "POST"])
def emojis():
    if request.method == "POST":
        with db.conn() as c:
            for r in c.execute("SELECT k FROM emojis").fetchall():
                k = r["k"]
                eid = request.form.get("id_" + k, "").strip()
                if eid and not eid.isdigit():
                    continue
                c.execute("UPDATE emojis SET eid=?, fallback=? WHERE k=?", (eid, request.form.get("fb_" + k, "").strip() or "▫️", k))
        db.emoji_clear()
        flash("Saved")
        return redirect("/emojis")
    with db.conn() as c:
        rows = c.execute("SELECT * FROM emojis ORDER BY rowid").fetchall()
    return page("emojis", rows=rows, tab="emojis")


@app.route("/emojis/clear/<k>")
def emoji_clear(k):
    with db.conn() as c:
        c.execute("UPDATE emojis SET eid='' WHERE k=?", (k,))
    db.emoji_clear()
    return redirect("/emojis")


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        for k in db.SETTINGS_DEFAULTS:
            if k in request.form:
                v = request.form[k].strip()
                if k in ("min_dep", "max_dep") and not v.isdigit():
                    continue
                if k == "low_stock" and not v.isdigit():
                    continue
                if k == "ref_percent":
                    try:
                        if not 0 <= float(v) <= 100:
                            continue
                    except ValueError:
                        continue
                if k.startswith("rate_"):
                    try:
                        if float(v) <= 0:
                            continue
                    except ValueError:
                        continue
                db.put(k, v)
        flash("Saved")
        return redirect("/settings")
    return page("settings", tab="settings", rate_keys=list(db.RATES))


@app.route("/users")
def users():
    q = request.args.get("q", "").strip()
    with db.conn() as c:
        if q:
            like = f"%{q}%"
            rows = c.execute("SELECT * FROM users WHERE CAST(id AS TEXT) LIKE ? OR name LIKE ? OR phone LIKE ? ORDER BY joined DESC LIMIT 50", (like, like, like)).fetchall()
        else:
            rows = c.execute("SELECT * FROM users ORDER BY joined DESC LIMIT 50").fetchall()
    return page("users", rows=rows, q=q, tab="users")


@app.route("/users/<int:uid>", methods=["POST"])
def user_action(uid):
    a = request.form.get("a")
    with db.conn() as c:
        if a == "bal":
            try:
                amt = float(request.form.get("amt", "0"))
                c.execute("UPDATE users SET balance=balance+? WHERE id=?", (amt, uid))
            except ValueError:
                flash("Invalid amount")
        elif a == "role":
            c.execute("UPDATE users SET role=CASE role WHEN 'reseller' THEN 'user' ELSE 'reseller' END WHERE id=?", (uid,))
        elif a == "ban":
            c.execute("UPDATE users SET banned=1-banned WHERE id=?", (uid,))
    return redirect(request.referrer or "/users")


def num(x, default=0.0):
    try:
        return max(float(x), 0.0)
    except (TypeError, ValueError):
        return default


@app.route("/products", methods=["GET", "POST"])
def products():
    if request.method == "POST" and request.form.get("name", "").strip():
        with db.conn() as c:
            c.execute("INSERT INTO products(name,descr) VALUES(?,?)", (request.form["name"].strip(), request.form.get("descr", "").strip()))
        flash("Product added")
        return redirect("/products")
    return page("products", rows=db.products(False), tab="products")


@app.route("/products/<int:pid>", methods=["GET", "POST"])
def product_page(pid):
    p = db.product(pid)
    if not p:
        return redirect("/products")
    if request.method == "POST":
        a, f = request.form.get("a"), request.form
        with db.conn() as c:
            if a == "edit":
                c.execute("UPDATE products SET name=?, descr=?, active=?, sort=? WHERE id=?",
                          (f.get("name", "").strip() or p["name"], f.get("descr", "").strip(), 1 if f.get("active") == "1" else 0, int(num(f.get("sort"))), pid))
                flash("Saved")
            elif a == "del":
                c.execute("DELETE FROM keys WHERE used=0 AND plan_id IN (SELECT id FROM plans WHERE product_id=?)", (pid,))
                c.execute("DELETE FROM plans WHERE product_id=?", (pid,))
                c.execute("DELETE FROM products WHERE id=?", (pid,))
                flash("Product deleted")
                return redirect("/products")
            elif a == "addplan" and f.get("name", "").strip():
                c.execute("INSERT INTO plans(product_id,name,price,rprice) VALUES(?,?,?,?)",
                          (pid, f["name"].strip(), num(f.get("price")), num(f.get("rprice"))))
                flash("Plan added")
            elif a == "saveplan":
                c.execute("UPDATE plans SET name=?, price=?, rprice=?, active=? WHERE id=? AND product_id=?",
                          (f.get("name", "").strip(), num(f.get("price")), num(f.get("rprice")), 1 if f.get("active") == "1" else 0, int(f.get("plan_id", 0)), pid))
                flash("Plan saved")
            elif a == "delplan":
                plid = int(f.get("plan_id", 0))
                c.execute("DELETE FROM keys WHERE plan_id=? AND used=0", (plid,))
                c.execute("DELETE FROM plans WHERE id=? AND product_id=?", (plid, pid))
                flash("Plan deleted")
        return redirect(f"/products/{pid}")
    return page("product", p=p, plans=db.plans_of(pid, False), tab="products")


@app.route("/plans/<int:plid>", methods=["GET", "POST"])
def plan_page(plid):
    pl = db.plan(plid)
    if not pl:
        return redirect("/products")
    if request.method == "POST":
        a = request.form.get("a")
        if a == "add":
            n = db.add_keys(plid, request.form.get("keys", ""))
            flash(f"{n} key(s) added")
        elif a == "delkey":
            with db.conn() as c:
                c.execute("DELETE FROM keys WHERE id=? AND plan_id=? AND used=0", (int(request.form.get("kid", 0)), plid))
        elif a == "clear":
            with db.conn() as c:
                c.execute("DELETE FROM keys WHERE plan_id=? AND used=0", (plid,))
            flash("Unsold keys deleted")
        return redirect(f"/plans/{plid}")
    with db.conn() as c:
        keys = c.execute("SELECT id, code FROM keys WHERE plan_id=? AND used=0 ORDER BY id LIMIT 200", (plid,)).fetchall()
    return page("plan", pl=pl, keys=keys, tab="products")


@app.route("/deposits")
def deposits():
    tabs = [("review", "To review"), ("pending", "Waiting for user"), ("paid", "Approved"), ("rejected", "Rejected"), ("cancelled", "Cancelled")]
    st = request.args.get("s", "review")
    if st not in dict(tabs):
        st = "review"
    with db.conn() as c:
        rows = c.execute("""SELECT d.*, u.name, u.symbol FROM deposits d LEFT JOIN users u ON u.id=d.user_id
                            WHERE d.status=? ORDER BY d.id DESC LIMIT 100""", (st,)).fetchall()
    return page("deposits", rows=rows, s=st, tabs=tabs, tab="deposits")


@app.route("/deposits/<int:did>", methods=["POST"])
def deposit_action(did):
    d = bot.approve_deposit(did, request.form.get("a") == "ok")
    flash("Done" if d else "Already handled")
    return redirect(request.referrer or "/deposits")


@app.route("/proof/<int:did>")
def proof(did):
    d = db.dep_get(did)
    data = bot.fetch_file(d["proof"]) if d and d["proof"] else None
    if not data:
        return "No proof", 404
    return Response(data, mimetype="image/jpeg")


@app.route("/orders")
def orders():
    q = request.args.get("q", "").strip()
    with db.conn() as c:
        if q:
            rows = c.execute("SELECT * FROM orders WHERE CAST(user_id AS TEXT)=? OR order_no LIKE ? ORDER BY id DESC LIMIT 200", (q, f"%{q}%")).fetchall()
        else:
            rows = c.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 200").fetchall()
    return page("orders", rows=rows, q=q, tab="orders")


@app.route("/backup", methods=["GET", "POST"])
def backup_page():
    if request.method == "POST":
        a = request.form.get("a")
        if a in ("now", "tg"):
            ok, msg = backup.run_now((lambda b: bot.send_doc_admin("backup_" + time.strftime("%Y%m%d_%H%M") + ".db.gz", b)) if a == "tg" else None)
            flash(msg)
        elif a == "restore":
            f = request.files.get("f")
            if f and backup.restore_bytes(f.read()):
                db.init()
                db.emoji_clear()
                flash("Restored successfully")
            else:
                flash("Restore failed: not a valid backup file")
        return redirect("/backup")
    return page("backup", st=backup.STATUS, gh=backup.enabled(), tab="backup")


@app.route("/backup/download")
def backup_download():
    return Response(backup.snapshot(), mimetype="application/gzip",
                    headers={"Content-Disposition": "attachment; filename=rg_backup_" + time.strftime("%Y%m%d_%H%M") + ".db.gz"})


BC = {"last": ""}


@app.route("/broadcast", methods=["GET", "POST"])
def broadcast_page():
    if request.method == "POST":
        text = request.form.get("text", "").strip()
        if text:
            ids = None if request.form.get("to") == "all" else [bot.ADMIN_ID]
            n = len(ids or db.broadcast_targets())
            BC["last"] = f"sending to {n} user(s)..."

            def done(ok, fail):
                BC["last"] = f"{time.strftime('%H:%M')} - delivered {ok}, failed {fail}"
            bot.broadcast(text, ids, done)
            flash(f"Broadcast started for {n} user(s)")
        return redirect("/broadcast")
    return page("broadcast", last=BC["last"], tab="broadcast")


@app.route("/orders.csv")
def orders_csv():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["order_no", "user_id", "product", "plan", "price", "key", "time"])
    with db.conn() as c:
        for o in c.execute("SELECT * FROM orders ORDER BY id DESC"):
            w.writerow([o["order_no"], o["user_id"], o["product"], o["plan"], o["price"], o["key"], o["created"]])
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=orders.csv"})
