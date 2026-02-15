import streamlit as st
import ccxt
import requests
import pandas as pd
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# --- КОНФИГУРАЦИЯ СЕТЕЙ ---
SUPPORTED_CHAINS = {
    'solana': {'name': 'Solana (SOL)', 'id': '1'}, # ID для GoPlus
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

st.set_page_config(page_title="CEX-DEX Arb + HoneyPot Check", layout="wide")

# Темная тема
st.markdown("""
    <style>
    .stApp { background-color: #0b0e14; color: #e1e1e1; }
    .stDataFrame { border: 1px solid #1f2937; }
    .status-safe { color: #00ff00; }
    .status-risk { color: #ff4b4b; }
    </style>
    """, unsafe_allow_html=True)

# --- ФУНКЦИИ ПРОВЕРКИ ---

def check_honeypot(chain_id, address):
    """Проверка токена на HoneyPot и налоги через GoPlus Security"""
    if chain_id in ['solana', 'aptos', 'sui']:
        return "⚠️ Check Manually (Non-EVM)"
    
    try:
        url = f"https://api.goplussecurity.io/api/v1/token_security/{chain_id}?contract_addresses={address}"
        res = requests.get(url, timeout=5).json()
        data = res.get('result', {}).get(address.lower(), {})
        
        if not data: return "❓ No Data"
        
        is_honeypot = data.get('is_honeypot')
        buy_tax = data.get('buy_tax', '0')
        sell_tax = data.get('sell_tax', '0')
        
        if is_honeypot == '1':
            return "❌ HONEYPOT!"
        
        tax_info = f"Buy: {float(buy_tax)*100:.1f}% | Sell: {float(sell_tax)*100:.1f}%"
        return f"✅ Safe | {tax_info}"
    except:
        return "⚠️ API Error"

def get_dex_data(chain_name):
    try:
        url = f"https://api.dexscreener.com/latest/dex/search?q={chain_name}"
        response = requests.get(url, timeout=10).json()
        pairs = response.get('pairs', [])
        
        extracted = []
        for p in pairs[:50]:
            quote = p.get('quoteToken', {}).get('symbol', '')
            if quote in ['USDT', 'USDC']:
                extracted.append({
                    'symbol': p['baseToken']['symbol'].upper(),
                    'address': p['baseToken']['address'],
                    'price': float(p['priceUsd']) if p.get('priceUsd') else 0,
                    'dex_id': p['dexId'],
                    'liquidity': p.get('liquidity', {}).get('usd', 0)
                })
        return extracted
    except:
        return []

def get_cex_prices(ex_id, symbols):
    try:
        ex = getattr(ccxt, ex_id)({'enableRateLimit': True})
        tickers = ex.fetch_tickers()
        data = {}
        for s in symbols:
            pair = f"{s}/USDT"
            if pair in tickers:
                t = tickers[pair]
                if t['bid'] and t['ask']:
                    data[s] = {'bid': t['bid'], 'ask': t['ask']}
        return ex_id, data
    except:
        return ex_id, {}

# --- ИНТЕРФЕЙС ---
st.title("🔗 CEX-DEX Arb Terminal v2.0")
st.write(f"Последний скан: {datetime.now().strftime('%H:%M:%S')}")

with st.sidebar:
    st.header("🌐 Сеть")
    chain_key = st.selectbox("Блокчейн:", list(SUPPORTED_CHAINS.keys()), 
                             format_func=lambda x: SUPPORTED_CHAINS[x]['name'])
    
    st.divider()
    min_spread = st.slider("Мин. профит (%)", 1.0, 15.0, 2.0)
    min_liq = st.number_input("Мин. ликвидность ($)", value=10000)
    
    st.divider()
    check_hp = st.checkbox("🔍 Проверять на HoneyPot", value=True)
    auto_refresh = st.checkbox("🔄 Авто-обновление (2 мин)")

# --- СКАНЕР ---
def start_scan():
    dex_pairs = get_dex_data(chain_key)
    dex_pairs = [p for p in dex_pairs if p['liquidity'] >= min_liq]
    
    if not dex_pairs:
        st.warning("Нет ликвидных пар.")
        return

    unique_symbols = list(set([p['symbol'] for p in dex_pairs]))

    with st.spinner('Синхронизация с Bybit, MEXC, LBank...'):
        with ThreadPoolExecutor(max_workers=3) as executor:
            cex_results = dict(list(executor.map(lambda x: get_cex_prices(x, unique_symbols), CEX_LIST)))

    results = []
    for d in dex_pairs:
        s = d['symbol']
        d_p = d['price']
        
        for cex_id, data in cex_results.items():
            if s in data:
                cex = data[s]
                
                # Покупаем на DEX -> Продаем на CEX
                spread_a = ((cex['bid'] - d_p) / d_p) * 100
                # Покупаем на CEX -> Продаем на DEX
                spread_b = ((d_p - cex['ask']) / cex['ask']) * 100
                
                final_spread = max(spread_a, spread_b)
                buy_from = f"DEX ({d['dex_id']})" if spread_a > spread_b else cex_id.upper()
                sell_to = cex_id.upper() if spread_a > spread_b else f"DEX ({d['dex_id']})"

                if min_spread < final_spread < 40:
                    security = "Skipped"
                    if check_hp:
                        security = check_honeypot(SUPPORTED_CHAINS[chain_key]['id'], d['address'])
                    
                    # Не выводим, если это точно HoneyPot
                    if "❌" in security: continue

                    results.append({
                        'Токен': s,
                        'ПРОФИТ': f"{final_spread:.2f}%",
                        'КУПИТЬ': buy_from,
                        'ПРОДАТЬ': sell_to,
                        'БЕЗОПАСНОСТЬ': security,
                        'DEX Цена': f"{d_p:.6f}",
                        'CEX Цена': f"{cex['bid'] if spread_a > spread_b else cex['ask']:.6f}",
                        'Контракт': d['address']
                    })

    if results:
        df = pd.DataFrame(results).sort_values('ПРОФИТ', ascending=False)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Связок не найдено.")

if auto_refresh:
    start_scan()
    time.sleep(120)
    st.rerun()
else:
    if st.button("🚀 ЗАПУСТИТЬ СКАНЕР", use_container_width=True):
        start_scan()
