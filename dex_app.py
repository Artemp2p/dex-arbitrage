import streamlit as st
import ccxt
import requests
import pandas as pd
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# --- КОНФИГУРАЦИЯ СЕТЕЙ (Chain IDs для GoPlus) ---
SUPPORTED_CHAINS = {
    'solana': {'name': 'Solana (SOL)', 'id': 'solana'},
    'eth': {'name': 'Ethereum (ETH)', 'id': '1'},
    'bsc': {'name': 'BSC (BNB)', 'id': '56'},
    'arbitrum': {'name': 'Arbitrum (ARB)', 'id': '42161'},
    'polygon': {'name': 'Polygon (MATIC)', 'id': '137'},
    'avalanche': {'name': 'Avalanche (AVAX)', 'id': '43114'},
    'optimism': {'name': 'Optimism (OP)', 'id': '10'},
    'base': {'name': 'Base', 'id': '8453'},
    'aptos': {'name': 'Aptos (APT)', 'id': 'aptos'},
    'sui': {'name': 'Sui (SUI)', 'id': 'sui'}
}

CEX_LIST = ['bybit', 'mexc', 'lbank2']

st.set_page_config(page_title="CEX-DEX Arb 2026", layout="wide")

# Темная тема
st.markdown("""
    <style>
    .stApp { background-color: #0b0e14; color: #e1e1e1; }
    .stDataFrame { border: 1px solid #1f2937; }
    </style>
    """, unsafe_allow_html=True)

# --- ЛОГИКА ПРОВЕРКИ ---

def check_security(chain_id, address):
    """Проверка HoneyPot и налогов через GoPlus"""
    if chain_id in ['solana', 'aptos', 'sui']:
        return "Manual Check Required"
    try:
        url = f"https://api.goplussecurity.io/api/v1/token_security/{chain_id}?contract_addresses={address}"
        res = requests.get(url, timeout=5).json()
        data = res.get('result', {}).get(address.lower(), {})
        if not data: return "No Security Data"
        
        if data.get('is_honeypot') == '1': return "❌ HONEYPOT"
        
        b_tax = float(data.get('buy_tax', 0)) * 100
        s_tax = float(data.get('sell_tax', 0)) * 100
        return f"✅ Buy: {b_tax:.1f}% | Sell: {s_tax:.1f}%"
    except:
        return "Check Error"

def get_dex_pairs(chain_name):
    """Загрузка данных с DexScreener"""
    try:
        url = f"https://api.dexscreener.com/latest/dex/search?q={chain_name}"
        res = requests.get(url, timeout=10).json()
        return [p for p in res.get('pairs', []) if p.get('quoteToken', {}).get('symbol') in ['USDT', 'USDC']]
    except:
        return []

def get_cex_ticker(ex_id, symbols, proxy=None):
    """Стабильное получение цен с CEX"""
    try:
        # Инициализация биржи с принудительным Spot режимом
        ex = getattr(ccxt, ex_id)({
            'enableRateLimit': True,
            'timeout': 20000,
            'options': {'defaultType': 'spot'}
        })
        if proxy:
            ex.proxies = {'http': proxy, 'https': proxy}
        
        # Важно: загружаем рынки перед поиском
        ex.load_markets()
        tickers = ex.fetch_tickers()
        
        found_data = {}
        for s in symbols:
            pair = f"{s}/USDT"
            if pair in tickers:
                t = tickers[pair]
                if t['bid'] and t['ask']:
                    found_data[s] = {'bid': t['bid'], 'ask': t['ask']}
        return ex_id, found_data
    except Exception as e:
        return ex_id, {}

# --- ИНТЕРФЕЙС ---
st.title("🔗 CEX-DEX Arb Scanner Pro")

with st.sidebar:
    st.header("Настройки")
    chain_key = st.selectbox("Блокчейн:", list(SUPPORTED_CHAINS.keys()), 
                             format_func=lambda x: SUPPORTED_CHAINS[x]['name'])
    proxy_url = st.text_input("Прокси (обязательно для облака):", placeholder="http://user:pass@ip:port")
    min_spread = st.slider("Мин. профит (%)", 1.0, 10.0, 2.0)
    min_liq = st.number_input("Мин. ликвидность ($)", value=5000)
    
    st.divider()
    auto_refresh = st.checkbox("🔄 Авто-обновление (5 мин)")

# --- ОСНОВНОЙ ЦИКЛ ---
def run_scanner():
    st.write(f"🕒 Обновлено: {datetime.now().strftime('%H:%M:%S')}")
    
    # 1. Данные с DEX
    dex_raw = get_dex_pairs(chain_key)
    dex_clean = [p for p in dex_raw if p.get('liquidity', {}).get('usd', 0) >= min_liq]
    
    if not dex_clean:
        st.warning("Монеты не найдены. Попробуйте сменить сеть или уменьшить порог ликвидности.")
        return

    symbols = list(set([p['baseToken']['symbol'].upper() for p in dex_clean]))

    # 2. Данные с CEX
    with st.spinner(f'Сверяем {len(symbols)} монет с биржами...'):
        with ThreadPoolExecutor(max_workers=3) as executor:
            cex_results = dict(list(executor.map(lambda x: get_cex_ticker(x, symbols, proxy_url), CEX_LIST)))

    # 3. Сравнение
    table_data = []
    for d in dex_clean:
        s = d['baseToken']['symbol'].upper()
        d_price = float(d['priceUsd'])
        
        for cex_id, data in cex_results.items():
            if s in data:
                cex = data[s]
                # Считаем спред (Купить на DEX - Продать на CEX)
                spread = ((cex['bid'] - d_price) / d_price) * 100
                
                if min_spread < spread < 50:
                    security = check_security(SUPPORTED_CHAINS[chain_key]['id'], d['baseToken']['address'])
                    if "❌" in security: continue
                    
                    table_data.append({
                        'Монета': s,
                        'ПРОФИТ': f"{spread:.2f}%",
                        'КУПИТЬ': f"DEX ({d['dexId']})",
                        'ПРОДАТЬ': cex_id.upper(),
                        'БЕЗОПАСНОСТЬ': security,
                        'DEX Цена': f"{d_price:.6f}",
                        'CEX Цена': f"{cex['bid']:.6f}",
                        'Контракт': d['baseToken']['address']
                    })

    if table_data:
        st.dataframe(pd.DataFrame(table_data).sort_values('ПРОФИТ', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("Активных связок не найдено. Проверьте настройки прокси.")

if auto_refresh:
    run_scanner()
    time.sleep(300)
    st.rerun()
else:
    if st.button("🚀 ЗАПУСТИТЬ СКАНЕР", use_container_width=True):
        run_scanner()
