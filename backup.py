"""Automatic backup / restore so data survives Render free-tier restarts.

Primary store : a PRIVATE GitHub repo (env GH_TOKEN, GH_REPO="user/repo", optional GH_BRANCH, GH_PATH)
Secondary     : the database file is also sent to the admin on Telegram (every 6h if changed).
Also          : download / upload-restore from the website Backup page.
"""
import os, io, gzip, time, base64, sqlite3, hashlib, threading, traceback
import requests
import db

GH_TOKEN = os.getenv("GH_TOKEN", "")
GH_REPO = os.getenv("GH_REPO", "")
GH_BRANCH = os.getenv("GH_BRANCH", "main")
GH_PATH = os.getenv("GH_PATH", "backup/data.db.gz")
STATUS = {"last_ok": 0, "last_err": "", "last_tg": 0, "size": 0}
_lock = threading.Lock()


def enabled():
    return bool(GH_TOKEN and GH_REPO)


def _h(raw=False):
    h = {"Authorization": f"Bearer {GH_TOKEN}", "X-GitHub-Api-Version": "2022-11-28"}
    h["Accept"] = "application/vnd.github.raw+json" if raw else "application/vnd.github+json"
    return h


def _url():
    return f"https://api.github.com/repos/{GH_REPO}/contents/{GH_PATH}"


def snapshot():
    """Consistent copy of the live DB -> gzip bytes."""
    tmp = db.DB_PATH + ".snap"
    src = sqlite3.connect(db.DB_PATH, timeout=30)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    with open(tmp, "rb") as f:
        raw = f.read()
    os.remove(tmp)
    return gzip.compress(raw, 6)


def push_github(blob):
    meta = requests.get(_url(), headers=_h(), params={"ref": GH_BRANCH}, timeout=30)
    body = {"message": "backup " + time.strftime("%Y-%m-%d %H:%M:%S"),
            "content": base64.b64encode(blob).decode(), "branch": GH_BRANCH}
    if meta.status_code == 200:
        body["sha"] = meta.json()["sha"]
    elif meta.status_code != 404:
        raise RuntimeError(f"GitHub {meta.status_code}: {meta.text[:150]}")
    r = requests.put(_url(), headers=_h(), json=body, timeout=60)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"GitHub {r.status_code}: {r.text[:150]}")


def restore_github():
    r = requests.get(_url(), headers=_h(raw=True), params={"ref": GH_BRANCH}, timeout=60)
    if r.status_code != 200:
        return False
    return restore_bytes(r.content, gz=True)


def restore_bytes(data, gz=False):
    """Validate then replace the DB file. Used at boot and by the website upload."""
    try:
        raw = gzip.decompress(data) if (gz or data[:2] == b"\x1f\x8b") else data
        if raw[:15] != b"SQLite format 3":
            return False
        tmp = db.DB_PATH + ".restore"
        with open(tmp, "wb") as f:
            f.write(raw)
        t = sqlite3.connect(tmp)
        ok = t.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        t.execute("SELECT COUNT(*) FROM users")
        t.close()
        if not ok:
            os.remove(tmp)
            return False
        for ext in ("-wal", "-shm"):
            if os.path.exists(db.DB_PATH + ext):
                os.remove(db.DB_PATH + ext)
        os.replace(tmp, db.DB_PATH)
        return True
    except Exception:
        traceback.print_exc()
        return False


def restore_if_missing():
    """Call BEFORE db.init(). On a fresh Render disk, pull the last backup."""
    if os.path.exists(db.DB_PATH) and os.path.getsize(db.DB_PATH) > 0:
        return
    if enabled():
        try:
            print("Restore from GitHub:", "OK" if restore_github() else "no backup found")
        except Exception as e:
            print("Restore failed:", e)


def run_now(send_tg=None):
    """Make a backup right now. Returns (ok, message)."""
    with _lock:
        try:
            blob = snapshot()
            STATUS["size"] = len(blob)
            if enabled():
                push_github(blob)
            STATUS["last_ok"], STATUS["last_err"] = int(time.time()), ""
            db.DIRTY["v"] = False
            if send_tg:
                send_tg(blob)
            return True, "Backup done" + ("" if enabled() else " (GitHub not configured - only local copy)")
        except Exception as e:
            STATUS["last_err"] = str(e)[:200]
            traceback.print_exc()
            return False, STATUS["last_err"]


def loop(send_doc):
    """send_doc(filename, bytes) sends a file to the admin on Telegram."""
    time.sleep(60)
    while True:
        try:
            if db.DIRTY["v"] and enabled() and time.time() - STATUS["last_ok"] >= 180:
                run_now()
            if db.DIRTY["v"] or STATUS["last_tg"] == 0:
                if time.time() - STATUS["last_tg"] >= 6 * 3600:
                    blob = snapshot()
                    send_doc("backup_" + time.strftime("%Y%m%d_%H%M") + ".db.gz", blob)
                    STATUS["last_tg"] = int(time.time())
        except Exception:
            traceback.print_exc()
        time.sleep(60)
