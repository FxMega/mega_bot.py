import yfinance as yf
import time
import requests
import urllib.parse
from datetime import datetime, timezone
import pandas as pd

PHONE = "256788408267"
APIKEY = "6265853"
BRAND_NAME = "FXMEGA UG"
CONTACT_NUMBER = "0700848808"

TRADING_PAIRS_CONFIG = {
    "BTC-USD": {"pair_display_name": "BITCOIN","rsi_buy_threshold": 32,"rsi_sell_threshold": 68,"ema_fast_period": 20,"ema_slow_period": 50,"currency_affected_by_news": "USD","full_strategy_explanation": "BITCOIN uses EMA 20/50 trend filter. BUY only when EMA20 is above EMA50 indicating uptrend AND RSI is below 32 oversold. SELL only when EMA20 is below EMA50 indicating downtrend AND RSI is above 68 overbought. This avoids fake pumps."},
    "ETH-USD": {"pair_display_name": "ETHEREUM","rsi_buy_threshold": 30,"rsi_sell_threshold": 70,"ema_fast_period": 20,"ema_slow_period": 50,"currency_affected_by_news": "USD","full_strategy_explanation": "ETHEREUM similar to Bitcoin but RSI 30/70 wider because ETH is more volatile. EMA20/50 for trend."},
    "SOL-USD": {"pair_display_name": "SOLANA","rsi_buy_threshold": 35,"rsi_sell_threshold": 65,"ema_fast_period": 9,"ema_slow_period": 21,"currency_affected_by_news": "USD","full_strategy_explanation": "SOLANA is very fast moving altcoin, needs fast EMA 9/21 to catch quick moves, RSI 35/65 tight to scalp fast."},
    "BNB-USD": {"pair_display_name": "BNB","rsi_buy_threshold": 38,"rsi_sell_threshold": 62,"ema_fast_period": 20,"ema_slow_period": 50,"currency_affected_by_news": "USD","full_strategy_explanation": "BNB is low volatility coin, uses narrow RSI 38/62 to catch small moves inside range, EMA 20/50."},
    "XRP-USD": {"pair_display_name": "XRP","rsi_buy_threshold": 30,"rsi_sell_threshold": 70,"ema_fast_period": 50,"ema_slow_period": 200,"currency_affected_by_news": "USD","full_strategy_explanation": "XRP respects big trend, uses EMA 50/200, only trades with big trend direction + RSI 30/70."},
    "DOGE-USD": {"pair_display_name": "DOGECOIN","rsi_buy_threshold": 25,"rsi_sell_threshold": 75,"ema_fast_period": 20,"ema_slow_period": 50,"currency_affected_by_news": "USD","full_strategy_explanation": "DOGECOIN is meme coin, only trade extremes. BUY only when RSI below 25 extreme oversold, SELL only when RSI above 75 extreme overbought. Ignores EMA to catch meme pumps."},
    "GC=F": {"pair_display_name": "GOLD","rsi_buy_threshold": 35,"rsi_sell_threshold": 65,"ema_fast_period": 50,"ema_slow_period": 200,"currency_affected_by_news": "USD","full_strategy_explanation": "GOLD uses EMA 50/200. BUY only if price is above EMA200 (major uptrend) and RSI below 35 dip. SELL only if price below EMA50 and RSI above 65. Gold respects 200 EMA support."},
    "SI=F": {"pair_display_name": "SILVER","rsi_buy_threshold": 40,"rsi_sell_threshold": 60,"ema_fast_period": 20,"ema_slow_period": 50,"currency_affected_by_news": "USD","full_strategy_explanation": "SILVER is choppy, uses RSI 40/60 wider than gold, EMA 20/50 to avoid false breakouts."},
    "EURUSD=X": {"pair_display_name": "EURUSD","rsi_buy_threshold": 30,"rsi_sell_threshold": 70,"ema_fast_period": 50,"ema_slow_period": 200,"currency_affected_by_news": "EUR","full_strategy_explanation": "EURUSD forex low volatility needs EMA 50/200 big trend filter + RSI 30/70 to avoid noise."},
    "GBPUSD=X": {"pair_display_name": "GBPUSD","rsi_buy_threshold": 32,"rsi_sell_threshold": 68,"ema_fast_period": 20,"ema_slow_period": 50,"currency_affected_by_news": "GBP","full_strategy_explanation": "GBPUSD more volatile than EURUSD, uses EMA 20/50 faster and RSI 32/68."},
    "USDJPY=X": {"pair_display_name": "USDJPY","rsi_buy_threshold": 25,"rsi_sell_threshold": 75,"ema_fast_period": 50,"ema_slow_period": 200,"currency_affected_by_news": "JPY","full_strategy_explanation": "USDJPY trends very strongly, only trade extremes RSI 25/75 + EMA 50/200 to catch strong trend continuation."},
}

