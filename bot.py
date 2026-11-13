import os, io, json, time, threading, traceback, html
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor
import requests
import db, gateway

try:
    import segno
except Exception:  # QR is optional
    segno = None

TOKEN = os.getenv("BOT_TOKEN", "8880096522:AAG5T6A0yj0goJ2XKw2YSJ7RgEgsPf-wncs")
ADMIN_ID = int(os.getenv("ADMIN_ID", "6739795427") or 0)
API = f"https://api.telegram.org/bot{TOKEN}/"
S = requests.Session()
IST = timezone(timedelta(hours=5, minutes=30))
BOT_USERNAME = {"v": ""}
PUBLIC_URL = (os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")


# ------------------------------------------------------------------ API helpers
def _strip(markup):
    """remove premium-icon / colour fields (fallback if Telegram rejects them)"""
    if not markup:
        return markup
    for row in markup.get("inline_keyboard", []):
        for b in row:
            b.pop("icon_custom_emoji_id", None)
            b.pop("style", None)
    return markup


def api(method, **p):
    if "reply_markup" in p and p["reply_markup"] is not None and not isinstance(p["reply_markup"], str):
        p["reply_markup"] = json.dumps(p["reply_markup"])
    p = {k: v for k, v in p.items() if v is not None}
    try:
        r = S.post(API + method, data=p, timeout=60).json()
    except Exception as e:
        return {"ok": False, "description": str(e)}
    if not r.get("ok") and "reply_markup" in p and "not modified" not in r.get("description", ""):
        d = r.get("description", "").lower()
        if any(x in d for x in ("emoji", "style", "button", "unsupported", "field")):
            m = _strip(json.loads(p["reply_markup"]))
            p["reply_markup"] = json.dumps(m)
            try:
                r = S.post(API + method, data=p, timeout=60).json()
            except Exception as e:
                return {"ok": False, "description": str(e)}
    return r


def raw(method, **p):
    """API call WITHOUT the automatic emoji fallback (used for diagnostics)"""
    if "reply_markup" in p and p["reply_markup"] is not None and not isinstance(p["reply_markup"], str):
        p["reply_markup"] = json.dumps(p["reply_markup"])
    p = {k: v for k, v in p.items() if v is not None}
    try:
        return S.post(API + method, data=p, timeout=60).json()
    except Exception as e:
        return {"ok": False, "description": str(e)}


def emoji_invalid(ids):
    """returns the IDs that Telegram says do not exist (empty list if it cannot check)"""
    ids = [i for i in ids if i]
    if not ids:
        return []
    r = raw("getCustomEmojiStickers", custom_emoji_ids=json.dumps(ids[:200]))
    if not r.get("ok"):
        return []
    good = {x.get("custom_emoji_id") for x in r.get("result", [])}
    return [i for i in ids if i not in good]


def emoji_test():
    """Sends ONE test message to the admin with a premium emoji in the text and on a button,
    then checks what Telegram really accepted. Returns (ok, report_text)."""
    with db.conn() as c:
        rows = [(r["k"], r["fallback"], r["eid"]) for r in c.execute("SELECT * FROM emojis WHERE eid<>''")]
    if not rows:
        return False, "No premium emoji ID is saved yet. Add at least one ID in Premium Emoji first."
    if not ADMIN_ID:
        return False, "ADMIN_ID is not set."
    bad = emoji_invalid([r[2] for r in rows])
    good = [r for r in rows if r[2] not in bad]
    out = []
    if bad:
        names = ", ".join(r[0] for r in rows if r[2] in bad)
        out.append(f"Invalid ID (Telegram does not know it): {names}. Send the emoji to the bot again and copy the new ID.")
    if not good:
        return False, "\n".join(out)
    fb, eid = good[0][1], good[0][2]
    kb = {"inline_keyboard": [[{"text": "Premium emoji test", "icon_custom_emoji_id": eid, "callback_data": "noop"}]]}
    r = raw("sendMessage", chat_id=ADMIN_ID, parse_mode="HTML", reply_markup=kb,
            text=f'Premium emoji test <tg-emoji emoji-id="{eid}">{fb}</tg-emoji> (this message deletes itself)')
    if not r.get("ok"):
        why = r.get("description", "")
        if "chat not found" in why.lower() or "blocked" in why.lower() or "forbidden" in why.lower():
            return False, "Could not message the admin. Open the bot with the ADMIN account and send /start first."
        d = why.lower()
        if "emoji" in d or "button" in d or "field" in d:
            db.put("emoji_mode", "blocked")
            db.emoji_clear()
            return False, ("Telegram REJECTED the premium emoji: " + why + "\n" + BLOCKED_HELP)
        return False, "Test failed: " + why
    msg = r["result"]
    text_ok = any(e.get("type") == "custom_emoji" for e in (msg.get("entities") or []))
    btn_ok = any(bt.get("icon_custom_emoji_id") for row in (msg.get("reply_markup") or {}).get("inline_keyboard", []) for bt in row)
    threading.Timer(20, lambda: api("deleteMessage", chat_id=ADMIN_ID, message_id=msg["message_id"])).start()
    if text_ok or btn_ok:
        db.put("emoji_mode", "ok")
        db.emoji_clear()
        out.insert(0, f"Premium emoji WORK. Text: {'yes' if text_ok else 'no'} · Buttons: {'yes' if btn_ok else 'no'}.")
        return True, "\n".join(out)
    db.put("emoji_mode", "blocked")
    db.emoji_clear()
    out.insert(0, "Telegram accepted the message but REMOVED the premium emoji.\n" + BLOCKED_HELP)
    return False, "\n".join(out)


BLOCKED_HELP = ("Reason: Telegram lets a bot show premium emoji only if the account that OWNS the bot "
                "(the account that created it in @BotFather) has Telegram Premium, or the bot has a username bought on Fragment. "
                "Premium on your admin account is not enough when the bot was created by a different account. "
                "Until that is fixed the bot shows normal emoji everywhere, so nothing breaks.")


def send(chat, text, kb=None):
    return api("sendMessage", chat_id=chat, text=text, parse_mode="HTML", reply_markup=kb,
               link_preview_options=json.dumps({"is_disabled": True}))


def show(chat, mid, text, kb=None, photo=False):
    if photo:
        api("deleteMessage", chat_id=chat, message_id=mid)
        send(chat, text, kb)
        return
    r = api("editMessageText", chat_id=chat, message_id=mid, text=text, parse_mode="HTML", reply_markup=kb,
            link_preview_options=json.dumps({"is_disabled": True}))
    if not r.get("ok") and "not modified" not in r.get("description", ""):
        send(chat, text, kb)


def esc(x):
    return html.escape(str(x if x is not None else ""))


def api_file(method, files, **p):
    if "reply_markup" in p and p["reply_markup"] is not None and not isinstance(p["reply_markup"], str):
        p["reply_markup"] = json.dumps(p["reply_markup"])
    p = {k: v for k, v in p.items() if v is not None}
    try:
        r = S.post(API + method, data=p, files=files, timeout=60).json()
        if not r.get("ok") and "reply_markup" in p and "emoji" in r.get("description", "").lower() + r.get("description", "").lower():
            p["reply_markup"] = json.dumps(_strip(json.loads(p["reply_markup"])))
            files = {k: (v[0], v[1]) for k, v in files.items()}
            r = S.post(API + method, data=p, files=files, timeout=60).json()
        return r
    except Exception as e:
        return {"ok": False, "description": str(e)}


def fetch_file(file_id):
    r = api("getFile", file_id=file_id)
    path = r.get("result", {}).get("file_path")
    if not path:
        return None
    try:
        return S.get(f"https://api.telegram.org/file/bot{TOKEN}/{path}", timeout=60).content
    except Exception:
        return None


def ans(cq, text=None, alert=False):
    api("answerCallbackQuery", callback_query_id=cq["id"], text=text, show_alert="true" if alert else None)


# ------------------------------------------------------------------ UI helpers
def E(key):
    fb, eid = db.emoji(key)
    return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>' if eid else fb


def B(text, cb=None, url=None, style=None, ek=None):
    fb, eid = db.emoji(ek) if ek else ("", "")
    b = {}
    if eid:
        b["text"] = text
        b["icon_custom_emoji_id"] = eid
    else:
        b["text"] = (fb + " " + text).strip()
    if cb:
        b["callback_data"] = cb
    if url:
        b["url"] = url
    if style:
        b["style"] = style  # primary = blue, success = green, danger = red
    return b


def KB(*rows):
    return {"inline_keyboard": [list(r) for r in rows]}


def back_btn():
    return B("Back to Main", cb="menu", style="danger", ek="back")


def fmt(u, x):
    return f"{u['symbol']}{x:.2f} {u['currency']}"


def ist(ts, f="%b %d · %H:%M IST"):
    return datetime.fromtimestamp(ts, IST).strftime(f)


def link(v, kind):
    v = (v or "").strip()
    if not v:
        return None
    if kind == "tg":
        if v.startswith("http"):
            return v
        return "https://t.me/" + v.lstrip("@")
    if kind == "wa":
        if v.startswith("http"):
            return v
        return "https://wa.me/" + "".join(ch for ch in v if ch.isdigit())
    return v if v.startswith("http") else "https://" + v


# ------------------------------------------------------------------ screens
def menu_screen(u):
    name = db.get("shop_name", "RG CHEAT SHOP")
    text = (
        f"{E('top')} ━━ <b>{name}</b> ━━ {E('top')}\n\n"
        f"{E('party')} Welcome back, <b><i>{esc(u['name'])}</i></b>\n\n"
        f"{E('bars')} ━ <b>STORE HIGHLIGHTS</b> ━ {E('bars')}\n\n"
        f"┃ {E('key')} Premium Game Keys\n"
        f"┃ {E('fire')} Instant Delivery 24/7\n"
        f"┃ {E('shield')} 100% Secure Payments\n"
        f"┃ {E('gift')} VIP Rewards &amp; Discounts\n"
        f"┃ {E('h24')} 24/7 Support &amp; Instant Solution\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E('tap')} <b>Tap Product Store Now to Start!</b>"
    )
    upd = link(db.get("update_url"), "url")
    row_upd = B("All Update File", url=upd, style="success", ek="folder") if upd else \
        B("All Update File", cb="noupd", style="success", ek="folder")
    kb = KB(
        [B("Shop Now", cb="shop", style="primary", ek="sale")],
        [B("Add Balance", cb="addbal", style="success", ek="money"), B("All History", cb="hist", style="success", ek="history")],
        [B("My Profile", cb="profile", style="success", ek="user"), B("Referral", cb="ref", style="success", ek="share")],
        [B("Tutorial", cb="tut", style="success", ek="yt"), row_upd],
        [B("Support", cb="sup", style="success", ek="support")],
    )
    return text, kb


def send_menu(chat, u):
    t, k = menu_screen(u)
    send(chat, t, k)


def addbal_screen(u):
    amt = db.kp_get(u["id"])
    mn, mx = int(db.get("min_dep", "1")), int(db.get("max_dep", "10000"))
    sym, cur = u["symbol"], u["currency"]
    text = (
        f"{E('money')} ━━━ <b>ADD BALANCE TO WALLET</b> ━━━\n\n"
        f"{E('wallet')} Current balance : <b>{fmt(u, u['balance'])}</b>\n\n"
        f"{E('chart')} Minimum Deposit : <b>{sym}{mn:,} {cur}</b>\n\n"
        f"{E('bars')} Maximum Deposit : <b>{sym}{mx:,}</b>\n\n\n"
        f"{E('money')} Amount: <b>{sym}{amt or 0} {cur}</b>\n\n\n"
        f"{E('tap')} <i>Use the keypad below to enter amount</i>"
    )
    d = lambda n: B(str(n), cb=f"kp:{n}", style="primary")
    kb = KB(
        [d(1), d(2), d(3)], [d(4), d(5), d(6)], [d(7), d(8), d(9)],
        [B("Cancel", cb="kp:c", style="danger", ek="cancel"), d(0), B("Confirm", cb="kp:ok", style="success", ek="confirm")],
        [back_btn()],
    )
    return text, kb


def history_screen(u):
    n, spent, dep = db.stats(u["id"])
    since = int(time.time()) - 3 * 86400
    recent = db.orders(u["id"], since)
    text = (
        f"{E('tap')} <b>ALL HISTORY</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"├── {E('diamond')} Total spent: <b>{u['symbol']}{spent:.2f} {u['currency']}</b>\n"
        f"└── {E('shield')} Total deposited: <b>{u['symbol']}{dep:.2f} {u['currency']}</b>\n\n"
        f"{E('cart')} <b>Recent Orders</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    for o in recent[:5]:
        text += (
            f"{E('check')} <code>{o['order_no']}</code>\n"
            f"├── {E('cart')} {esc(o['product'])} · {esc(o['plan'])}\n"
            f"├── {E('money')} {u['symbol']}{o['price']:.2f} {u['currency']}\n"
            f"├── {E('time')} {ist(o['created'])}\n"
            f"└── {E('key')} <code>{esc(o['key'])}</code>\n\n"
        )
    if not recent:
        text += "<i>No orders in the last 3 days.</i>\n\n"
    older = n - len(recent[:5])
    if n:
        text += f"{E('info')} <i>Showing your latest orders from the last 3 days. {max(older,0)} older order(s) are in the full file — tap</i> {E('download')} <b>Download All Keys</b>."
    kb = KB([B("Download All Keys", cb="dl", style="success", ek="download")], [back_btn()])
    return text, kb


def profile_screen(u):
    n, spent, _ = db.stats(u["id"])
    role = "Reseller" if u["role"] == "reseller" else "Standard User"
    text = (
        f"{E('user')} <b>MY PROFILE</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"├── {E('check')} ID: <code>{u['id']}</code>\n\n"
        f"├── {E('fire2')} Name: <b><i>{esc(u['name'])}</i></b>\n\n"
        f"├── {E('phone')} Phone: {u['phone'] or '-'}\n\n"
        f"├── {E('globe')} Country: {u['country']}\n\n"
        f"├── {E('wallet')} Balance: {fmt(u, u['balance'])}\n\n"
        f"├── {E('gift2')} Ref Balance: {fmt(u, u['ref_balance'])}\n\n"
        f"├── {E('cart')} Orders: {n}\n\n"
        f"├── {E('diamond')} Lifetime spent: {fmt(u, spent)}\n\n"
        f"└── {E('calendar')} Joined: {ist(u['joined'], '%Y-%m-%d')} IST\n\n"
        f"{E('user')} {role}"
    )
    return text, KB([back_btn()])


def ref_screen(u):
    lk = f"https://t.me/{BOT_USERNAME['v']}?start=ref_{u['id']}"
    text = (
        f"{E('share')} <b>Referral Program</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"Status: Active 🟢\n\n"
        f"{E('money')} Earn exclusive commissions on referred purchases! ⭐\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{E('megaphone')} <b>Your Invite Link:</b>\n<code>{lk}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E('share')} <b>Share your link to grow your earnings!</b>"
    )
    share = f"https://t.me/share/url?url={quote(lk)}&text={quote('Best game keys store! Join here:')}"
    rows = [[B("Send Link", url=share, style="success", ek="share")]]
    if u["ref_balance"] > 0:
        rows.append([B(f"Claim {fmt(u, u['ref_balance'])} to wallet", cb="claim", style="primary", ek="gift2")])
    rows.append([back_btn()])
    return text, KB(*rows)


def tut_screen(u):
    text = (
        f"{E('yt')} ━ <b>VIDEO TUTORIALS</b> ━ {E('yt')}\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E('yt')} <b>Learn How To Use Our Products</b>\n\n"
        f"├ {E('fire')} Step-By-Step Guides\n├ {E('key')} Game Setup Tutorials\n"
        f"├ {E('support')} Installation Help\n└ ⭐ Tips &amp; Tricks\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n{E('tap')} <b>Click Any Tutorial Below:</b>"
    )
    rows = []
    v = link(db.get("tutorial_url"), "url")
    if v:
        rows.append([B("Watch Guide Video", url=v, style="primary", ek="yt")])
    rows.append([back_btn()])
    return text, KB(*rows)


def sup_screen(u):
    text = (
        f"{E('h24')} <b>Support Team</b>\n{E('tap')} Our team is here to help you.\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E('user')} <b>We can assist with:</b>\n\n"
        f"— {E('fire')} Orders &amp; key delivery\n— {E('money')} Payments &amp; balance\n"
        f"— {E('info')} Product questions\n— {E('fire')} Any other issue\n\n"
        f"If you face any issues or have questions regarding our services, feel free to contact our expert team.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n<b>Click the button below to start a chat</b> {E('tap')}"
    )
    rows = []
    if db.get("support_tg_on") == "1" and link(db.get("support_tg"), "tg"):
        rows.append([B("Chat on Telegram", url=link(db.get("support_tg"), "tg"), style="success", ek="telegram")])
    if db.get("support_wa_on") == "1" and link(db.get("support_wa"), "wa"):
        rows.append([B("Chat on WhatsApp", url=link(db.get("support_wa"), "wa"), style="success", ek="whatsapp")])
    if not rows:
        text += "\n\n<i>Support is currently unavailable.</i>"
    rows.append([back_btn()])
    return text, KB(*rows)



def shop_screen(u):
    text = (f"{E('sale')} ━━ <b>PRODUCT STORE</b> ━━\n\n"
            f"{E('wallet')} Balance: <b>{fmt(u, u['balance'])}</b>\n\n")
    rows = []
    prods = db.products()
    for p in prods:
        tag = "" if p["stock"] else " · Sold out"
        rows.append([B(p["name"] + tag, cb=f"p:{p['id']}", style="primary", ek="key")])
    text += (f"{E('tap')} <i>Select a product:</i>" if prods else "<i>No products available yet.</i>")
    rows.append([back_btn()])
    return text, KB(*rows)


def prod_screen(u, pid):
    p = db.product(pid)
    if not p or not p["active"]:
        return shop_screen(u)
    text = f"{E('key')} <b>{esc(p['name'])}</b>\n━━━━━━━━━━━━━━━━━━━━\n"
    if p["descr"]:
        text += f"{esc(p['descr'])}\n\n"
    text += f"{E('tap')} <i>Choose a plan:</i>"
    rows = []
    for pl in db.plans_of(pid):
        price = db.price_for(u, pl)
        if pl["stock"] > 0:
            label, cb = f"{pl['name']} · {u['symbol']}{price:g}", f"pl:{pl['id']}"
        else:
            label, cb = f"{pl['name']} · Sold out", "oos"
        rows.append([B(label, cb=cb, style="primary" if pl["stock"] else None)])
    rows.append([B("Back", cb="shop", style="danger", ek="back")])
    return text, KB(*rows)


def method_err(u, m):
    """None if the payment method can be used by this user, else a message"""
    if m == "upi":
        if u["currency"] != "INR" or db.get("pay_upi_on") != "1" or not db.get("upi_id").strip():
            return "UPI payment is not available right now."
    elif m == "binance":
        if db.get("pay_binance_on") != "1" or not db.get("binance_text").strip():
            return "Binance payment is not available right now."
    elif m == "other":
        if u["currency"] == "INR" or not db.get("pay_other_text").strip():
            return "This payment method is not available right now."
    return None


def methods_for(u):
    """[(label, key, emoji_key)] key: q=gateway QR, u=UPI/local manual, b=Binance manual"""
    out = []
    if u["currency"] == "INR" and gateway.configured():
        out.append(("Pay QR", "q", "qr"))
    if not method_err(u, "upi"):
        out.append(("Pay UPI", "u", "upi"))
    elif not method_err(u, "other"):
        out.append(("Pay Local", "u", "local"))
    if not method_err(u, "binance"):
        out.append(("Pay Binance", "b", "binance"))
    return out


def topup_methods_screen(u, amt):
    ms = methods_for(u)
    text = (f"{E('money')} <b>SELECT PAYMENT METHOD</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"{E('wallet')} Add to wallet: <b>{u['symbol']}{amt} {u['currency']}</b>\n\n")
    text += f"{E('tap')} <i>Choose how you want to pay:</i>" if ms else "<i>No payment method is set up yet. Please contact support.</i>"
    btns = [B(lb, cb=f"t{k}:{amt}", style="primary", ek=ek) for lb, k, ek in ms]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([B("Back", cb="addbal", style="danger", ek="back")])
    return text, KB(*rows)


def phone_txt(u):
    return ("+" + u["phone"]) if u["phone"] else "-"


def plan_screen(u, plid):
    pl = db.plan(plid)
    if not pl or not pl["pactive"] or not pl["active"]:
        return shop_screen(u)
    code = db.cp_get(u["id"], plid)
    final, disc, err = db.coupon_calc(u, pl, code)
    if err:
        db.cp_set(u["id"], 0, "")
        code = ""
    base = db.price_for(u, pl)
    price_line = f"<s>{fmt(u, base)}</s> ➜ <b>{fmt(u, final)}</b>" if disc else f"<b>{fmt(u, final)}</b>"
    text = (
        f"{E('receipt')} <b>ORDER SUMMARY</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"├── {E('user')} Name: <b><i>{esc(u['name'])}</i></b>\n"
        f"├── {E('idcard')} User ID: <code>{u['id']}</code>\n"
        f"├── {E('phone')} Phone: <code>{esc(phone_txt(u))}</code>\n"
        f"├── {E('key')} Product: <b>{esc(pl['pname'])}</b>\n"
        f"├── {E('cart')} Plan: <b>{esc(pl['name'])}</b>\n"
        f"├── {E('money')} Price: {price_line}\n"
    )
    if code:
        text += f"├── {E('coupon')} Coupon: <code>{esc(code)}</code> (-{fmt(u, disc)})\n"
    text += f"└── {E('wallet')} Wallet Balance: <b>{fmt(u, u['balance'])}</b>\n"
    rows = []
    if pl["stock"] <= 0:
        text += "\n<i>This plan is sold out.</i>"
    else:
        if u["balance"] >= final:
            rows.append([B("Pay Wallet", cb=f"buy:{plid}", style="success", ek="wallet")])
        btns = [B(lb, cb=f"p{k}:{plid}", style="primary", ek=ek) for lb, k, ek in methods_for(u)]
        btns.append(B("Coupon", cb=f"cp:{plid}", style="success", ek="coupon"))
        for i in range(0, len(btns), 2):
            rows.append(btns[i:i + 2])
        if u["balance"] < final:
            text += f"\n{E('info')} <i>Wallet balance is low. Pick a payment method below.</i>"
    rows.append([B("Back", cb=f"p:{pl['product_id']}", style="danger", ek="back")])
    return text, KB(*rows)


def order_screen(u, o):
    text = (
        f"{E('check')} <b>ORDER SUCCESSFUL</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"├── {E('check')} Order: <code>{o['order_no']}</code>\n"
        f"├── {E('cart')} {esc(o['product'])} · {esc(o['plan'])}\n"
        f"├── {E('money')} {fmt(u, o['price'])}\n"
        f"├── {E('time')} {ist(o['created'])}\n"
        f"└── {E('key')} <code>{esc(o['key'])}</code>\n\n"
        f"{E('info')} <i>Tap the key to copy it. It is also saved in All History.</i>"
    )
    return text, KB([B("Shop More", cb="shop", style="primary", ek="sale")], [back_btn()])


def send_payment(chat, mid, u, dep_id, amt):
    api("deleteMessage", chat_id=chat, message_id=mid)
    kb = KB([B("I Have Paid", cb=f"dp:{dep_id}", style="success", ek="paid")],
            [B("Cancel", cb=f"dc:{dep_id}", style="danger", ek="cancel")])
    upi = db.get("upi_id").strip()
    amount_txt = fmt(u, amt)
    if u["currency"] == "INR" and upi:
        uri = (f"upi://pay?pa={quote(upi, safe='@.-_')}&pn={quote(db.get('upi_name') or 'Shop')}"
               f"&am={amt:.2f}&cu=INR&tn={quote('RG' + str(dep_id))}")
        cap = (f"{E('qr')} <b>PAY VIA UPI</b>\n━━━━━━━━━━━━━━━━━━━━\n"
               f"{E('money')} Amount: <b>{amount_txt}</b>\n"
               f"{E('check')} UPI ID: <code>{esc(upi)}</code>\n"
               f"{E('chart')} Deposit ID: <code>#{dep_id}</code>\n\n"
               f"1️⃣ Scan the QR or pay the <b>exact amount</b>.\n"
               f"2️⃣ Tap <b>I Have Paid</b>, then send your UTR / Transaction ID or a screenshot.")
        if segno:
            try:
                buf = io.BytesIO()
                segno.make(uri, error="m").save(buf, kind="png", scale=8, border=3)
                r = api_file("sendPhoto", {"photo": ("qr.png", buf.getvalue())}, chat_id=chat,
                             caption=cap, parse_mode="HTML", reply_markup=kb)
                if r.get("ok"):
                    return
            except Exception:
                traceback.print_exc()
        send(chat, cap, kb)
        return
    other = db.get("pay_other_text").strip()
    if not other:
        send(chat, "⚠️ Payment method is not set for your country yet. Please contact support.", KB([back_btn()]))
        return
    send(chat, f"{E('paid')} <b>PAYMENT DETAILS</b>\n━━━━━━━━━━━━━━━━━━━━\n"
               f"{E('money')} Amount: <b>{amount_txt}</b>\n{E('chart')} Deposit ID: <code>#{dep_id}</code>\n\n"
               f"{esc(other)}\n\nAfter paying tap <b>I Have Paid</b> and send your transaction ID or screenshot.", kb)


def page_url(pay):
    return f"{PUBLIC_URL}/pay/{pay['token']}" if PUBLIC_URL else ""


def own_upi_uri(amt, pay_no):
    upi = db.get("upi_id").strip()
    if not upi:
        return ""
    return (f"upi://pay?pa={quote(upi, safe='@.-_')}&pn={quote(db.get('upi_name') or 'Shop')}"
            f"&am={amt:.2f}&cu=INR&tn={quote(pay_no)}")


def qr_png(data):
    if not segno or not data:
        return None
    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="png", scale=8, border=3)
    return buf.getvalue()


def pay_caption(pay, u):
    exp = int(db.get("pay_expire", "10") or 10)
    return (f"{E('qr')} <b>PAY VIA QR</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"├── {E('receipt')} Order ID: <code>{pay['pay_no']}</code>\n"
            f"├── {E('key')} {esc(pay['title'])}\n"
            f"├── {E('money')} Amount: <b>{fmt(u, pay['amount'])}</b>\n"
            f"└── {E('time')} Valid for: <b>{exp} min</b>\n\n"
            f"1️⃣ Scan this QR with any UPI app (or tap <b>Open Payment Page</b>).\n"
            f"2️⃣ Pay the <b>exact amount</b>. Payment is detected automatically — no screenshot needed.")


def send_pay_msg(chat, mid, u, pay):
    if mid:
        api("deleteMessage", chat_id=chat, message_id=mid)
    rows = []
    pu = page_url(pay)
    if pu:
        rows.append([B("Open Payment Page", url=pu, style="primary", ek="qr")])
    rows.append([B("Cancel", cb=f"pc:{pay['pay_no']}", style="danger", ek="cancel")])
    kb = KB(*rows)
    cap = pay_caption(pay, u)
    png = None
    try:
        png = qr_png(pay["upi_uri"] or pay["pay_url"])
    except Exception:
        traceback.print_exc()
    r = None
    if png:
        r = api_file("sendPhoto", {"photo": ("qr.png", png)}, chat_id=chat, caption=cap, parse_mode="HTML", reply_markup=kb)
    if not r or not r.get("ok"):
        r = send(chat, cap + (f"\n\n{esc(pay['pay_url'])}" if pay["pay_url"] else ""), kb)
    try:
        db.pay_update(pay["pay_no"], chat_id=chat, msg_id=r["result"]["message_id"])
    except Exception:
        pass


def start_qr(chat, mid, u, kind, amount, plid, code, title):
    """create the order on the gateway and show the QR"""
    pay = db.pay_create(u["id"], kind, amount, plid, code, title)
    hook = f"{PUBLIC_URL}/webhook/gateway?s={db.get('gw_secret')}" if PUBLIC_URL else ""
    res = gateway.create(pay["pay_no"], amount, u, page_url(pay), hook)
    if not res["ok"]:
        db.pay_update(pay["pay_no"], status="cancelled")
        send(chat, f"⚠️ <b>Could not start payment.</b>\n<i>{esc(res['err'])}</i>\nPlease try again or contact support.",
             KB([back_btn()]))
        return
    uri = res["upi_uri"] or own_upi_uri(amount, pay["pay_no"])
    db.pay_update(pay["pay_no"], upi_uri=uri, pay_url=res["pay_url"], gw_ref=res["ref"])
    send_pay_msg(chat, mid, u, db.pay_get(pay["pay_no"]))


def usd_of(u, amount):
    return max(round(amount / db.rate(u["currency"]) * db.rate("USD"), 2), 0.01)


def start_manual(chat, mid, u, method, kind, amount, plid, code, title):
    """manual payment (UPI / Binance / local): user pays, then sends the transaction ID to the admin"""
    pay = db.pay_create(u["id"], kind, amount, plid, code, title, method)
    no = pay["pay_no"]
    if mid:
        api("deleteMessage", chat_id=chat, message_id=mid)
    head = {"upi": "PAY VIA UPI", "binance": "PAY VIA BINANCE", "other": "PAYMENT DETAILS"}[method]
    text = (f"{E('qr') if method == 'upi' else E('paid')} <b>{head}</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"├── {E('receipt')} Order ID: <code>{no}</code>\n├── {E('key')} {esc(title)}\n")
    png = None
    if method == "upi":
        uri = own_upi_uri(amount, no)
        db.pay_update(no, upi_uri=uri)
        text += (f"├── {E('money')} Amount: <b>{fmt(u, amount)}</b>\n└── {E('check')} UPI ID: <code>{esc(db.get('upi_id').strip())}</code>\n\n"
                 f"1️⃣ Scan the QR or pay the <b>exact amount</b> to the UPI ID.\n"
                 f"2️⃣ Tap <b>I Have Paid</b>, then send your <b>UTR / Transaction ID</b> (or a screenshot).")
        try:
            png = qr_png(uri)
        except Exception:
            traceback.print_exc()
    elif method == "binance":
        text += (f"└── {E('money')} Amount: <b>{fmt(u, amount)}</b> ≈ <b>${usd_of(u, amount):.2f} USDT</b>\n\n"
                 f"{esc(db.get('binance_text'))}\n\n"
                 f"1️⃣ Pay on Binance.\n2️⃣ Tap <b>I Have Paid</b> and send the Binance <b>Order ID / Transaction ID</b> you get after paying.")
    else:
        text += (f"└── {E('money')} Amount: <b>{fmt(u, amount)}</b>\n\n{esc(db.get('pay_other_text'))}\n\n"
                 f"After paying tap <b>I Have Paid</b> and send your transaction ID or screenshot.")
    kb = KB([B("I Have Paid", cb=f"pm:{no}", style="success", ek="paid")],
            [B("Cancel", cb=f"pc:{no}", style="danger", ek="cancel")])
    r = None
    if png:
        r = api_file("sendPhoto", {"photo": ("qr.png", png)}, chat_id=chat, caption=text, parse_mode="HTML", reply_markup=kb)
    if not r or not r.get("ok"):
        r = send(chat, text, kb)
    try:
        db.pay_update(no, chat_id=chat, msg_id=r["result"]["message_id"])
    except Exception:
        pass


def notify_admin_pay(p, u):
    if not ADMIN_ID:
        return
    what = "Wallet top-up" if p["kind"] == "topup" else p["title"]
    extra = f"\nBinance amount: <b>${usd_of(u, p['amount']):.2f}</b>" if p["method"] == "binance" else ""
    text = (f"{E('wait')} <b>New {esc(p['method'].upper())} payment</b>\n"
            f"Order: <code>{p['pay_no']}</code>\nUser: <code>{u['id']}</code> {esc(u['name'])}\n"
            f"For: <b>{esc(what)}</b>\nAmount: <b>{fmt(u, p['amount'])}</b>{extra}\n"
            f"Transaction ID: <code>{esc(p['txn'] or '-')}</code>")
    kb = KB([B("Approve", cb=f"ma:{p['pay_no']}", style="success", ek="confirm"),
             B("Reject", cb=f"mr:{p['pay_no']}", style="danger", ek="cancel")])
    if p["proof"]:
        r = api("sendPhoto", chat_id=ADMIN_ID, photo=p["proof"], caption=text, parse_mode="HTML", reply_markup=kb)
        if r.get("ok"):
            return
    send(ADMIN_ID, text, kb)


def reject_pay(no):
    p = db.pay_reject(no)
    if not p:
        return None
    u = db.user(p["user_id"])
    if p["chat_id"] and p["msg_id"]:
        api("deleteMessage", chat_id=p["chat_id"], message_id=p["msg_id"])
    if u:
        send(u["id"], f"❌ <b>Payment {p['pay_no']} was rejected.</b>\nIf you really paid, contact support with your payment proof.")
    return p


def success_block(u, pay, txn, extra=""):
    return (f"{E('success')} <b>PAYMENT SUCCESSFUL</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"├── {E('receipt')} Order ID: <code>{pay['pay_no']}</code>\n"
            f"├── {E('txn')} Transaction ID: <code>{esc(txn or '-')}</code>\n"
            f"├── {E('money')} Amount: <b>{fmt(u, pay['amount'])}</b>\n"
            f"├── {E('time')} {ist(int(time.time()))}\n{extra}")


def complete_pay(pay_no, txn=""):
    """Called by the watcher / webhook / admin. Safe to call many times - runs once."""
    pay = db.pay_resolve(pay_no, txn)
    if not pay:
        return None
    uid = pay["user_id"]
    u = db.user(uid)
    if not u:
        return pay
    if pay["chat_id"] and pay["msg_id"]:
        api("deleteMessage", chat_id=pay["chat_id"], message_id=pay["msg_id"])
    chat = pay["chat_id"] or uid
    if pay["kind"] == "topup":
        db.add_balance(uid, pay["amount"])
        db.dep_record_paid(uid, pay["amount"], txn or pay_no)
        u = db.user(uid)
        text = (success_block(u, pay, txn, f"└── {E('wallet')} Wallet balance: <b>{fmt(u, u['balance'])}</b>\n") +
                f"\n{E('check')} <b>Wallet recharged successfully!</b>")
        send(chat, text, KB([B("Shop Now", cb="shop", style="primary", ek="sale")], [back_btn()]))
        what = "Wallet top-up"
    else:
        res = db.buy(uid, pay["plan_id"], ext_price=pay["amount"])
        if res[0] == "ok":
            db.coupon_consume(uid, pay["coupon"])
            o = res[1]
            db.pay_update(pay_no, order_no=o["order_no"])
            u = db.user(uid)
            text = (success_block(u, pay, txn, f"└── {E('cart')} {esc(o['product'])} · {esc(o['plan'])}\n") +
                    f"\n{E('key')} <b>Your key:</b>\n<code>{esc(o['key'])}</code>\n\n"
                    f"{E('info')} <i>Tap the key to copy. Saved in All History too.</i>\n"
                    f"{E('cart')} Order: <code>{o['order_no']}</code>")
            send(chat, text, KB([B("Shop More", cb="shop", style="primary", ek="sale")], [back_btn()]))
            comm = db.pay_commission(uid, o["price"])
            if comm:
                ru = db.user(comm[0])
                if ru:
                    send(ru["id"], f"{E('gift2')} Referral commission: you earned <b>{fmt(ru, comm[1])}</b> from a friend's purchase!")
            if res[2] <= int(db.get("low_stock", "3") or 3) and ADMIN_ID:
                send(ADMIN_ID, f"{E('box')} Low stock: <b>{esc(o['product'])} · {esc(o['plan'])}</b> has {res[2]} key(s) left.")
            what = f"Purchase {o['product']} · {o['plan']}"
        else:
            u = db.user(uid)
            send(chat, success_block(u, pay, txn, f"└── {E('wallet')} Wallet balance: <b>{fmt(u, u['balance'])}</b>\n") +
                 f"\n{E('info')} The item just went out of stock, so <b>{fmt(u, pay['amount'])}</b> was added to your wallet instead. "
                 f"You can buy another plan with it.", KB([B("Shop Now", cb="shop", style="primary", ek="sale")], [back_btn()]))
            what = "Purchase (out of stock -> refunded to wallet)"
    if ADMIN_ID:
        send(ADMIN_ID, f"{E('paid')} <b>Payment received</b>\n{what}\nUser: <code>{uid}</code> {esc(u['name'])}\n"
                       f"Amount: <b>{fmt(u, pay['amount'])}</b>\nOrder: <code>{pay_no}</code> · Txn: <code>{esc(txn or '-')}</code>")
    return pay


def pay_watch():
    """background: check pending QR payments every few seconds, expire old ones"""
    while True:
        time.sleep(4)
        try:
            exp = int(db.get("pay_expire", "10") or 10) * 60
            for p in db.pay_pending():
                if time.time() - p["created"] > exp:
                    # one last check, then expire (a late payment can still be honoured by the webhook)
                    if gateway.configured() and gateway.check(p["pay_no"])[0] == "paid":
                        complete_pay(p["pay_no"], gateway.check(p["pay_no"])[1])
                        continue
                    db.pay_update(p["pay_no"], status="expired")
                    if p["chat_id"] and p["msg_id"]:
                        api("deleteMessage", chat_id=p["chat_id"], message_id=p["msg_id"])
                        send(p["chat_id"], f"{E('wait')} <b>Payment expired</b>\nOrder <code>{p['pay_no']}</code> was not paid in time. "
                                           f"If you already paid, it will still be added automatically.", KB([back_btn()]))
                    continue
                if gateway.configured():
                    st, txn = gateway.check(p["pay_no"])
                    if st == "paid":
                        complete_pay(p["pay_no"], txn)
                    elif st == "failed":
                        db.pay_update(p["pay_no"], status="cancelled")
        except Exception:
            traceback.print_exc()


def approve_deposit(did, ok=True):
    """Used by Telegram buttons and the website. Returns deposit row or None if already handled."""
    d = db.dep_resolve(did, ok)
    if not d:
        return None
    u = db.user(d["user_id"])
    if u:
        if ok:
            send(u["id"], f"{E('check')} <b>Deposit approved!</b>\n{fmt(u, d['amount'])} added to your wallet.\n"
                          f"{E('wallet')} New balance: <b>{fmt(u, u['balance'])}</b>")
        else:
            send(u["id"], f"❌ <b>Deposit #{did} was rejected.</b>\nIf you really paid, contact support with your payment proof.")
    return d


def notify_admin_deposit(d, u, utr, proof):
    if not ADMIN_ID:
        return
    text = (f"{E('wait')} <b>New deposit request</b>\n"
            f"Deposit: <code>#{d['id']}</code>\nUser: <code>{u['id']}</code> {esc(u['name'])}\n"
            f"Amount: <b>{fmt(u, d['amount'])}</b>\nUTR: <code>{esc(utr or '-')}</code>")
    kb = KB([B("Approve", cb=f"da:{d['id']}", style="success", ek="confirm"),
             B("Reject", cb=f"dr:{d['id']}", style="danger", ek="cancel")])
    if proof:
        r = api("sendPhoto", chat_id=ADMIN_ID, photo=proof, caption=text, parse_mode="HTML", reply_markup=kb)
        if r.get("ok"):
            return
    send(ADMIN_ID, text, kb)


_last = {}


def rate_ok(uid, gap=0.35):
    """ignore button taps faster than ~3 per second per user"""
    now = time.time()
    if now - _last.get(uid, 0) < gap:
        return False
    _last[uid] = now
    if len(_last) > 5000:
        _last.clear()
    return True


def send_doc_admin(name, blob, caption="Database backup"):
    if ADMIN_ID:
        api_file("sendDocument", {"document": (name, blob)}, chat_id=ADMIN_ID, caption=caption)


def broadcast(text, only_ids=None, done=None):
    """background broadcast, ~20 msgs/sec"""
    def job():
        ok = fail = 0
        for uid in (only_ids or db.broadcast_targets()):
            r = send(uid, text)
            if r.get("ok"):
                ok += 1
            else:
                fail += 1
            time.sleep(0.05)
        if done:
            done(ok, fail)
    threading.Thread(target=job, daemon=True).start()


# ------------------------------------------------------------------ handlers
def ask_phone(chat):
    kb = {"keyboard": [[{"text": "📱 Share Phone Number", "request_contact": True}]],
          "resize_keyboard": True, "one_time_keyboard": True}
    send(chat, "👋 <b>Welcome!</b>\n\nTo continue, please verify your phone number using the button below.", kb)


def on_message(m):
    if m["chat"]["type"] != "private":
        return
    chat, fr = m["chat"]["id"], m["from"]
    uid = fr["id"]
    text = m.get("text", "") or ""

    # admin helper: send a premium emoji -> get its ID
    ents = [e for e in (m.get("entities") or []) if e["type"] == "custom_emoji"]
    if uid == ADMIN_ID and ents:
        t16 = text.encode("utf-16-le")
        lines = []
        for e in ents:
            ch = t16[e["offset"] * 2:(e["offset"] + e["length"]) * 2].decode("utf-16-le")
            lines.append(f"{ch}  <code>{e['custom_emoji_id']}</code>")
        send(chat, "<b>Premium emoji IDs:</b>\n" + "\n".join(lines) +
             "\n\nPaste the ID in the website admin panel → Premium Emoji.")
        return

    if uid == ADMIN_ID and text.startswith("/emojitest"):
        ok, rep = emoji_test()
        send(chat, ("✅ " if ok else "⚠️ ") + esc(rep))
        return

    if db.get("maint") == "1" and uid != ADMIN_ID:
        send(chat, "🛠 " + esc(db.get("maint_text")))
        return

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        ref = None
        if len(parts) > 1 and parts[1].startswith("ref_"):
            try:
                ref = int(parts[1][4:])
            except ValueError:
                pass
        u = db.ensure_user(fr, ref)
        if u["banned"]:
            return
        send_menu(chat, u) if u["verified"] else ask_phone(chat)
        return

    c = m.get("contact")
    if c:
        if c.get("user_id") != uid:
            send(chat, "❌ Please share <b>your own</b> number using the button.")
            return
        u = db.ensure_user(fr)
        phone = "".join(ch for ch in c["phone_number"] if ch.isdigit())
        refby = db.verify(uid, phone)
        if refby:
            reward = float(db.get("ref_reward", "2"))
            db.add_ref_balance(refby, reward)
            ru = db.user(refby)
            if ru:
                send(refby, f"🎁 Your friend joined and verified! You earned <b>{ru['symbol']}{reward:g}</b> referral balance.")
        api("sendMessage", chat_id=chat, text="✅ <b>Phone verified!</b>", parse_mode="HTML",
            reply_markup=json.dumps({"remove_keyboard": True}))
        send_menu(chat, db.user(uid))
        return

    u = db.user(uid)
    if not u or not u["verified"]:
        ask_phone(chat)
        return
    if u["banned"]:
        return
    st = db.st_get(uid)
    if st.startswith("coupon:"):
        plid = int(st[7:])
        pl = db.plan(plid)
        code = text.strip().upper()[:32] if text and not text.startswith("/") else ""
        if not pl or not code:
            send(chat, "Please send the <b>coupon code</b> as text.")
            return
        final, disc, err = db.coupon_calc(u, pl, code)
        if err:
            send(chat, f"❌ {esc(err)}\nSend another code or tap Cancel.",
                 KB([B("Cancel", cb=f"pl:{plid}", style="danger", ek="cancel")]))
            return
        db.cp_set(uid, plid, code)
        db.st_set(uid, "")
        send(chat, f"{E('success')} <b>Coupon applied!</b> You save <b>{fmt(u, disc)}</b>.")
        t, k = plan_screen(u, plid)
        send(chat, t, k)
        return
    if st.startswith("mp:"):
        no = st[3:]
        p = db.pay_get(no)
        photo = (m.get("photo") or [{}])[-1].get("file_id", "")
        txn = text.strip()[:80] if text and not text.startswith("/") else ""
        if not p or p["user_id"] != uid or p["status"] != "pending":
            db.st_set(uid, "")
        elif not txn and not photo:
            send(chat, "Please send your <b>Transaction ID</b> as text, or a payment screenshot.")
            return
        elif txn and len(txn) < 6:
            send(chat, "❌ That ID looks too short. Send the full Transaction ID / Order ID or a screenshot.")
            return
        elif txn and db.pay_txn_used(txn):
            send(chat, "❌ This transaction ID was already used. Contact support if this is a mistake.")
            return
        else:
            db.pay_submit(no, txn, photo)
            db.st_set(uid, "")
            if p["chat_id"] and p["msg_id"]:
                api("deleteMessage", chat_id=p["chat_id"], message_id=p["msg_id"])
            send(chat, f"{E('wait')} <b>Request sent to admin!</b>\nOrder <code>{no}</code> is being checked. "
                       f"You will get your {'balance' if p['kind'] == 'topup' else 'key'} as soon as it is approved.", KB([back_btn()]))
            notify_admin_pay(db.pay_get(no), u)
            return
    if st.startswith("utr:"):
        did = int(st[4:])
        d = db.dep_get(did)
        photo = (m.get("photo") or [{}])[-1].get("file_id", "")
        utr = text.strip()[:64] if text and not text.startswith("/") else ""
        if not d or d["user_id"] != uid or d["status"] != "pending":
            db.st_set(uid, "")
        elif not utr and not photo:
            send(chat, "Please send your <b>UTR / Transaction ID</b> as text, or a payment screenshot.")
            return
        elif utr and len(utr) < 6:
            send(chat, "❌ That ID looks too short. Send the full UTR / Transaction ID or a screenshot.")
            return
        elif utr and db.dep_utr_used(utr):
            send(chat, "❌ This transaction ID was already used. Contact support if this is a mistake.")
            return
        else:
            db.dep_submit(did, utr, photo)
            db.st_set(uid, "")
            send(chat, f"{E('wait')} <b>Request submitted!</b>\nDeposit <code>#{did}</code> is under review. "
                       f"Your balance will be updated as soon as it is approved.", KB([back_btn()]))
            notify_admin_deposit(db.dep_get(did), u, utr, photo)
            return
    send_menu(chat, u)


def on_cb(cq):
    uid = cq["from"]["id"]
    chat, mid = cq["message"]["chat"]["id"], cq["message"]["message_id"]
    data = cq["data"]
    photo = "photo" in cq["message"]

    # admin deposit buttons (work even if admin has not verified a phone)
    if data[:3] in ("ma:", "mr:"):
        if uid != ADMIN_ID:
            ans(cq, "Not allowed.", True)
            return
        no, ok = data[3:], data.startswith("ma:")
        if ok:
            pp = db.pay_get(no)
            res = complete_pay(no, (pp["txn"] if pp else "") or "ADMIN")
        else:
            res = reject_pay(no)
        api("editMessageReplyMarkup", chat_id=chat, message_id=mid, reply_markup=json.dumps({"inline_keyboard": []}))
        ans(cq, (("Approved" if ok else "Rejected") if res else "Already handled"), True)
        if res:
            send(chat, f"{'✅ Approved' if ok else '❌ Rejected'} payment <code>{no}</code>.")
        return
    if data[:3] in ("da:", "dr:"):
        if uid != ADMIN_ID:
            ans(cq, "Not allowed.", True)
            return
        did = int(data[3:])
        ok = data.startswith("da:")
        d = approve_deposit(did, ok)
        api("editMessageReplyMarkup", chat_id=chat, message_id=mid, reply_markup=json.dumps({"inline_keyboard": []}))
        ans(cq, ("Approved" if ok else "Rejected") if d else "Already handled", True)
        if d:
            send(chat, f"{'✅ Approved' if ok else '❌ Rejected'} deposit <code>#{did}</code>.")
        return

    u = db.user(uid)
    if not u or not u["verified"] or u["banned"]:
        ans(cq, "Please /start the bot first.", True)
        return
    if db.get("maint") == "1" and uid != ADMIN_ID:
        ans(cq, db.get("maint_text"), True)
        return
    if not rate_ok(uid):
        ans(cq)
        return

    def sh(t, k):
        show(chat, mid, t, k, photo)

    if data == "menu":
        db.kp_set(uid, "")
        db.st_set(uid, "")
        sh(*menu_screen(u))
    elif data == "shop":
        sh(*shop_screen(u))
    elif data.startswith("p:"):
        sh(*prod_screen(u, int(data[2:])))
    elif data.startswith("pl:"):
        db.st_set(uid, "")
        sh(*plan_screen(u, int(data[3:])))
    elif data.startswith("cp:"):
        plid = int(data[3:])
        db.st_set(uid, f"coupon:{plid}")
        ans(cq)
        sh(f"{E('coupon')} <b>COUPON</b>\n━━━━━━━━━━━━━━━━━━━━\nSend your <b>coupon code</b> now.",
           KB([B("Cancel", cb=f"pl:{plid}", style="danger", ek="cancel")]))
        return
    elif data.startswith("pq:"):
        plid = int(data[3:])
        pl = db.plan(plid)
        if not pl or not pl["pactive"] or not pl["active"]:
            ans(cq, "This item is no longer available.", True)
            return
        if pl["stock"] <= 0:
            ans(cq, "This plan is sold out.", True)
            return
        if u["currency"] != "INR":
            ans(cq, "UPI QR is for India (INR) users. Please pay from your wallet.", True)
            return
        if not gateway.configured():
            ans(cq, "QR payment is not active yet. Please use wallet or contact support.", True)
            return
        final, disc, err = db.coupon_calc(u, pl, db.cp_get(uid, plid))
        if err:
            ans(cq, err, True)
            return
        if final <= 0:
            ans(cq, "Price is 0 after coupon - use Pay Wallet.", True)
            return
        ans(cq, "Creating payment...")
        start_qr(chat, mid, u, "buy", final, plid, db.cp_get(uid, plid), f"{pl['pname']} · {pl['name']}")
        return
    elif data[:3] in ("pu:", "pb:"):
        plid = int(data[3:])
        pl = db.plan(plid)
        if not pl or not pl["pactive"] or not pl["active"]:
            ans(cq, "This item is no longer available.", True)
            return
        if pl["stock"] <= 0:
            ans(cq, "This plan is sold out.", True)
            return
        method = "binance" if data[:3] == "pb:" else ("upi" if u["currency"] == "INR" else "other")
        e = method_err(u, method)
        if e:
            ans(cq, e, True)
            return
        final, disc, err = db.coupon_calc(u, pl, db.cp_get(uid, plid))
        if err:
            ans(cq, err, True)
            return
        if final <= 0:
            ans(cq, "Price is 0 after coupon - use Pay Wallet.", True)
            return
        ans(cq)
        start_manual(chat, mid, u, method, "buy", final, plid, db.cp_get(uid, plid), f"{pl['pname']} · {pl['name']}")
        return
    elif data[:3] in ("tq:", "tu:", "tb:"):
        amt = int(data[3:])
        mn, mx = int(db.get("min_dep", "1")), int(db.get("max_dep", "10000"))
        if amt < mn or amt > mx:
            ans(cq, f"Amount must be between {u['symbol']}{mn} and {u['symbol']}{mx:,}", True)
            return
        k = data[1]
        if k == "q":
            if u["currency"] != "INR" or not gateway.configured():
                ans(cq, "QR payment is not available right now.", True)
                return
            ans(cq, "Creating payment...")
            start_qr(chat, mid, u, "topup", float(amt), 0, "", "Wallet Recharge")
            return
        method = "binance" if k == "b" else ("upi" if u["currency"] == "INR" else "other")
        e = method_err(u, method)
        if e:
            ans(cq, e, True)
            return
        ans(cq)
        start_manual(chat, mid, u, method, "topup", float(amt), 0, "", "Wallet Recharge")
        return
    elif data.startswith("pm:"):
        p = db.pay_get(data[3:])
        if not p or p["user_id"] != uid or p["status"] != "pending":
            ans(cq, "This payment request is no longer active.", True)
            return
        db.st_set(uid, f"mp:{p['pay_no']}")
        ans(cq)
        send(chat, f"{E('paid')} Send your <b>Transaction ID</b> (UTR / Binance Order ID) as text, or a <b>payment screenshot</b> now.",
             KB([B("Cancel", cb=f"pc:{p['pay_no']}", style="danger", ek="cancel")]))
        return
    elif data == "noop":
        ans(cq)
        return
    elif data.startswith("pc:"):
        p = db.pay_get(data[3:])
        if p and p["user_id"] == uid and p["status"] == "pending":
            db.pay_update(p["pay_no"], status="cancelled")
        ans(cq, "Payment cancelled.")
        sh(*menu_screen(u))
        return
    elif data == "oos":
        ans(cq, "This plan is sold out.", True)
        return
    elif data.startswith("buy:"):
        plid_b = int(data[4:])
        res = db.buy(uid, plid_b, db.cp_get(uid, plid_b))
        if res[0] == "coupon":
            ans(cq, res[1], True)
            return
        if res[0] == "ok":
            db.cp_set(uid, 0, "")
            u2 = db.user(uid)
            sh(*order_screen(u2, res[1]))
            comm = db.pay_commission(uid, res[1]["price"])
            if comm:
                ru = db.user(comm[0])
                if ru:
                    send(ru["id"], f"{E('gift2')} Referral commission: you earned <b>{fmt(ru, comm[1])}</b> from a friend's purchase!")
            if res[2] <= int(db.get("low_stock", "3") or 3) and ADMIN_ID:
                send(ADMIN_ID, f"{E('box')} Low stock: <b>{esc(res[1]['product'])} · {esc(res[1]['plan'])}</b> has {res[2]} key(s) left.")
        elif res[0] == "bal":
            ans(cq, "Not enough balance. Please add balance first.", True)
            return
        elif res[0] == "stock":
            ans(cq, "Sorry, this plan just sold out.", True)
            return
        else:
            ans(cq, "This item is no longer available.", True)
            return
    elif data == "noupd":
        ans(cq, "Update file link is not added yet.", True)
        return
    elif data == "addbal":
        db.kp_set(uid, "")
        sh(*addbal_screen(u))
    elif data.startswith("kp:"):
        k = data[3:]
        cur = db.kp_get(uid)
        mn, mx = int(db.get("min_dep", "1")), int(db.get("max_dep", "10000"))
        if k == "c":
            if not cur:
                ans(cq)
                return
            db.kp_set(uid, cur[:-1])
        elif k == "ok":
            amt = int(cur or 0)
            if amt < mn:
                ans(cq, f"Minimum deposit is {u['symbol']}{mn}", True)
                return
            db.kp_set(uid, "")
            ans(cq)
            sh(*topup_methods_screen(u, amt))
            return
        else:
            new = (cur + k).lstrip("0")
            if not new:
                ans(cq)
                return
            if int(new) > mx:
                ans(cq, f"Maximum deposit is {u['symbol']}{mx:,}", True)
                return
            db.kp_set(uid, new)
        sh(*addbal_screen(u))
    elif data.startswith("dp:"):
        d = db.dep_get(int(data[3:]))
        if not d or d["user_id"] != uid or d["status"] != "pending":
            ans(cq, "This deposit request is no longer active.", True)
            return
        db.st_set(uid, f"utr:{d['id']}")
        send(chat, f"{E('paid')} Send your <b>UTR / Transaction ID</b> (text) or a <b>payment screenshot</b> now.",
             KB([B("Cancel", cb=f"dc:{d['id']}", style="danger", ek="cancel")]))
    elif data.startswith("dc:"):
        db.dep_cancel(int(data[3:]), uid)
        db.st_set(uid, "")
        sh(*menu_screen(u))
    elif data == "hist":
        sh(*history_screen(u))
    elif data == "dl":
        rows = db.orders(uid)
        if not rows:
            ans(cq, "You have no keys yet.", True)
            return
        body = "\n".join(f"{o['order_no']} | {o['product']} | {o['plan']} | {o['price']} | {ist(o['created'])} | {o['key']}" for o in rows)
        S.post(API + "sendDocument", data={"chat_id": chat},
               files={"document": (f"keys_{uid}.txt", body.encode())}, timeout=60)
    elif data == "profile":
        sh(*profile_screen(u))
    elif data == "ref":
        sh(*ref_screen(u))
    elif data == "claim":
        amt = db.claim_ref(uid)
        if not amt:
            ans(cq, "No referral balance to claim.", True)
            return
        ans(cq, f"{u['symbol']}{amt:g} added to your wallet!", True)
        sh(*ref_screen(db.user(uid)))
        return
    elif data == "tut":
        sh(*tut_screen(u))
    elif data == "sup":
        sh(*sup_screen(u))
    ans(cq)


# ------------------------------------------------------------------ polling
_locks = {}


def process(u):
    try:
        src = u.get("message") or u.get("callback_query") or {}
        uid = (src.get("from") or {}).get("id", 0)
        lock = _locks.setdefault(uid, threading.Lock())
        with lock:
            _dispatch(u)
    except Exception:
        traceback.print_exc()


def _dispatch(u):
    try:
        if "message" in u:
            on_message(u["message"])
        elif "callback_query" in u:
            on_cb(u["callback_query"])
    except Exception:
        traceback.print_exc()


def run():
    me = api("getMe")
    BOT_USERNAME["v"] = me.get("result", {}).get("username", "")
    print("Bot started:", BOT_USERNAME["v"])
    api("deleteWebhook")
    pool = ThreadPoolExecutor(max_workers=16)
    offset = 0
    while True:
        try:
            r = S.post(API + "getUpdates", data={"offset": offset, "timeout": 50,
                       "allowed_updates": json.dumps(["message", "callback_query"])}, timeout=70).json()
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                pool.submit(process, u)
        except Exception as e:
            print("poll error:", e)
            time.sleep(3)
