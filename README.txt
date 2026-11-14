RG Shop Bot - V8  (includes everything from V1 to V7)
=====================================================
Replace ALL files in your GitHub repo with these and redeploy. Old data is kept. Env variables are the same.

1) YOUR GATEWAY (FamPay + Paytm) - fully automatic
   Website -> Settings -> "Payment Gateway":
     Gateway: Paytm or FamPay  |  API token  |  Base URL (changeable any time)  ->  press "Save & Connect".
   Connect shows "Connected successfully" (or the exact problem, e.g. Invalid API token).
   Pay via UPI creates the QR, detects the payment by itself (polling + webhook), then delivers the key / adds wallet balance.
   FamPay adds paise to the amount (e.g. 90.90 -> 91.27): the bot, QR page and success message show the EXACT amount to pay.
   Webhook (optional, faster): copy the Webhook URL shown in Settings into your gateway dashboard -> Webhooks,
   and paste its signing secret in Settings. Signature + timestamp + amount are verified. Without the secret the bot
   still works by checking payments every few seconds.
   If the gateway token is empty, Pay via UPI falls back to the manual UPI flow (UTR + admin approve).

2) STORE SCREENS (same style as your screenshots, prices in INR only)
   Shop: bot name, line, Product Lineup, your 4 lines (editable in Settings), "Pick what you want", products as buttons.
   Product: name / Account Type (User or Reseller) / See Current Plans & Pricing / tree of plans / CHOOSE A PLAN, Buy buttons.
   Checkout Summary: product, plan, quantity, price, Final Total (+ name, ID, phone, wallet balance).
   Buttons in order: Pay via Wallet (always shown) | Pay via UPI | Pay via Binance | Apply Coupon Code | BACK.
   After a purchase: key + [Join Telegram] (product's update group) + [Main Panel]. Not shown for Add Balance.
   Reseller sees the reseller price automatically (Users -> "Make reseller").

3) ADMIN: ADD PRODUCT (Website -> Products -> + Add product)
   Product name + update group link, then plan rows: Duration + Hours/Days + User price + Reseller price,
   "+ Add another plan" for more. Product page: edit name/link, edit each plan (duration, unit, prices), add plans, delete.

4) Phone number verification ON/OFF  (Settings -> "Store screen & sign-up").
5) Everything is INR now. Old users with other currencies were converted once to INR automatically.

V7 CHANGES
- Pay via UPI screen = your screenshot: QR photo + "UPI PAYMENT GATEWAY" caption (Amount, Order, Expires, Instant Verification, How to pay).
  Only ONE button: "Back to Store" (goes to the main menu). No verify button - payment is detected automatically,
  then the key is delivered. Order ID looks like ORD2026111414220951360A and is the same ID sent to your gateway.
  Amount = exact amount to pay (FamPay paise included).
- Wallet purchase message = your screenshot (WALLET PAYMENT SUCCESSFUL / ORDER DETAILS / YOUR KEY ...),
  buttons: "Join Telegram Group" (product update group) and "Main Menu".
- Purchase paid by UPI / Binance: first a "PAYMENT SUCCESSFUL" notification (Order ID, Transaction ID, amount),
  then the same delivery message (title PAYMENT SUCCESSFUL, Method: UPI Method / Binance Method) with the same two buttons.

V8 CHANGES
- QR not paid within 5 minutes -> the QR message is removed and this message is sent (same as your screenshot):
  PAYMENT EXPIRED / Order Id : <real order ID> / Not paid within 5 minutes / QR / payment details are no longer valid / Tap /start to begin a new order.
  The time is Settings -> "Payment valid for (minutes)" (now 5 by default). A payment that still arrives late is added automatically.
- FIND WHO MADE AN ORDER (admin):
  Website -> "Find Order": type the order ID (ORD... payment order, WAL... shop order), a transaction ID or a user ID -> shows the user
  (name, ID, @username, phone, wallet) and the order details. Website -> QR Payments also has a search box.
  Telegram (admin only): /find ORD2026...  gives the same details in the bot.