def get_red_news_blocked_currencies():
    blocked_currencies_list = set()
    try:
        print("Starting RED NEWS check from ForexFactory...")
        forex_factory_url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        response_from_api = requests.get(forex_factory_url, timeout=10)
        json_data_of_events = response_from_api.json()
        current_time_utc = datetime.now(timezone.utc)
        for single_event in json_data_of_events:
            impact_level = single_event.get("impact")
            if impact_level != "High": continue
            event_date_string = single_event.get("date")
            try: event_time = datetime.fromisoformat(event_date_string.replace("Z", "+00:00"))
            except Exception: continue
            difference_in_minutes = (event_time - current_time_utc).total_seconds() / 60.0
            if -30 <= difference_in_minutes <= 60:
                currency_code_from_event = single_event.get("country", "").strip()
                event_title = single_event.get("title", "")
                if currency_code_from_event:
                    blocked_currencies_list.add(currency_code_from_event)
                    print(f"🔴 RED NEWS DETECTED: {currency_code_from_event} - {event_title} happening in {difference_in_minutes:.0f} minutes")
    except Exception as error_message:
        print(f"RED NEWS check failed: {error_message}")
    return blocked_currencies_list

def calculate_rsi_and_ema_indicators(dataframe_with_prices, fast_ema_period_value, slow_ema_period_value):
    if isinstance(dataframe_with_prices.columns, pd.MultiIndex):
        dataframe_with_prices.columns = dataframe_with_prices.columns.get_level_values(0)
    closing_prices_series = dataframe_with_prices['Close']
    if isinstance(closing_prices_series, pd.DataFrame):
        closing_prices_series = closing_prices_series.iloc[:, 0]
    closing_prices_series = pd.Series(closing_prices_series).dropna()
    price_difference = closing_prices_series.diff()
    positive_gains = price_difference.where(price_difference > 0, 0).rolling(window=14).mean()
    negative_losses = -price_difference.where(price_difference < 0, 0).rolling(window=14).mean()
    relative_strength = positive_gains / negative_losses
    rsi_indicator_series = 100 - (100 / (1 + relative_strength))
    ema_fast_series = closing_prices_series.ewm(span=fast_ema_period_value).mean()
    ema_slow_series = closing_prices_series.ewm(span=slow_ema_period_value).mean()
    def safe_last_float(s):
        if isinstance(s, pd.DataFrame): v = s.iloc[-1, 0]
        else: v = s.iloc[-1]
        if isinstance(v, pd.Series): v = v.iloc[0]
        return float(v)
    last_rsi_value = safe_last_float(rsi_indicator_series)
    last_ema_fast_value = safe_last_float(ema_fast_series)
    last_ema_slow_value = safe_last_float(ema_slow_series)
    last_closing_price = safe_last_float(closing_prices_series)
    return last_rsi_value, last_ema_fast_value, last_ema_slow_value, last_closing_price

