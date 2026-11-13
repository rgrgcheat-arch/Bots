RG Shop Bot - PART 3 (FINAL, includes Part 1 + 2)
==================================================
Replace ALL files in your GitHub repo with these (main.py, bot.py, web.py, db.py, backup.py, requirements.txt) and redeploy.

NEW Render environment variables (for automatic backup - IMPORTANT on free hosting):
  GH_TOKEN = GitHub fine-grained token (only your backup repo, permission: Contents = Read and write)
  GH_REPO  = yourname/rg-backup      (create a PRIVATE repo; it will hold the database backup)
  (optional) GH_BRANCH = main
Also set ADMIN_PASS and SECRET_KEY (if ADMIN_PASS is missing a random password is printed in the Render logs).

NEW in Part 3
- Auto backup: every change is saved to your private GitHub repo (max once per 3 min). On restart the bot restores it automatically.
  Extra copy: database file is sent to your Telegram every 6h if changed.
- Website -> Backup: backup now, download, upload-restore.
- Website -> Broadcast: send a message to all users (or test only to yourself).
- Referral commission % on friend's purchases + "Claim to wallet" button in Referral screen.
- Maintenance mode, low-stock alert level, orders CSV export, dashboard stats (orders/users today).
- Security: admin login lock (5 wrong tries = 15 min), secure cookies, security headers, bot tap rate-limit.
