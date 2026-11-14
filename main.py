import os, threading, time
import requests
import db, bot, web, backup


def keepalive():
    url = os.getenv("RENDER_EXTERNAL_URL")
    if not url:
        return
    while True:
        time.sleep(240)
        try:
            requests.get(url + "/health", timeout=20)
        except Exception:
            pass


if __name__ == "__main__":
    if not bot.TOKEN:
        raise SystemExit("BOT_TOKEN env var missing")
    backup.restore_if_missing()      # fresh Render disk -> pull last backup from GitHub
    db.init()
    db.migrate_inr()
    threading.Thread(target=keepalive, daemon=True).start()
    threading.Thread(target=bot.pay_watch, daemon=True).start()
    threading.Thread(target=backup.loop, args=(bot.send_doc_admin,), daemon=True).start()
    from waitress import serve
    threading.Thread(target=lambda: serve(web.app, host="0.0.0.0", port=int(os.getenv("PORT", "10000")), threads=8), daemon=True).start()
    bot.run()
