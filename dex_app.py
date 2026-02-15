import streamlit as st
import ccxt
import requests
import pandas as pd
import time
from concurrent.futures import ThreadPoolExecutor

# --- КОНФИГУРАЦИЯ СЕТЕЙ ---
SUPPORTED_CHAINS = {
    'solana': {'name': 'Solana', 'go_id': 'solana'},
    'bsc': {'name': 'BSC', 'go_id': '56'},
    'ethereum': {'name': 'Ethereum', 'go_id': '1'},
    'arbitrum': {'name': 'Arbitrum', 'go_id': '42161'},
    'base': {'name': 'Base', 'go_id': '8453'},
    'optimism': {'name': 'Optimism', 'go_id': '10'},
    'polygon': {'name': 'Polygon', 'go_id': '137'},
    'aptos': {'name': 'Aptos', 'go_id': 'aptos'},
    'sui': {'name': 'Sui', 'go_id': 'sui'}
}

CEX_LIST = ['bybit', 'mexc', 'lbank2']

st.set_page_config(page_title="DEX-CEX Arb Pro 2026", layout="wide")

# Темная тема
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: white; }
    .stDataFrame { border: 1px solid #30363d; }
    </style>
    """, unsafe_allow_html=True)

# --- ФУНКЦИИ ---

def check_hp(address, chain_id):
    if chain_id in ['solana', 'aptos', 'sui']: return "Manual"
    try:
        url = f"https://api.goplussecurity.io/api/v1/token_security/{chain_id}?contract_addresses={address}"
        res = requests.get(url, timeout=5).json()
        data = res['result'][address.lower()]
        if data.get('is_honeypot') == '1': return "❌ SCAM"
        b_tax = float(data.get('buy_tax', 0)) * 100
        s_tax = float(data.get('sell_tax', 0)) * 100
        return f"✅ B:{b_tax:.0f}% S:{s_tax:.0f}%"
    except: return "N/A"

def get_cex_prices(ex_id, symbols):
    try:
        ex = getattr(ccxt, ex_id)({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})
        ex.load_markets()
        tickers = ex.fetch_tickers()
        return ex_id, {s: tickers[f"{s}/USDT"]['bid'] for s in symbols if f"{s}/USDT" in tickers and tickers[f"{s}/USDT"]['bid']}
    except: return ex_id, {}

# --- ИНТЕРФЕЙС ---
st.title("🛰 DEX-to-CEX Arbitrage Terminal")

with st.sidebar:
    st.header("Настройки")
    chain_key = st.selectbox("Блокчейн для скана:", list(SUPPORTED_CHAINS.keys()), 
                             format_func=lambda x: SUPPORTED_CHAINS[x]['name'])
    min_spread = st.slider("Мин. спред (%)", 0.5, 15.0, 2.0)
    min_liq = st.number_input("Мин. ликвидность ($)", value=10000)
    st.divider()
    st.info("Бот ищет монеты на DEX и проверяет их цену на Bybit, MEXC, LBank.")

# --- ЛОГИКА ---
if st.button("🚀 ЗАПУСТИТЬ ПОИСК СВЯЗОК", use_container_width=True):
    # 1. Скан DexScreener
    try:
        res = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={chain_key}", timeout=10).json()
        pairs = [p for p in res.get('pairs', []) if p.get('liquidity', {}).get('usd', 0) >= min_liq]
    except:
        st.error("Ошибка подключения к DexScreener")
        pairs = []

    if pairs:
        symbols = list(set([p['baseToken']['symbol'].upper() for p in pairs]))
        
        # 2. Скан CEX
        with st.spinner(f'Сверяем {len(symbols)} токенов с биржами...'):
            with ThreadPoolExecutor(max_workers=3) as executor:
                cex_results = dict(list(executor.map(lambda x: get_cex_prices(x, symbols), CEX_LIST)))

        # 3. Формирование таблицы
        results = []
        for p in pairs:
            sym = p['baseToken']['symbol'].upper()
            d_price = float(p['priceUsd'])
            addr = p['baseToken']['address']
            
            for ex_id, prices in cex_results.items():
                if sym in prices:
                    c_price = prices[sym]
                    spread = ((c_price - d_price) / d_price) * 100
                    
                    if min_spread < spread < 40:
                        results.append({
                            'Монета': sym,
                            'Спред (%)': f"{spread:.2f}%",
                            'Блокчейн': SUPPORTED_CHAINS[chain_key]['name'],
                            'DEX Цена': f"{d_price:.6f}",
                            f'CEX {ex_id.upper()}': f"{c_price:.6f}",
                            'Безопасность': check_hp(addr, SUPPORTED_CHAINS[chain_key]['go_id']),
                            'График': f"https://dexscreener.com/{chain_key}/{addr}",
                            'Контракт': addr
                        })

        if results:
            df = pd.DataFrame(results).sort_values('Спред (%)', ascending=False)
            # Отображаем ссылку как кликабельный объект
            st.dataframe(
                df, 
                use_container_width=True, 
                column_config={
                    "График": st.column_config.LinkColumn("График", display_text="Open Chart")
                },
                hide_index=True
            )
        else:
            st.warning("Связок не найдено. Попробуйте сменить сеть.")
