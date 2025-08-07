import asyncio
import time
import datetime
import requests
import hmac
import hashlib
import json

BYBIT_API_KEY = "your_api_key"
BYBIT_API_SECRET = "your_api_secret"
BASE_URL = "https://api.bybit.com"
SYMBOL = "TRXUSDT"
INTERVAL = 60  # 1-minute candles
CONFIRM_INTERVAL = 60 * 60 * 2  # 2 hours window for 1H confirmation

# ---------------------------- Utility Functions ----------------------------

def get_server_time():
    return int(time.time() * 1000)

def sign_request(params):
    sorted_params = sorted(params.items())
    query_string = "&".join([f"{k}={v}" for k, v in sorted_params])
    signature = hmac.new(
        BYBIT_API_SECRET.encode(), query_string.encode(), hashlib.sha256
    ).hexdigest()
    return signature

# ---------------------------- API Callers ----------------------------

def get_kline(symbol, interval, limit=200):
    endpoint = "/v5/market/kline"
    params = {
        "category": "linear",
        "symbol": symbol,
        "interval": str(interval),
        "limit": limit,
    }
    resp = requests.get(BASE_URL + endpoint, params=params)
    data = resp.json()
    return data["result"]["list"] if "result" in data else []

def get_price():
    candles = get_kline(SYMBOL, 1, limit=1)
    return float(candles[-1][4]) if candles else 0  # Closing price of latest candle

# ---------------------------- Strategy Logic ----------------------------

def detect_color(candle):
    open_price = float(candle[1])
    close_price = float(candle[4])
    return "green" if close_price > open_price else "red"

def detect_sequence(candles):
    sequence = []
    prev_color = None
    for candle in candles:
        color = detect_color(candle)
        if color != prev_color:
            sequence = []
        sequence.append(candle)
        prev_color = color
    return sequence

def is_new_high_or_low(seq, last_confirmed, direction):
    if direction == "buy":
        return min([float(c[3]) for c in seq]) > last_confirmed["low"]
    elif direction == "sell":
        return max([float(c[2]) for c in seq]) < last_confirmed["high"]
    return False

def confirm_on_1h_candle(direction, since_timestamp):
    candles = get_kline(SYMBOL, 60, limit=3)  # last 3 one-hour candles
    for candle in candles:
        candle_open_time = int(candle[0])
        if candle_open_time < since_timestamp:
            continue
        open_price = float(candle[1])
        high = float(candle[2])
        low = float(candle[3])
        if direction == "buy" and high > open_price:
            return True
        elif direction == "sell" and low < open_price:
            return True
    return False

# ---------------------------- Trade Execution ----------------------------

def place_market_order(side, qty):
    endpoint = "/v5/order/create"
    timestamp = get_server_time()
    params = {
        "apiKey": BYBIT_API_KEY,
        "timestamp": timestamp,
        "recvWindow": 5000,
        "category": "linear",
        "symbol": SYMBOL,
        "side": side.upper(),
        "orderType": "Market",
        "qty": qty,
        "timeInForce": "GoodTillCancel",
    }
    params["sign"] = sign_request(params)
    response = requests.post(BASE_URL + endpoint, data=params)
    return response.json()

# ---------------------------- Runner Loop ----------------------------

async def run_bot():
    last_confirmed_buy = {"low": 0}
    last_confirmed_sell = {"high": 1e10}
    
    while True:
        candles = get_kline(SYMBOL, 1, limit=50)
        if not candles:
            await asyncio.sleep(60)
            continue
        
        seq = detect_sequence(candles)
        color = detect_color(seq[-1])

        if color == "green" and is_new_high_or_low(seq, last_confirmed_buy, "buy"):
            confirm_from = int(seq[-1][0])
            if confirm_on_1h_candle("buy", confirm_from):
                qty = 100  # Put your dynamic quantity logic here
                place_market_order("Buy", qty)
                last_confirmed_buy["low"] = min([float(c[3]) for c in seq])

        elif color == "red" and is_new_high_or_low(seq, last_confirmed_sell, "sell"):
            confirm_from = int(seq[-1][0])
            if confirm_on_1h_candle("sell", confirm_from):
                qty = 100
                place_market_order("Sell", qty)
                last_confirmed_sell["high"] = max([float(c[2]) for c in seq])
        
        await asyncio.sleep(60)

# ---------------------------- Main Entry ----------------------------

if __name__ == "__main__":
    asyncio.run(run_bot())