def send_whatsapp_alert_message(full_message_text):
    encoded_message_for_url = urllib.parse.quote(full_message_text)
    call_me_bot_api_url = f"https://api.callmebot.com/whatsapp.php?phone={PHONE}&text={encoded_message_for_url}&apikey={APIKEY}"
    try:
        request_response = requests.get(call_me_bot_api_url, timeout=15)
        print(f"SENT SUCCESSFULLY: {full_message_text[:150]}... API Response: {request_response.text[:100]}")
    except Exception as sending_error:
        print(f"FAILED TO SEND: {sending_error}")

print("=================================================================")
print(f"{BRAND_NAME} v6 PRO FINAL - STARTING ONE HOURLY RUN")
print("=================================================================")
blocked_currencies_now = get_red_news_blocked_currencies()
print(f"Currencies blocked: {blocked_currencies_now if blocked_currencies_now else 'None'}")
for trading_symbol, pair_config in TRADING_PAIRS_CONFIG.items():
    currency_for_news = pair_config["currency_affected_by_news"]
    display_name = pair_config["pair_display_name"]
    if currency_for_news in blocked_currencies_now: print(f"{display_name} SKIPPED - RED NEWS {currency_for_news}"); continue
    if "USD" in blocked_currencies_now and display_name in ["GOLD","SILVER","BITCOIN","ETHEREUM","BNB"]: print(f"{display_name} SKIPPED - USD RED NEWS"); continue
    try:
        print(f"\n--- ANALYZING {display_name} ({trading_symbol}) ---")
        print(f"Strategy Details: {pair_config['full_strategy_explanation']}")
        price_dataframe = yf.download(trading_symbol, period="5d", interval="15m", progress=False, auto_adjust=True)
        if price_dataframe.empty or len(price_dataframe) < 60: print(f"{display_name} -> NO DATA"); continue
        current_rsi, current_ema_fast, current_ema_slow, current_market_price = calculate_rsi_and_ema_indicators(price_dataframe, pair_config["ema_fast_period"], pair_config["ema_slow_period"])
        print(f"{display_name} CURRENT: Price={current_market_price:.2f} RSI={current_rsi:.1f} EMA{pair_config['ema_fast_period']}={current_ema_fast:.2f} EMA{pair_config['ema_slow_period']}={current_ema_slow:.2f}")
        is_buy_signal=False; is_sell_signal=False; reason_for_signal_text=""
        if display_name in ["DOGECOIN","USDJPY"]:
            if current_rsi < pair_config["rsi_buy_threshold"]: is_buy_signal=True; reason_for_signal_text=f"EXTREME OVERSOLD RSI {current_rsi:.1f} < {pair_config['rsi_buy_threshold']} - {pair_config['full_strategy_explanation']}"
            elif current_rsi > pair_config["rsi_sell_threshold"]: is_sell_signal=True; reason_for_signal_text=f"EXTREME OVERBOUGHT RSI {current_rsi:.1f} > {pair_config['rsi_sell_threshold']} - {pair_config['full_strategy_explanation']}"
        elif display_name == "GOLD":
            if current_rsi < pair_config["rsi_buy_threshold"] and current_market_price > current_ema_slow: is_buy_signal=True; reason_for_signal_text=f"GOLD UPTREND: Price {current_market_price:.2f} > EMA200 {current_ema_slow:.2f} + RSI dip {current_rsi:.1f}"
            elif current_rsi > pair_config["rsi_sell_threshold"] and current_market_price < current_ema_fast: is_sell_signal=True; reason_for_signal_text=f"GOLD DOWNTREND: Price {current_market_price:.2f} < EMA50 {current_ema_fast:.2f} + RSI high {current_rsi:.1f}"
        else:
            if current_rsi < pair_config["rsi_buy_threshold"] and current_ema_fast > current_ema_slow: is_buy_signal=True; reason_for_signal_text=f"UPTREND CONFIRMED: EMA{pair_config['ema_fast_period']} {current_ema_fast:.2f} > EMA{pair_config['ema_slow_period']} {current_ema_slow:.2f} + RSI oversold {current_rsi:.1f} < {pair_config['rsi_buy_threshold']}"
            elif current_rsi > pair_config["rsi_sell_threshold"] and current_ema_fast < current_ema_slow: is_sell_signal=True; reason_for_signal_text=f"DOWNTREND CONFIRMED: EMA{pair_config['ema_fast_period']} {current_ema_fast:.2f} < EMA{pair_config['ema_slow_period']} {current_ema_slow:.2f} + RSI overbought {current_rsi:.1f} > {pair_config['rsi_sell_threshold']}"
        entry_price_value=current_market_price
        if is_buy_signal:
            if display_name in ["BITCOIN","ETHEREUM","SOLANA","BNB","XRP","DOGECOIN"]: stop_loss_for_buy=entry_price_value*0.975; take_profit_1_for_buy=entry_price_value*1.015; take_profit_2_for_buy=entry_price_value*1.03; take_profit_3_for_buy=entry_price_value*1.06
            elif display_name in ["GOLD","SILVER"]: stop_loss_for_buy=entry_price_value*0.992; take_profit_1_for_buy=entry_price_value*1.005; take_profit_2_for_buy=entry_price_value*1.01; take_profit_3_for_buy=entry_price_value*1.015
            else: stop_loss_for_buy=entry_price_value*0.995; take_profit_1_for_buy=entry_price_value*1.003; take_profit_2_for_buy=entry_price_value*1.006; take_profit_3_for_buy=entry_price_value*1.009
            final_message_to_send=f"""{BRAND_NAME}\n{display_name} BUY SIGNAL\nENTRY PRICE: {entry_price_value:.2f}\nTAKE PROFIT 1: {take_profit_1_for_buy:.2f}\nTAKE PROFIT 2: {take_profit_2_for_buy:.2f}\nTAKE PROFIT 3: {take_profit_3_for_buy:.2f}\nSTOP LOSS: {stop_loss_for_buy:.2f}\nRSI VALUE: {current_rsi:.1f}\nREASON: {reason_for_signal_text}\nRED NEWS: No RED news - safe\n{CONTACT_NUMBER}"""
            send_whatsapp_alert_message(final_message_to_send); time.sleep(6)
        elif is_sell_signal:
            if display_name in ["BITCOIN","ETHEREUM","SOLANA","BNB","XRP","DOGECOIN"]: stop_loss_for_sell=entry_price_value*1.025; take_profit_1_for_sell=entry_price_value*0.985; take_profit_2_for_sell=entry_price_value*0.97; take_profit_3_for_sell=entry_price_value*0.94
            elif display_name in ["GOLD","SILVER"]: stop_loss_for_sell=entry_price_value*1.008; take_profit_1_for_sell=entry_price_value*0.995; take_profit_2_for_sell=entry_price_value*0.99; take_profit_3_for_sell=entry_price_value*0.985
            else: stop_loss_for_sell=entry_price_value*1.005; take_profit_1_for_sell=entry_price_value*0.997; take_profit_2_for_sell=entry_price_value*0.994; take_profit_3_for_sell=entry_price_value*0.991
            final_message_to_send=f"""{BRAND_NAME}\n{display_name} SELL SIGNAL\nENTRY PRICE: {entry_price_value:.2f}\nTAKE PROFIT 1: {take_profit_1_for_sell:.2f}\nTAKE PROFIT 2: {take_profit_2_for_sell:.2f}\nTAKE PROFIT 3: {take_profit_3_for_sell:.2f}\nSTOP LOSS: {stop_loss_for_sell:.2f}\nRSI VALUE: {current_rsi:.1f}\nREASON: {reason_for_signal_text}\nRED NEWS: No RED news - safe\n{CONTACT_NUMBER}"""
            send_whatsapp_alert_message(final_message_to_send); time.sleep(6)
        else: print(f"{display_name} -> WAIT: No signal, RSI {current_rsi:.1f}")
    except Exception as error_in_loop: print(f"Error processing {display_name} ({trading_symbol}): {error_in_loop}")
    print("Waiting 1 second..."); time.sleep(1)
print("=================================================================")
print("FXMEGA UG v6 PRO FINAL - Hourly run completed successfully")
print("=================================================================")
