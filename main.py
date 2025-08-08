import requests
import datetime

# Function to fetch candlestick data from Bybit
def get_bybit_ohlc(symbol="TRXUSDT", interval="5"):
    url = "https://api.bybit.com/v5/market/kline"
    params = {
        "category": "linear",
        "symbol": symbol,
        "interval": interval,
        "limit": 2  # Get last 2 candles (to confirm latest closed candle)
    }
    response = requests.get(url, params=params)
    data = response.json()

    if data["retCode"] != 0:
        print("Error:", data["retMsg"])
        return None

    candles = data["result"]["list"]
    return candles

# Function to convert to Heikin Ashi candles
def convert_to_heikin_ashi(candles):
    ha_candles = []
    prev_ha_close = None
    prev_ha_open = None

    for candle in reversed(candles):  # Reverse so oldest is first
        ts, o, h, l, c, vol, turnover = candle
        o, h, l, c = float(o), float(h), float(l), float(c)

        # Calculate Heikin Ashi values
        ha_close = (o + h + l + c) / 4
        if prev_ha_open is None:
            ha_open = (o + c) / 2
        else:
            ha_open = (prev_ha_open + prev_ha_close) / 2

        ha_high = max(h, ha_open, ha_close)
        ha_low = min(l, ha_open, ha_close)

        ha_candles.append({
            "time": datetime.datetime.fromtimestamp(int(ts) / 1000),
            "open": ha_open,
            "high": ha_high,
            "low": ha_low,
            "close": ha_close
        })

        prev_ha_close = ha_close
        prev_ha_open = ha_open

    return ha_candles

# Main bot function
def bot_log():
    candles = get_bybit_ohlc()
    if not candles:
        return

    ha_candles = convert_to_heikin_ashi(candles)

    latest_candle = ha_candles[-1]  # Most recent candle
    candle_color = "GREEN" if latest_candle["close"] > latest_candle["open"] else "RED"

    print(f"[{latest_candle['time']}] {candle_color} candle")
    print(f"Open: {latest_candle['open']:.6f}")
    print(f"High: {latest_candle['high']:.6f}")
    print(f"Low:  {latest_candle['low']:.6f}")
    print(f"Close:{latest_candle['close']:.6f}")

# Run bot
if __name__ == "__main__":
    bot_log()
