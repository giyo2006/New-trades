from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pybit.unified_trading import HTTP
import os
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import asyncio

app = FastAPI()

# === Environment Variables ===
MAIN_API_KEY = os.getenv("MAIN_API_KEY")
MAIN_API_SECRET = os.getenv("MAIN_API_SECRET")
SUB_API_KEY = os.getenv("SUB_API_KEY")
SUB_API_SECRET = os.getenv("SUB_API_SECRET")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")
SUB_UID = os.getenv("SUB_UID")

main_session = HTTP(api_key=MAIN_API_KEY, api_secret=MAIN_API_SECRET)
sub_session = HTTP(api_key=SUB_API_KEY, api_secret=SUB_API_SECRET)

last_trade = {"type": None, "outcome": None}
trade_log = []

# === Get Balance ===
def get_usdt_balance(session):
    try:
        data = session.get_wallet_balance(accountType="UNIFIED")
        coins = data["result"]["list"][0]["coin"]
        usdt = next((x for x in coins if x["coin"] == "USDT"), None)
        return float(usdt["equity"]) if usdt else 0
    except:
        return 0

# === Rebalance ===
def rebalance_funds():
    try:
        main = get_usdt_balance(main_session)
        sub = get_usdt_balance(sub_session)
        total = main + sub
        target = total / 2
        if abs(main - sub) < 0.1:
            print("✅ Balance already even.")
            return
        amount = abs(main - target)
        transfer_type = "MAIN_SUB" if main > target else "SUB_MAIN"
        main_session.create_internal_transfer(
            transfer_type=transfer_type,
            coin="USDT",
            amount=str(round(amount, 2)),
            sub_member_id=SUB_UID
        )
        print("🔁 Rebalanced main/sub")
    except Exception as e:
        print("❌ Rebalance failed:", e)

# === Close All TRXUSDT Positions ===
def close_trades(session, label):
    try:
        pos = session.get_positions(category="linear", symbol="TRXUSDT")["result"]["list"]
        closed = False
        for p in pos:
            size = float(p["size"])
            side = p["side"]
            if size > 0:
                close_side = "Sell" if side == "Buy" else "Buy"
                session.place_order(
                    category="linear",
                    symbol="TRXUSDT",
                    side=close_side,
                    order_type="Market",
                    qty=size,
                    reduce_only=True,
                    position_idx=0
                )
                print(f"✅ {label} Account: Closed {side} {size}")
                closed = True
        return closed
    except Exception as e:
        print(f"❌ {label} close failed:", e)
        return False

# === Email Summary ===
def send_email(subject, body):
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        print("📧 Email sent")
    except Exception as e:
        print("❌ Email failed:", e)

def summarize_trades():
    if not trade_log:
        return None
    wins = sum(1 for t in trade_log if t["outcome"] == "win")
    losses = sum(1 for t in trade_log if t["outcome"] == "loss")
    return f"WINS: {wins}\nLOSSES: {losses}"

@app.on_event("startup")
async def startup():
    async def summary_loop():
        while True:
            now = datetime.utcnow()
            midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0)
            await asyncio.sleep((midnight - now).total_seconds())
            summary = summarize_trades()
            if summary:
                send_email("Daily Trade Summary", summary)
                trade_log.clear()
    async def keep_alive():
        while True:
            await asyncio.sleep(3600)
    asyncio.create_task(summary_loop())
    asyncio.create_task(keep_alive())

# === Signal Receiver ===
@app.post("/signal")
async def receive_signal(request: Request):
    try:
        body = (await request.body()).decode().strip()
        print("\n📩 Signal:\n", body)
        lines = body.splitlines()
        if len(lines) < 2:
            return JSONResponse(content={"error": "Bad format"}, status_code=400)

        symbol = lines[0].strip().upper()
        signal_type = lines[1].lower()

        entry = sl = tp = None
        for line in lines:
            if "entry:" in line.lower():
                entry = float(line.split(":")[1])
            elif "sl:" in line.lower():
                sl = float(line.split(":")[1])
            elif "tp:" in line.lower():
                tp = float(line.split(":")[1])

        is_buy = "buy" in signal_type
        session = sub_session if is_buy else main_session
        label = "Sub" if is_buy else "Main"

        if entry and sl and tp:
            rr = abs(entry - sl)
            boosted = last_trade["outcome"] == "loss" and last_trade["type"] != ("buy" if is_buy else "sell")
            tp = entry + 1.5 * rr + 0.005 * entry if boosted and is_buy else \
                 entry - 1.5 * rr - 0.005 * entry if boosted and not is_buy else \
                 entry + rr if is_buy else entry - rr

            balance = get_usdt_balance(session)
            total = get_usdt_balance(main_session) + get_usdt_balance(sub_session)
            risk = total * 0.10
            sl_diff = abs(entry - sl)
            leverage = 75
            qty_risk = risk / sl_diff
            max_qty = ((balance * leverage) / entry) * 0.9
            qty = max(1, round(min(qty_risk, max_qty)))

            # Entry
            session.place_order(
                category="linear",
                symbol=symbol,
                side="Buy" if is_buy else "Sell",
                order_type="Market",
                qty=qty,
                position_idx=0
            )

            # TP/SL
            tick_size = float(session.get_instruments_info(category="linear", symbol=symbol)['result']['list'][0]['priceFilter']['tickSize'])
            round_price = lambda x: round(round(x / tick_size) * tick_size, 8)
            tp_price = round_price(tp)
            sl_price = round_price(sl)
            for price in [tp_price, sl_price]:
                session.place_order(
                    category="linear",
                    symbol=symbol,
                    side="Sell" if is_buy else "Buy",
                    order_type="Limit",
                    price=price,
                    qty=qty,
                    reduce_only=True,
                    time_in_force="GoodTillCancel",
                    close_on_trigger=True,
                    position_idx=0
                )

            last_trade.update({"type": "buy" if is_buy else "sell", "outcome": None})
            rebalance_funds()
            return {
                "status": "Trade placed",
                "entry": entry,
                "tp": tp,
                "sl": sl,
                "qty": qty,
                "tp_mode": "BOOSTED" if boosted else "NORMAL"
            }

        else:
            closed = close_trades(session, label)
            if closed:
                rebalance_funds()
                return {"status": f"{label} trades closed and rebalanced"}
            else:
                return {"status": "No trades to close"}

    except Exception as e:
        print("❌ Error:", str(e))
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/")
def health():
    return {"status": "Bot is online"
