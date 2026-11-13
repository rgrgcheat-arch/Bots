RG Shop Bot - PART 5  (includes Part 1 + 2 + 3 + 4)
=====================================================
Replace ALL files in your GitHub repo with these and redeploy. Old data is kept.
Env variables are the same as before.

NEW in Part 5
1) Pay UPI (manual): customer gets a QR for your UPI ID + exact amount, pays, taps "I Have Paid" and sends the UTR (or screenshot).
   YOU get an instant notification with Approve / Reject buttons. Approve = key delivered / wallet credited.
2) Pay Binance (manual): customer sees the amount (also in USDT), your Binance details, pays, then sends the Binance
   Order ID / Transaction ID to you. Same notification + Approve / Reject.
3) Works for both buying a plan and Add Balance (Confirm -> choose payment method).
   Non-INR users (e.g. BDT) get "Pay Local" (your "other countries" payment text) + Pay Binance.
4) Pay QR (auto gateway) stays ready but is hidden until you set the gateway in Settings (API will be connected later).
5) Website -> Settings -> "Manual payments": turn Pay UPI / Pay Binance ON/OFF and write your Binance details.
   Website -> QR / Manual Payments: review list with proof screenshot, Approve / Reject.
6) PREMIUM EMOJI FIX / DIAGNOSIS
   - Website -> Premium Emoji -> "Test premium emoji now"  (or send /emojitest to the bot as admin).
     It tells you exactly if Telegram accepts premium emoji from this bot, and why not.
   - Saving emoji IDs now checks every ID with Telegram and warns about wrong IDs.
   - If Telegram blocks premium emoji the bot automatically shows the normal emoji (buttons never lose their icon).
   - Also fixed: the dashboard "Total users" number was empty.

IMPORTANT about premium emoji
Telegram only shows premium emoji from a bot if the account that CREATED the bot in @BotFather has Telegram Premium
(or the bot has a username bought on Fragment). Premium on the admin account alone is not enough.
