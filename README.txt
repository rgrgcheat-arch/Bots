RG Shop Bot - V10 = PART 10 / 2 (FINAL)  (includes everything from V1 to V9 part 9)
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

================ V9 - PART 9 (first half) ================
1) PREMIUM EMOJI - every button / line has its OWN slot (Website -> Premium Emoji, grouped)
   - Main menu: Shop Now, Add Balance, All History, My Profile, Referral, Tutorial, All Update File, Support = 8 separate slots.
   - Referral screen and Tutorial screen have their own slots too. Old IDs are copied once; the 3 Referral slots start EMPTY
     (set the emoji you want there). Saving warns you if the same ID is used in two places.
   - Button "Send main menu / shop / referral / tutorial to my Telegram" = real preview.
2) PRODUCT + PLAN EMOJI (Website -> Products)
   - "One emoji for ALL products" and "One emoji for ALL plans (A to Z)". Plans: shown on every plan line and Buy button.
   - Single product: open the product -> "Premium emoji ID for THIS product" (wins over the all-products emoji).
   - "Save & use for ALL products" clears every single-product emoji.
3) USER MESSAGES (new style, premium emoji slots 'Purchase / balance confirmation')
   - Key bought (wallet / UPI / Binance): Purchase Confirmed + Order Details + License Key.  Buttons: Join Update Group + Back to Main Menu.
   - Balance added: Payment Confirmed + Add Wallet Balance + Current Balance.  Button: Back to Main Menu only.
4) ADMIN NOTIFICATIONS (premium emoji slots 'Admin notifications'; each has a Contact User button)
   - NEW HACK PURCHASE (user or reseller, any payment method)
   - NEW WALLET BALANCE ADDED (previous / current balance, hacks purchased, total deposited, UTR)
   - PAYMENT SUCCESS - KEY DELIVERY FAILED (name, username, user ID, chat ID, phone ... + refund note)
   - NEW USER VERIFIED
   Settings -> "Admin notifications": ON/OFF for each, optional group/channel chat ID,
   and "Send sample messages to my Telegram" to preview everything with fake data.

================ V10 - PART 10 (second half): PANEL API ================
New file: panel.py.  New website tab: "Panel API".   Files changed: db.py, bot.py, web.py, main.py.
Replace ALL files in your GitHub repo and redeploy. Old data is kept (new columns are added automatically).

1) CONNECT  (Website -> Panel API -> step 1)
   Server URL (default https://official2-qg3g.onrender.com) + API token. Both can be changed any time.
   [Save & Connect] -> "Connect successful (username, balance ... INR)" or the exact problem (Invalid API token ...).
   [Check Balance] -> your panel balance.   [Show Products] -> every product that exists on your panel.
   (A sleeping Render panel can need up to a minute for the first call - just press again.)

2) ADD PRODUCTS  (Show Products)
   Tick the products you want and press [Add selected], or press [Add ALL products].
   Products, plans and prices come from the panel; you never add them by hand. Keys are bought from the panel
   automatically when a customer buys (wallet, UPI QR, Binance - all payment methods).
   Adding again later is safe: it only refreshes prices and adds NEW plans.

3) YOUR PRICES = PANEL PRICE + %   (Panel API -> step 2)
   Reseller %  (default 25)   and   User %  (default 200)  -> panel price 100 = reseller 125 / user 300.
   [Save %] = new products use it.   [Save & apply to ALL products] = every product is re-priced at once.
   A price you edit by hand on a product page is kept ("price: manual"); press [Auto] there to go back to the % price.
   The Products page shows the "Panel cost" of every plan.

4) AUTO PRICE SYNC (Panel API -> step 3)
   Every X minutes (default 60) the bot reads the panel prices again, applies your % and adds new plans.
   [Sync prices now] does it immediately.  Can be switched OFF.

5) WHEN A PURCHASE FAILS (panel says no / panel down / no panel balance)
   - Panel clearly refuses -> money is returned AUTOMATICALLY (wallet purchase: wallet refunded;
     UPI/QR payment: the amount is added to the user's wallet). The user gets a clear message.
   - Panel does not answer / crashes (unknown if the key was made) -> NO automatic refund, so you can never lose a key
     AND the money. The user is told "your order is being processed, do not buy again".
   - In both cases YOU get the alert immediately (name, username, user ID, chat ID, phone, product, plan, amount,
     order ID, reason, what happened to the wallet) with a Contact User button.
     For the "unknown" case check the panel order history, then send the key or add balance (Website -> Users).
   - Double tap on Buy while the panel is working is blocked ("previous order still processing").

Products you added the old way (keys pasted by hand) keep working exactly as before.
