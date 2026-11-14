import os, time, secrets, hmac
from flask import Flask, request, session, redirect, url_for, render_template_string, flash, Response
from datetime import datetime, timezone, timedelta
from jinja2 import DictLoader
import io, csv, threading
import json
import db, bot, backup, gateway
try:
    import segno
except Exception:
    segno = None

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)
ADMIN_USER = os.getenv("ADMIN_USER") or "RGCHEAT"
ADMIN_PASS = os.getenv("ADMIN_PASS") or "909090"
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
.msg{white-space:pre-line;background:#16301f;border:1px solid #245c37;padding:10px;border-radius:8px;margin-bottom:12px}.mu{color:var(--mu);font-size:13px}
.bd{padding:2px 8px;border-radius:99px;background:#232a3b;font-size:12px}.ok{color:#4cd07d}.no{color:#ff6b6b}.wt{color:#ffc857}a.lk{color:var(--ac);text-decoration:none}
.row{display:flex;gap:8px;align-items:center}.row input{flex:1}
</style></head><body>
{% if session.get('ok') %}<nav>
<a href="/" class="{{ 'on' if tab=='home' }}">Dashboard</a><a href="/emojis" class="{{ 'on' if tab=='emojis' }}">Premium Emoji</a>
<a href="/products" class="{{ 'on' if tab=='products' }}">Products</a><a href="/deposits" class="{{ 'on' if tab=='deposits' }}">Deposits</a><a href="/payments" class="{{ 'on' if tab=='payments' }}">QR Payments</a><a href="/find" class="{{ 'on' if tab=='find' }}">Find Order</a><a href="/coupons" class="{{ 'on' if tab=='coupons' }}">Coupons</a>
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
<div class="card stat"><b><a class="lk" href="/payments">{{ s.pend }}</a></b><span>Deposits to review</span></div>
<div class="card stat"><b>{{ s.stock }}</b><span>Keys in stock</span></div>
<div class="card stat"><b>{{ s.o_today }}</b><span>Orders today</span></div><div class="card stat"><b>{{ s.u_today }}</b><span>New users today</span></div></div>
<div class="card"><h3>Bot status</h3><p class="mu">All parts live: shop, order summary, Pay QR + auto payment page, Pay UPI / Pay Binance (manual approve), coupons, wallet top-up, backup/restore, broadcast, referral commission, maintenance mode, login protection.</p></div>{% endblock %}"""

EMOJIS = """{% extends 'base.html' %}{% block body %}<h1>Premium Emoji</h1>
<div class="card"><p class="mu"><b>How to get an emoji ID:</b> open the bot with your admin Telegram account (Premium) and send any premium emoji as a message.
The bot replies with the ID. Paste it below. Leave blank to use the normal emoji. Changes apply in a few seconds.</p></div>
<div class="card"><h3>Premium emoji check</h3><p>Status: <b class="{{ 'no' if gs('emoji_mode')=='blocked' else 'ok' }}">{{ 'BLOCKED by Telegram (normal emoji shown)' if gs('emoji_mode')=='blocked' else 'enabled' }}</b></p>
<p class="mu">Sends one test message to your admin Telegram and tells you exactly why premium emoji do or do not show. You can also send /emojitest to the bot.</p>
<form method="post" action="/emojis/test"><input type="hidden" name="csrf" value="{{ csrf() }}"><button>Test premium emoji now</button></form></div>
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
<div class="card"><h3>Payment Gateway (UPI QR, automatic)</h3>
<p class="mu">Choose the gateway, paste the <b>API token</b> and press <b>Save &amp; Connect</b>. QR is created, payment is detected automatically and the key is delivered / wallet is credited.</p>
<label>Gateway</label><select name="gw_gateway"><option value="paytm" {{ 'selected' if gs('gw_gateway')!='fampay' }}>Paytm</option><option value="fampay" {{ 'selected' if gs('gw_gateway')=='fampay' }}>FamPay</option></select>
<label>API token</label><input name="gw_token" value="{{ gs('gw_token') }}" autocomplete="off" placeholder="paste API key from your gateway">
<label>Gateway Base URL (change this when you move your gateway)</label><input name="gw_base" value="{{ gs('gw_base') or 'https://paymentgateway-0km8.onrender.com' }}">
<label>Webhook signing secret (optional - from gateway dashboard &rarr; Webhooks)</label><input name="gw_webhook_secret" value="{{ gs('gw_webhook_secret') }}" autocomplete="off">
<label>Payment page name (shown to customer)</label><input name="pay_name" value="{{ gs('pay_name') }}">
<label>Payment valid for (minutes)</label><input name="pay_expire" value="{{ gs('pay_expire') }}">
<button type="submit" formaction="/gateway/connect">Save &amp; Connect</button>
<p class="mu">Status: <b class="{{ 'ok' if gs('gw_connected')=='1' else 'no' }}">{{ 'Connected' if gs('gw_connected')=='1' else ('Token saved - press Save & Connect' if gw_on() else 'Not connected') }}</b><br>
Webhook URL to set in your gateway: <code>{{ webhook_url() }}</code></p></div>
<div class="card"><h3>Store screen &amp; sign-up</h3>
<label>Phone number verification at /start</label><select name="verify_on"><option value="1" {{ 'selected' if gs('verify_on')!='0' }}>ON (ask phone number)</option><option value="0" {{ 'selected' if gs('verify_on')=='0' }}>OFF (no phone needed)</option></select>
<label>Shop screen lines (one per line, shown under "Product Lineup")</label><textarea name="shop_bullets" rows="5">{{ gs('shop_bullets') }}</textarea></div>
<div class="card"><h3>Manual payments (UPI / Binance)</h3>
<p class="mu">Customer pays, taps <b>I Have Paid</b>, sends the transaction ID, and YOU get a notification with Approve / Reject.</p>
<label>Pay UPI button (needs the UPI ID in "Payment (deposits)")</label><select name="pay_upi_on"><option value="1" {{ 'selected' if gs('pay_upi_on')=='1' }}>ON</option><option value="0" {{ 'selected' if gs('pay_upi_on')!='1' }}>OFF</option></select>
<label>Pay Binance button</label><select name="pay_binance_on"><option value="1" {{ 'selected' if gs('pay_binance_on')=='1' }}>ON</option><option value="0" {{ 'selected' if gs('pay_binance_on')!='1' }}>OFF</option></select>
<label>Binance payment details shown to customer (Binance Pay ID / UID / wallet address + network). Empty = button hidden.</label>
<textarea name="binance_text" rows="4">{{ gs('binance_text') }}</textarea></div>
<div class="card"><h3>Links</h3><label>Tutorial video link (Watch Guide Video)</label><input name="tutorial_url" value="{{ gs('tutorial_url') }}" placeholder="https://youtube.com/...">
<label>All Update File link</label><input name="update_url" value="{{ gs('update_url') }}" placeholder="https://t.me/... or drive link"></div>
<button>Save settings</button></form>{% endblock %}"""

USERS = """{% extends 'base.html' %}{% block body %}<h1>Users</h1><form class="row" method="get"><input name="q" value="{{ q }}" placeholder="Search ID / name / phone"><button style="margin:0">Search</button></form><br>
<div class="card tw"><table><tr><th>ID</th><th>Name</th><th>Phone</th><th>Balance</th><th>Account type</th><th>Actions</th></tr>
{% for u in rows %}<tr><td>{{ u.id }}</td><td>{{ u.name }}</td><td>{{ u.phone or '-' }}</td><td>{{ u.symbol }}{{ '%.2f'|format(u.balance) }}</td>
<td>{{ u.role }}{{ ' (banned)' if u.banned }}</td><td><form method="post" action="/users/{{ u.id }}" class="row"><input type="hidden" name="csrf" value="{{ csrf() }}">
<input name="amt" placeholder="+100 / -50" style="width:90px;flex:none"><button name="a" value="bal" style="margin:0">Balance</button>
<button name="a" value="role" style="margin:0">{{ 'Make user' if u.role=='reseller' else 'Make reseller' }}</button>
<button name="a" value="ban" class="red" style="margin:0">{{ 'Unban' if u.banned else 'Ban' }}</button></form></td></tr>{% endfor %}</table></div>{% endblock %}"""

PRODUCTS = """{% extends 'base.html' %}{% block body %}<h1>Products</h1>
<p><a class="lk" href="/products/new"><button type="button">+ Add product</button></a></p>
<div class="card tw"><table><tr><th>Name</th><th>Plans</th><th>Stock</th><th>Status</th><th></th></tr>
{% for p in rows %}<tr><td><a class="lk" href="/products/{{ p.id }}">{{ p.name }}</a></td><td>{{ p.nplans }}</td><td>{{ p.stock }}</td>
<td>{{ 'Visible' if p.active else 'Hidden' }}</td><td><a class="lk" href="/products/{{ p.id }}">Open</a></td></tr>{% endfor %}</table></div>{% endblock %}"""

PRODUCT = """{% extends 'base.html' %}{% block body %}<h1>{{ p.name }}</h1>
<div class="card"><h3>Product</h3><form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="edit">
<label>Name</label><input name="name" value="{{ p.name }}"><label>Description</label><input name="descr" value="{{ p.descr }}">
<label>Update group link (Join Telegram button after purchase)</label><input name="link" value="{{ p.link or '' }}" placeholder="https://t.me/yourgroup">
<label>Sort order (small = first)</label><input name="sort" value="{{ p.sort }}">
<label>Visibility</label><select name="active"><option value="1" {{ 'selected' if p.active }}>Visible</option><option value="0" {{ 'selected' if not p.active }}>Hidden</option></select>
<button>Save</button></form>
<form method="post" onsubmit="return confirm('Delete this product, its plans and unsold keys?')"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="del"><button class="red">Delete product</button></form></div>
<div class="card tw"><h3>Plans (prices in INR)</h3><table><tr><th>Duration</th><th>User price</th><th>Reseller price</th><th>Show</th><th>Stock / Sold</th><th></th></tr>
{% for pl in plans %}<tr><form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="plan_id" value="{{ pl.id }}">
<td>{% set pp_ = pl.name|pp %}{% if pp_ %}<input name="dur" value="{{ pp_[0] }}" style="width:70px"> <select name="unit" style="width:90px"><option value="hours" {{ 'selected' if pp_[1]=='hours' }}>Hours</option><option value="days" {{ 'selected' if pp_[1]=='days' }}>Days</option></select>{% else %}<input name="name" value="{{ pl.name }}">{% endif %}</td><td><input name="price" value="{{ pl.price }}" style="width:80px"></td><td><input name="rprice" value="{{ pl.rprice }}" style="width:80px"></td>
<td><select name="active"><option value="1" {{ 'selected' if pl.active }}>Yes</option><option value="0" {{ 'selected' if not pl.active }}>No</option></select></td>
<td>{{ pl.stock }} / {{ pl.sold }}<br><a class="lk" href="/plans/{{ pl.id }}">Manage keys</a></td>
<td><button name="a" value="saveplan" style="margin:0">Save</button> <button name="a" value="delplan" class="red" style="margin:0" onclick="return confirm('Delete plan and unsold keys?')">X</button></td></form></tr>{% endfor %}</table></div>
<div class="card"><h3>Add plans</h3><form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="addplans">
<div id="rows"></div><button type="button" onclick="addRow()" style="margin:6px 0">+ Add another plan</button>
<script>function addRow(){var d=document.createElement('div');d.className='row';d.style.cssText='flex-wrap:wrap;gap:6px;margin:8px 0';
d.innerHTML='<input name="dur" type="number" min="1" step="1" placeholder="Duration" style="width:95px;flex:none" required><select name="unit" style="width:95px;flex:none"><option value="hours">Hours</option><option value="days" selected>Days</option></select><input name="uprice" placeholder="User price" style="width:110px;flex:none" required><input name="rprice" placeholder="Reseller price" style="width:125px;flex:none"><button type="button" class="red" style="margin:0" onclick="this.parentNode.remove()">X</button>';
document.getElementById('rows').appendChild(d)}addRow();</script>
<button>Save plans</button></form></div>{% endblock %}"""

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

PAYMENTS = '{% extends \'base.html\' %}{% block body %}<h1>QR / Manual Payments</h1><form class="row" method="get" action="/payments"><input name="q" value="{{ qs }}" placeholder="Search order ID / txn ID / user ID / name"><button style="margin:0">Search</button></form><br>\n<p>{% for k,l in tabs %}<a class="lk" href="/payments?s={{ k }}" style="margin-right:12px;{{ \'font-weight:bold\' if k==s }}">{{ l }}</a>{% endfor %}</p>\n<div class="card tw"><table><tr><th>Order ID</th><th>User</th><th>Method</th><th>For</th><th>Amount</th><th>Txn ID</th><th>Proof</th><th>Status</th><th>Time</th><th></th></tr>\n{% for p in rows %}<tr><td>{{ p.pay_no }}</td><td>{{ p.user_id }}<br><span class="mu">{{ p.name }}</span></td><td>{{ p.method }}</td><td>{{ p.title }}</td><td>{{ p.symbol }}{{ \'%.2f\'|format(p.amount) }}</td><td>{{ p.txn or \'-\' }}</td>\n<td>{% if p.proof %}<a class="lk" target="_blank" href="/payproof/{{ p.pay_no }}">view</a>{% else %}-{% endif %}</td>\n<td><span class="bd {{ \'ok\' if p.status==\'paid\' else \'no\' if p.status in (\'cancelled\',\'rejected\') else \'wt\' }}">{{ p.status }}</span></td><td>{{ p.created|ts }}</td>\n<td>{% if p.status in (\'pending\',\'expired\',\'review\') %}<form method="post" action="/payments/{{ p.pay_no }}" class="row"><input type="hidden" name="csrf" value="{{ csrf() }}">\n<button name="a" value="ok" style="margin:0" onclick="return confirm(\'Mark as PAID and deliver to the user?\')">Approve</button><button name="a" value="no" class="red" style="margin:0">Reject</button></form>{% endif %}</td></tr>{% endfor %}</table></div>{% endblock %}'
COUPONS = '{% extends \'base.html\' %}{% block body %}<h1>Coupons</h1>\n<div class="card"><h3>Create coupon</h3><p class="mu">A coupon gives a discount on one purchase. Each user can use a coupon once.</p>\n<form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="add">\n<label>Code (letters/numbers)</label><input name="code" required placeholder="RG50">\n<label>Type</label><select name="kind"><option value="percent">Percent off (%)</option><option value="flat">Flat off (INR)</option></select>\n<label>Value</label><input name="value" required placeholder="10">\n<label>Max total uses (0 = unlimited)</label><input name="max_uses" value="0">\n<label>Valid for days (0 = no expiry)</label><input name="days" value="0"><button>Create coupon</button></form></div>\n<div class="card tw"><table><tr><th>Code</th><th>Discount</th><th>Used</th><th>Expires</th><th>Status</th><th></th></tr>\n{% for c in rows %}<tr><td><b>{{ c.code }}</b></td><td>{{ (c.value|string + \'%\') if c.kind==\'percent\' else (\'₹\' + c.value|string) }}</td><td>{{ c.used }} / {{ c.max_uses or \'∞\' }}</td>\n<td>{{ c.expires|ts if c.expires else \'never\' }}</td><td>{{ \'Active\' if c.active else \'Off\' }}</td>\n<td><form method="post" class="row"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="code" value="{{ c.code }}">\n<button name="a" value="toggle" style="margin:0">{{ \'Turn off\' if c.active else \'Turn on\' }}</button><button name="a" value="del" class="red" style="margin:0" onclick="return confirm(\'Delete coupon?\')">Delete</button></form></td></tr>{% endfor %}</table></div>{% endblock %}'
PAYPAGE = '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n<title>{{ shop }} · Payment</title><style>\n*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 50% -10%,#1b2a4a 0,#0a0e17 55%);color:#eaf0ff;font-family:system-ui,Segoe UI,Roboto,sans-serif;display:flex;justify-content:center;padding:18px}\n.card{width:100%;max-width:410px;background:#111827;border:1px solid #223049;border-radius:20px;padding:22px;box-shadow:0 20px 60px #0008;align-self:flex-start;margin-top:10px}\n.top{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}.shop{font-weight:700;font-size:16px}.sec{font-size:12px;color:#7ee0a0;background:#12301f;padding:4px 10px;border-radius:99px}\n.amt{text-align:center;margin:10px 0 4px;font-size:38px;font-weight:800}.sub{text-align:center;color:#8b96b3;font-size:13px;margin-bottom:14px}\n.qr{background:#fff;border-radius:16px;padding:14px;width:240px;height:240px;margin:0 auto;display:flex;align-items:center;justify-content:center}.qr svg{width:100%;height:100%}\n.row{display:flex;justify-content:space-between;gap:10px;padding:10px 0;border-bottom:1px solid #1d2940;font-size:14px}.row span:first-child{color:#8b96b3}.row b{text-align:right;word-break:break-all}\n.btn{display:block;text-align:center;text-decoration:none;background:#3b82f6;color:#fff;padding:13px;border-radius:12px;font-weight:600;margin-top:16px}.btn.g{background:#16a34a}\n.wait{display:flex;align-items:center;justify-content:center;gap:10px;margin-top:16px;color:#ffd166;font-size:14px}.dot{width:10px;height:10px;border-radius:50%;background:#ffd166;animation:p 1s infinite}@keyframes p{50%{opacity:.25}}\n.tm{text-align:center;color:#8b96b3;font-size:13px;margin-top:8px}.ok{width:84px;height:84px;border-radius:50%;background:#16a34a;margin:6px auto 14px;display:flex;align-items:center;justify-content:center;animation:pop .5s}\n@keyframes pop{0%{transform:scale(.3);opacity:0}100%{transform:scale(1);opacity:1}}.ok svg{width:46px;height:46px}.big{text-align:center;font-size:22px;font-weight:800}.bad{background:#dc2626}\n.mu{color:#8b96b3;font-size:12px;text-align:center;margin-top:14px}\n</style></head><body><div class="card">\n<div class="top"><div class="shop">{{ shop }}</div><div class="sec">🔒 Secure UPI</div></div>\n{% if p.status == \'paid\' %}\n<div class="ok"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7"/></svg></div>\n<div class="big">Payment Successful</div><div class="sub">{{ sym }}{{ \'%.2f\'|format(p.pay_amount or p.amount) }} received</div>\n<div class="row"><span>Order ID</span><b>{{ p.pay_no }}</b></div>\n<div class="row"><span>Transaction ID</span><b>{{ p.txn or \'-\' }}</b></div>\n<div class="row"><span>{{ \'Wallet\' if p.kind==\'topup\' else \'Item\' }}</span><b>{{ \'Recharge added to wallet\' if p.kind==\'topup\' else p.title }}</b></div>\n<div class="row"><span>Paid on</span><b>{{ p.paid_at|ts }} IST</b></div>\n<div class="row"><span>Status</span><b style="color:#4ade80">SUCCESS</b></div>\n<p class="sub" style="margin-top:14px">{{ \'Your wallet balance is updated.\' if p.kind==\'topup\' else \'Your key has been sent in Telegram.\' }}</p>\n{% if bot_user %}<a class="btn g" href="https://t.me/{{ bot_user }}">Back to Telegram</a>{% endif %}\n{% elif p.status in (\'expired\',\'cancelled\') %}\n<div class="ok bad"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3.2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></div>\n<div class="big">Payment {{ \'Expired\' if p.status==\'expired\' else \'Cancelled\' }}</div><div class="sub">Order {{ p.pay_no }}<br>If you already paid, it will be added automatically.</div>\n{% if bot_user %}<a class="btn" href="https://t.me/{{ bot_user }}">Back to Telegram</a>{% endif %}\n{% else %}\n<div class="amt">{{ sym }}{{ \'%.2f\'|format(p.pay_amount or p.amount) }}</div><div class="sub">{{ p.title }}</div>\n<div class="qr">{{ qr|safe if qr else \'QR not available\' }}</div>\n<div class="tm">Expires in <b id="t">--:--</b></div>\n<div class="wait"><span class="dot"></span> Waiting for payment…</div>\n{% if p.upi_uri %}<a class="btn" href="{{ p.upi_uri }}">Pay with UPI App</a>{% elif p.pay_url %}<a class="btn" href="{{ p.pay_url }}">Open payment link</a>{% endif %}\n<div class="row" style="margin-top:14px"><span>Order ID</span><b>{{ p.pay_no }}</b></div>\n<p class="mu">Scan with PhonePe, Google Pay, Paytm or any UPI app.<br>Do not close this page — it updates automatically.</p>\n<script>var left={{ left }};function f(){var m=Math.floor(left/60),s=left%60;document.getElementById(\'t\').textContent=(m<10?\'0\':\'\')+m+\':\'+(s<10?\'0\':\'\')+s;if(left<=0){location.reload();return}left--}f();setInterval(f,1000);\nsetInterval(function(){fetch(\'status\').then(function(r){return r.json()}).then(function(j){if(j.status!==\'pending\')location.reload()}).catch(function(){})},3000);</script>\n{% endif %}\n</div></body></html>'

NEWPRODUCT = '{% extends \'base.html\' %}{% block body %}<h1>Add product</h1>\n<div class="card"><form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}">\n<label>Product name</label><input name="name" required placeholder="e.g. Br Mods Pc Emulator">\n<label>Update group link (Join Telegram button after purchase) - optional</label><input name="link" placeholder="https://t.me/yourgroup">\n<h3>Plans</h3><p class="mu">Duration + Hours/Days, then User price and Reseller price (INR). Press <b>+ Add another plan</b> for more. Reseller price empty = same as user price.</p>\n<div id="rows"></div><button type="button" onclick="addRow()" style="margin:6px 0">+ Add another plan</button>\n<script>function addRow(){var d=document.createElement(\'div\');d.className=\'row\';d.style.cssText=\'flex-wrap:wrap;gap:6px;margin:8px 0\';\nd.innerHTML=\'<input name="dur" type="number" min="1" step="1" placeholder="Duration" style="width:95px;flex:none" required><select name="unit" style="width:95px;flex:none"><option value="hours">Hours</option><option value="days" selected>Days</option></select><input name="uprice" placeholder="User price" style="width:110px;flex:none" required><input name="rprice" placeholder="Reseller price" style="width:125px;flex:none"><button type="button" class="red" style="margin:0" onclick="this.parentNode.remove()">X</button>\';\ndocument.getElementById(\'rows\').appendChild(d)}addRow();</script>\n<button>Save product</button></form></div>{% endblock %}'
FIND = '{% extends \'base.html\' %}{% block body %}<h1>Find order</h1>\n<form class="row" method="get"><input name="q" value="{{ q }}" placeholder="Order ID (ORD… / WAL…), transaction ID or user ID" autofocus><button style="margin:0">Find user</button></form><br>\n{% if q and not hits %}<div class="card">Nothing found for <b>{{ q }}</b>.</div>{% endif %}\n{% for h in hits %}<div class="card"><h3>{{ h.kind }}</h3>\n<p><b>Order ID:</b> {{ h.ref }}</p>\n{% for k, v in h.info %}<p class="mu">{{ k }}: <b>{{ v }}</b></p>{% endfor %}\n<p><b>User:</b> {{ h.uname or \'-\' }} · <b>ID:</b> {{ h.uid }} · <b>Username:</b> {{ (\'@\' + h.username) if h.username else \'-\' }}<br><b>Phone:</b> {{ h.phone or \'-\' }} · <b>Wallet:</b> ₹{{ \'%.2f\'|format(h.balance) }}</p>\n<a class="lk" href="/users?q={{ h.uid }}">Open user</a></div>{% endfor %}{% endblock %}'
app.jinja_loader = DictLoader({"find.html": FIND, "newproduct.html": NEWPRODUCT, "payments.html": PAYMENTS, "coupons.html": COUPONS, "backup.html": BACKUP, "broadcast.html": BROADCAST,"products.html": PRODUCTS, "product.html": PRODUCT, "plan.html": PLAN, "deposits.html": DEPOSITS, "orders.html": ORDERS,"base.html": BASE, "login.html": LOGIN, "home.html": HOME, "emojis.html": EMOJIS, "settings.html": SETTINGS, "users.html": USERS})


def csrf():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


IST = timezone(timedelta(hours=5, minutes=30))
def public_url():
    return (bot.PUBLIC_URL or request.host_url.rstrip("/"))


app.jinja_env.globals.update(csrf=csrf, gs=lambda k: db.get(k), gw_on=gateway.configured,
                             webhook_url=lambda: public_url() + "/webhook/gateway")
app.jinja_env.filters["ts"] = lambda t: datetime.fromtimestamp(t or 0, IST).strftime("%d %b %H:%M")


@app.before_request
def guard():
    if request.endpoint in ("health", "static", "pay_page", "pay_status", "gw_webhook"):
        return
    if request.method == "POST" and not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "x")):
        return "Bad request", 400
    if request.endpoint == "login":
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
        s = {"users": c.execute("SELECT COUNT(*) FROM users").fetchone()[0],
             "ver": c.execute("SELECT COUNT(*) FROM users WHERE verified=1").fetchone()[0],
             "orders": c.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
             "bal": c.execute("SELECT COALESCE(SUM(balance),0) FROM users").fetchone()[0],
             "pend": c.execute("SELECT COUNT(*) FROM deposits WHERE status='review'").fetchone()[0] + c.execute("SELECT COUNT(*) FROM pay_orders WHERE status='review'").fetchone()[0],
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
        db.put("emoji_mode", "ok")
        db.emoji_clear()
        with db.conn() as c:
            ids = [r["eid"] for r in c.execute("SELECT eid FROM emojis WHERE eid<>''")]
        bad = bot.emoji_invalid(ids)
        flash("Saved" + (f" - but {len(bad)} ID(s) are not valid in Telegram: " + ", ".join(bad[:5]) if bad else ". Now press 'Test premium emoji now'."))
        return redirect("/emojis")
    with db.conn() as c:
        rows = c.execute("SELECT * FROM emojis ORDER BY rowid").fetchall()
    return page("emojis", rows=rows, tab="emojis")


@app.route("/emojis/test", methods=["POST"])
def emoji_test_route():
    ok, rep = bot.emoji_test()
    flash(("OK: " if ok else "PROBLEM: ") + rep)
    return redirect("/emojis")


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
                if k == "pay_expire" and not (v.isdigit() and 1 <= int(v) <= 60):
                    continue
                if k == "gw_token" and v != db.get("gw_token"):
                    db.put("gw_connected", "0")
                if k == "gw_gateway" and v not in ("paytm", "fampay"):
                    continue
                if k == "gw_base":
                    v = v.rstrip("/")
                    if v and not v.startswith("http"):
                        v = "https://" + v
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


import re


def plan_parts(name):
    """'10 days' -> ('10','days');  anything else -> None (shown as free text)"""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(hours?|hrs?|days?)\s*", name or "", re.I)
    if not m:
        return None
    n = float(m.group(1))
    return (str(int(n)) if n == int(n) else str(n), "hours" if m.group(2).lower().startswith("h") else "days")


def plan_name(n, unit):
    n = num(n)
    return f"{int(n) if n == int(n) else n} {'hours' if unit == 'hours' else 'days'}" if n > 0 else ""


app.jinja_env.filters["pp"] = plan_parts


def parse_plan_rows(f):
    out = []
    for dur, unit, up, rp in zip(f.getlist("dur"), f.getlist("unit"), f.getlist("uprice"), f.getlist("rprice")):
        name, price = plan_name(dur, unit), num(up)
        if name and price > 0:
            out.append((name, price, num(rp)))
    return out


@app.route("/products/new", methods=["GET", "POST"])
def product_new():
    if request.method == "POST":
        f = request.form
        name = f.get("name", "").strip()
        plans = parse_plan_rows(f)
        if not name:
            flash("Enter the product name")
            return redirect("/products/new")
        with db.conn() as c:
            cur = c.execute("INSERT INTO products(name,link) VALUES(?,?)", (name, f.get("link", "").strip()))
            pid = cur.lastrowid
            for n, (pn, pr, rp) in enumerate(plans):
                c.execute("INSERT INTO plans(product_id,name,price,rprice,sort) VALUES(?,?,?,?,?)", (pid, pn, pr, rp, n))
        flash(f"Product added with {len(plans)} plan(s). Now open a plan and add its keys.")
        return redirect(f"/products/{pid}")
    return page("newproduct", tab="products")


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
                c.execute("UPDATE products SET name=?, descr=?, link=?, active=?, sort=? WHERE id=?",
                          (f.get("name", "").strip() or p["name"], f.get("descr", "").strip(), f.get("link", "").strip(), 1 if f.get("active") == "1" else 0, int(num(f.get("sort"))), pid))
                flash("Saved")
            elif a == "del":
                c.execute("DELETE FROM keys WHERE used=0 AND plan_id IN (SELECT id FROM plans WHERE product_id=?)", (pid,))
                c.execute("DELETE FROM plans WHERE product_id=?", (pid,))
                c.execute("DELETE FROM products WHERE id=?", (pid,))
                flash("Product deleted")
                return redirect("/products")
            elif a == "addplans":
                rows_ = parse_plan_rows(f)
                base = c.execute("SELECT COALESCE(MAX(sort),0) FROM plans WHERE product_id=?", (pid,)).fetchone()[0]
                for n, (pn, pr, rp) in enumerate(rows_, 1):
                    c.execute("INSERT INTO plans(product_id,name,price,rprice,sort) VALUES(?,?,?,?,?)", (pid, pn, pr, rp, base + n))
                flash(f"{len(rows_)} plan(s) added" if rows_ else "Enter duration and price")
            elif a == "addplan" and f.get("name", "").strip():
                c.execute("INSERT INTO plans(product_id,name,price,rprice) VALUES(?,?,?,?)",
                          (pid, f["name"].strip(), num(f.get("price")), num(f.get("rprice"))))
                flash("Plan added")
            elif a == "saveplan":
                pname = plan_name(f.get("dur"), f.get("unit")) if f.get("dur") else f.get("name", "").strip()
                c.execute("UPDATE plans SET name=?, price=?, rprice=?, active=? WHERE id=? AND product_id=?",
                          (pname or "Plan", num(f.get("price")), num(f.get("rprice")), 1 if f.get("active") == "1" else 0, int(f.get("plan_id", 0)), pid))
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


# ------------------------------------------------------------------ Part 4: QR payment page, webhook, payments, coupons
@app.route("/pay/<token>")
def pay_page(token):
    p = db.pay_by_token(token)
    if not p:
        return "Payment not found", 404
    u = db.user(p["user_id"])
    exp = int(db.get("pay_expire", "10") or 10) * 60
    left = max(int(p["created"] + exp - time.time()), 0)
    if p["status"] == "pending" and left <= 0:
        db.pay_update(p["pay_no"], status="expired")
        p = db.pay_get(p["pay_no"])
    qr = ""
    if p["status"] == "pending" and segno and (p["upi_uri"] or p["pay_url"]):
        qr = segno.make(p["upi_uri"] or p["pay_url"], error="m").svg_inline(scale=6, border=1, dark="#000", light="#fff")
    return render_template_string(PAYPAGE, p=p, qr=qr, left=left, shop=db.get("pay_name") or db.get("shop_name"),
                                  sym=u["symbol"] if u else "₹", bot_user=bot.BOT_USERNAME["v"])


@app.route("/pay/<token>/status")
def pay_status(token):
    p = db.pay_by_token(token)
    return {"status": p["status"] if p else "none"}


@app.route("/gateway/connect", methods=["POST"])
def gateway_connect():
    f = request.form
    for k in ("gw_gateway", "gw_token", "gw_base", "gw_webhook_secret", "pay_name", "pay_expire"):
        if k not in f:
            continue
        v = f[k].strip()
        if k == "gw_gateway" and v not in ("paytm", "fampay"):
            continue
        if k == "pay_expire" and not (v.isdigit() and 1 <= int(v) <= 60):
            continue
        if k == "gw_base":
            v = v.rstrip("/")
            if v and not v.startswith("http"):
                v = "https://" + v
        db.put(k, v)
    ok, msg = gateway.connect_test()
    db.put("gw_connected", "1" if ok else "0")
    flash(("✅ " if ok else "❌ ") + msg)
    return redirect("/settings")


@app.route("/webhook/gateway", methods=["GET", "POST"])
def gw_webhook():
    if request.method == "GET":
        return "ok"
    raw = request.get_data(as_text=True)
    secret = db.get("gw_webhook_secret").strip()
    signed = False
    if secret:
        if not gateway.verify_signature(secret, request.headers.get("X-Payment-Gateway-Timestamp", "0"),
                                        request.headers.get("X-Payment-Gateway-Signature", ""), raw):
            return "bad signature", 401
        signed = True
    try:
        d = json.loads(raw or "{}")
    except ValueError:
        d = {}
    if not isinstance(d, dict) or d.get("event") != "payment.success" or str(d.get("status", "")).upper() != "SUCCESS":
        return "ok"
    no = str(d.get("order_id") or "")
    p = db.pay_get(no) if no else None
    if not p:
        return "ok"
    txn = str(d.get("transaction_id") or "")
    if signed:
        try:
            paid_amt = float(d.get("amount"))
        except (TypeError, ValueError):
            paid_amt = None
        want = p["pay_amount"] or p["amount"]
        if paid_amt is not None and abs(paid_amt - want) > 0.01:
            return "amount mismatch", 200
        threading.Thread(target=bot.complete_pay, args=(no, txn), daemon=True).start()
    else:
        st, t2, _a = gateway.check(no)
        if st == "paid":
            threading.Thread(target=bot.complete_pay, args=(no, t2 or txn), daemon=True).start()
    return "ok"


@app.route("/find")
def find_page():
    q = request.args.get("q", "").strip()
    return page("find", q=q, hits=db.find_order(q) if q else [], tab="find")


@app.route("/payments")
def payments():
    tabs = [("review", "To review"), ("pending", "Waiting"), ("paid", "Paid"), ("rejected", "Rejected"), ("expired", "Expired"), ("cancelled", "Cancelled"), ("all", "All")]
    st = request.args.get("s", "review")
    q = """SELECT p.*, u.name, u.symbol FROM pay_orders p LEFT JOIN users u ON u.id=p.user_id"""
    qs = request.args.get("q", "").strip()
    conds, args = [], []
    if qs:
        st = "all"
        conds.append("(p.pay_no LIKE ? OR p.txn LIKE ? OR u.name LIKE ? OR CAST(p.user_id AS TEXT)=?)")
        args += [f"%{qs}%", f"%{qs}%", f"%{qs}%", qs]
    elif st != "all":
        conds.append("p.status=?")
        args.append(st)
    with db.conn() as c:
        rows = c.execute(q + (" WHERE " + " AND ".join(conds) if conds else "") + " ORDER BY p.id DESC LIMIT 150", args).fetchall()
    return page("payments", rows=rows, s=st, tabs=tabs, tab="payments", qs=qs)


@app.route("/payments/<no>", methods=["POST"])
def payment_action(no):
    if request.form.get("a") == "ok":
        pp = db.pay_get(no)
        p = bot.complete_pay(no, (pp["txn"] if pp else "") or "ADMIN-" + time.strftime("%H%M%S"))
        flash("Approved and delivered" if p else "Already handled")
    else:
        p = bot.reject_pay(no)
        flash("Rejected, user informed" if p else "Already handled")
    return redirect(request.referrer or "/payments")


@app.route("/payproof/<no>")
def payproof(no):
    p = db.pay_get(no)
    data = bot.fetch_file(p["proof"]) if p and p["proof"] else None
    if not data:
        return "No proof", 404
    return Response(data, mimetype="image/jpeg")


@app.route("/coupons", methods=["GET", "POST"])
def coupons():
    if request.method == "POST":
        a, f = request.form.get("a"), request.form
        code = "".join(ch for ch in f.get("code", "").upper() if ch.isalnum())[:32]
        with db.conn() as c:
            if a == "add" and code:
                kind = "flat" if f.get("kind") == "flat" else "percent"
                val = num(f.get("value"))
                if val <= 0 or (kind == "percent" and val > 100):
                    flash("Invalid value")
                else:
                    days = int(num(f.get("days")))
                    c.execute("INSERT OR REPLACE INTO coupons(code,kind,value,max_uses,used,expires,active,created) VALUES(?,?,?,?,COALESCE((SELECT used FROM coupons WHERE code=?),0),?,1,?)",
                              (code, kind, val, int(num(f.get("max_uses"))), code, int(time.time()) + days * 86400 if days else 0, int(time.time())))
                    flash("Coupon saved")
            elif a == "toggle" and code:
                c.execute("UPDATE coupons SET active=1-active WHERE code=?", (code,))
            elif a == "del" and code:
                c.execute("DELETE FROM coupons WHERE code=?", (code,))
        return redirect("/coupons")
    with db.conn() as c:
        rows = c.execute("SELECT * FROM coupons ORDER BY created DESC").fetchall()
    return page("coupons", rows=rows, tab="coupons")
