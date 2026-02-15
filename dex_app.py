import streamlit as st
import ccxt
import requests
import pandas as pd
import time
from concurrent.futures import ThreadPoolExecutor

# --- КОНФИГУРАЦИЯ ---
SUPPORTED_CHAINS = {
    'solana': {'name': 'Solana', 'go_id': 'solana'},
    'bsc': {'name': 'BSC', 'go_id': '56'},
    'ethereum': {'name': 'Ethereum', 'go_id': '1'},
    'arbitrum': {'name': 'Arbitrum', 'go_id': '42161'},
    'base': {'name': 'Base', 'go_id': '8453'},
    'polygon': {'name': 'Polygon', 'go_id': '137'},
    'aptos': {'name': 'Aptos', 'go_id': 'aptos'}
}

CEX_LIST = ['bybit', 'mexc', 'lbank2']

st.set_page_config(page_title="Arbitrage Scanner 2026", layout="wide")

# --- ЛОГИКА ---

@st.cache_data(ttl=300) # Кэшируем рынки на 5 минут для скорости
def get_all_cex_markets():
    markets = {}
    for ex_id in CEX_LIST:
        try:
            ex = getattr(ccxt, ex_id)({'enableRateLimit': True})
            m = ex.load_markets()
            # Берем только USDT пары
            markets[ex_id] = {s.split('/')[0]: s for s in m if '/USDT' in s}
        except: continue
    return markets

def check_hp(address, chain_id):
    if chain_id in ['solana', 'aptos']: return "Manual"
    try:
        url = f"https://api.goplussecurity.io/api/v1/token_security/{chain_id}?contract_addresses={address}"
        res = requests.get(url, timeout=5).json()
        data = res['result'][address.lower()]
        if data.get('is_honeypot') == '1': return "❌ SCAM"
        return f"✅ B:{float(data.get('buy_tax', 0))*100:.0f}% S:{float(data.get('sell_tax', 0))*100:.0f}%"
    except: return "N/A"

# --- ИНТЕРФЕЙС ---
st.title("🛰 Global CEX-DEX Scanner")

with st.sidebar:
    st.header("Настройки")
    chain_key = st.selectbox("Сеть:", list(SUPPORTED_CHAINS.keys()))
    min_spread = st.number_input("Мин. спред (%)", value=1.0, step=0.1)
    min_liq = st.number_input("Мин. ликвидность ($)", value=5000)
    max_pairs = st.slider("Глубина поиска на DEX (пар)", 50, 500, 200)

if st.button("🚀 НАЧАТЬ ПОЛНОЕ СКАНИРОВАНИЕ", use_container_width=True):
    # 1. Загружаем рынки бирж (один раз)
    all_cex = get_all_cex_markets()
    
    # 2. Получаем пары с DEX
    with st.spinner('Загружаем пары с DexScreener...'):
        try:
            res = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={chain_key}", timeout=10).json()
            pairs = [p for p in res.get('pairs', []) if p.get('liquidity', {}).get('usd', 0) >= min_liq][:max_pairs]
        except:
            st.error("Ошибка API"); pairs = []

    if not pairs:
        st.warning("Пар не найдено.")
    else:
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()

        # 3. Процесс сравнения
        for i, p in enumerate(pairs):
            sym = p['baseToken']['symbol'].upper()
            status_text.text(f"Проверка {i+1}/{len(pairs)}: {sym}")
            progress_bar.progress((i + 1) / len(pairs))
            
            d_price = float(p['priceUsd'])
            
            # Ищем этот символ на всех наших биржах
            for ex_id, markets in all_cex.items():
                if sym in markets:
                    try:
                        ex = getattr(ccxt, ex_id)()
                        ticker = ex.fetch_ticker(markets[sym])
                        c_price = ticker['bid']
                        
                        if c_price:
                            spread = ((c_price - d_price) / d_price) * 100
                            if min_spread < spread < 50:
                                results.append({
                                    'Токен': sym,
                                    'Спред': f"{spread:.2f}%",
                                    'Биржа': ex_id.upper(),
                                    'DEX Цена': f"{d_price:.6f}",
                                    'CEX Цена': f"{c_price:.6f}",
                                    'Безопасность': check_hp(p['baseToken']['address'], SUPPORTED_CHAINS[chain_key]['go_id']),
                                    'График': f"https://dexscreener.com/{chain_key}/{p['baseToken']['address']}"
                                })
                    except: continue

        status_text.text("Сканирование завершено!")
        if results:
            df = pd.DataFrame(results).sort_values('Спред', ascending=False)
            st.dataframe(df, use_container_width=True, column_config={
                "График": st.column_config.LinkColumn("График", display_text="Открыть")
            }, hide_index=True)
        else:
            st.info("Совпадений не найдено. Попробуйте увеличить глубину поиска или сменить сеть.")
