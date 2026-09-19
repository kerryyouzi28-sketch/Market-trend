import json
import urllib.request
import requests
import pandas as pd
import streamlit as st
import plotly.express as px
from datetime import datetime, timezone, timedelta
import pytz

# 1. 網頁設定
st.set_page_config(
    page_title="台美股動態熱錢與三維度選股診斷系統", 
    page_icon="📈", 
    layout="wide"
)

# 注入 CSS 優化行動裝置體驗
st.markdown("""
    <style>
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    </style>
""", unsafe_allow_html=True)

st.title("🌐 台美股『當日熱錢掃描 x 三維度健檢風控』系統")
st.caption("支援台灣股市與美國股市，結合熱錢動能、三維度評分（技術/籌碼/位階）與風控進出場點位計算")

# 美股核心熱門標的池 (備援/預設)
US_TOP_TICKERS = [
    "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "AMD", "PLTR", 
    "AVGO", "NFLX", "INTC", "SMCI", "COIN", "MSTR", "BAC", "JPM", "DIS",
    "QQQ", "SPY", "SOXX", "IWM"
]

# -----------------------------------------------------------------------------
# 核心演算法函數
# -----------------------------------------------------------------------------

def estimate_daily_volume(volume_so_far, market_type="TW"):
    """盤中預估成交量計算 (支援台股與美股交易時間)"""
    if market_type == "TW":
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        market_open = now.replace(hour=9, minute=0, second=0, microsecond=0)
        market_close = now.replace(hour=13, minute=30, second=0, microsecond=0)
        total_minutes = 270.0
    else:
        tz = timezone(timedelta(hours=-4)) # 美東時間
        now = datetime.now(tz)
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        total_minutes = 390.0

    if now < market_open or now >= market_close:
        return volume_so_far

    elapsed_minutes = (now - market_open).total_seconds() / 60.0
    if elapsed_minutes < 5:
        return volume_so_far

    return int(volume_so_far * (total_minutes / elapsed_minutes))

@st.cache_data(ttl=300)
def fetch_yahoo_detail(symbol):
    chart_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=60d&interval=1d"
    req_chart = urllib.request.Request(
        chart_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    )
    try:
        with urllib.request.urlopen(req_chart, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            result = data["chart"]["result"][0]
            meta = result["meta"]
            stock_name = meta.get("shortName") or meta.get("longName") or meta.get("symbol") or symbol

            quote = result["indicators"]["quote"][0]
            closes = [c for c in quote["close"] if c is not None]
            opens = [o for o in quote["open"] if o is not None]
            highs = [h for h in quote["high"] if h is not None]
            lows = [l for l in quote["low"] if l is not None]
            volumes = [v for v in quote["volume"] if v is not None]

            return {
                "name": stock_name,
                "close": closes,
                "open": opens,
                "high": highs,
                "low": lows,
                "volume": volumes,
                "fiftyTwoWeekHigh": meta.get("fiftyTwoWeekHigh", 0),
                "fiftyTwoWeekLow": meta.get("fiftyTwoWeekLow", 0),
            }
    except Exception:
        return None

def evaluate_stock_full(
    symbol, 
    market_type="TW",
    min_score_filter=0, 
    min_vol_actual=0, 
    min_vol_est=0,
    min_tech=0,
    min_chip=0,
    min_fund=0
):
    data = fetch_yahoo_detail(symbol)
    if not data or len(data["close"]) < 20:
        return None

    closes, opens, highs, lows, volumes = (
        data["close"],
        data["open"],
        data["high"],
        data["low"],
        data["volume"],
    )
    latest_price = round(closes[-1], 2)
    
    # 台股單位為張 (1,000股)，美股直接為股
    vol_shares = int(volumes[-1] / 1000) if market_type == "TW" else int(volumes[-1])
    est_vol_shares = estimate_daily_volume(vol_shares, market_type)

    if vol_shares < min_vol_actual or est_vol_shares < min_vol_est:
        return None

    code = symbol.split(".")[0]
    name = data["name"]
    prev_close = closes[-2]
    if prev_close == 0:
        return None

    change_pct = round(((latest_price - prev_close) / prev_close) * 100, 2)

    # 1. 技術面 (35%)
    tech_score = 0
    tech_details = []
    ma5 = sum(closes[-5:]) / 5.0
    ma20 = sum(closes[-20:]) / 20.0
    ma60 = sum(closes[-60:]) / 60.0 if len(closes) >= 60 else sum(closes) / len(closes)

    if latest_price >= ma20:
        tech_score += 15
        tech_details.append("站穩20日線")
    else:
        tech_details.append("跌破20日線")

    if ma5 >= ma20 >= ma60:
        tech_score += 12
        tech_details.append("均線多頭")
    elif ma5 >= ma20:
        tech_score += 6
        tech_details.append("短中期偏多")

    upper_shadow = highs[-1] - max(latest_price, opens[-1])
    body_size = abs(latest_price - opens[-1])
    if upper_shadow <= (body_size * 0.8):
        tech_score += 8
        tech_details.append("無長上影線")

    # 2. 籌碼量能 (35%)
    chip_score = 0
    recent_vols = [v / 1000 if market_type == "TW" else v for v in volumes[-6:-1]]
    vol_5ma = sum(recent_vols) / len(recent_vols) if len(recent_vols) > 0 else 0
    vol_ratio = round(vol_shares / vol_5ma, 2) if vol_5ma > 0 else 1.0

    if 0.3 <= vol_ratio <= 0.7:
        chip_score += 35
    elif 0.7 < vol_ratio <= 1.2:
        chip_score += 25
    elif 1.2 < vol_ratio <= 1.8 and change_pct > 0:
        chip_score += 30
    else:
        chip_score += 10

    # 3. 位階安全度 (30%)
    fund_score = 0
    h52, l52 = data["fiftyTwoWeekHigh"], data["fiftyTwoWeekLow"]
    if h52 > l52 > 0:
        position = ((latest_price - l52) / (h52 - l52)) * 100
        if position <= 45:
            fund_score += 30
        elif position <= 75:
            fund_score += 20
        else:
            fund_score += 10

    total_score = tech_score + chip_score + fund_score

    if (
        tech_score < min_tech or 
        chip_score < min_chip or 
        fund_score < min_fund or 
        total_score < min_score_filter
    ):
        return None

    # 風控進出場點位推算
    low_10d, high_20d = min(lows[-10:]), max(highs[-20:])
    entry_low = round(min(ma20, min(lows[-5:])), 2)
    entry_high = round(latest_price if latest_price < ma5 else (latest_price + ma20) / 2.0, 2)
    stop_loss = round(min(low_10d, ma20 * 0.97), 2)
    target_price = round(max(high_20d * 1.03, entry_high * 1.10), 2)

    risk = max(0.1, entry_high - stop_loss)
    reward = target_price - entry_high
    rr_ratio = round(reward / risk, 2)

    unit_price = "元" if market_type == "TW" else "美元"
    unit_vol = "張" if market_type == "TW" else "股"

    return {
        "代號": code if market_type == "TW" else symbol.upper(),
        "名稱": name,
        f"現價({unit_price})": latest_price,
        "漲跌幅(%)": change_pct,
        "健檢總分": total_score,
        "量能倍數": vol_ratio,
        "建議卡位進場區": f"{entry_low:.2f} ~ {entry_high:.2f} {unit_price}",
        "第一目標價": f"{target_price:.2f} {unit_price}",
        "停損防守價": f"{stop_loss:.2f} {unit_price}",
        "風報比(R/R)": rr_ratio,
        f"當日成交量({unit_vol})": f"{vol_shares:,}",
        f"預估成交量({unit_vol})": f"{est_vol_shares:,}",
        "技術得分": tech_score,
        "籌碼得分": chip_score,
        "位階得分": fund_score,
        "技術明細": ", ".join(tech_details),
    }

@st.cache_data(ttl=600)
def get_twse_top_tickers():
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX20?response=json"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    symbols = []
    try:
        res = requests.get(url, headers=headers, timeout=10)
        data = res.json()
        if "data" in data:
            for row in data["data"]:
                code = str(row[1]).strip()
                if len(code) == 4 and code.isdigit() and not code.startswith("00"):
                    symbols.append(f"{code}.TW")
                if len(symbols) >= 40:
                    break
    except Exception:
        pass
    if not symbols:
        symbols = ["2330.TW", "2317.TW", "2454.TW", "2382.TW", "3231.TW", "2603.TW", "2408.TW", "1303.TW"]
    return symbols

# -----------------------------------------------------------------------------
# 側邊欄與市場模式分流
# -----------------------------------------------------------------------------

with st.sidebar:
    st.header("🌐 市場選擇")
    target_market = st.radio("請選擇目標市場：", ("🇹🇼 台灣股市 (TWSE)", "🇺🇸 美國股市 (US)"))
    market_code = "TW" if "台灣" in target_market else "US"

    st.divider()
    st.header("🎯 功能選單")
    st.caption("💡 選取完畢請點擊左上方 「✕」 關閉選單，以獲得最佳觀看體驗")
    
    app_mode = st.radio(
        "選擇功能模式", 
        ("🔥 當日熱錢焦點綜合診斷", "🔍 號碼區間/清單掃描", "🩺 單股精準診斷")
    )
    st.divider()

    if app_mode == "🔥 當日熱錢焦點綜合診斷":
        st.subheader("⚙️ 熱錢健檢門檻")
        min_score = st.slider("最低健檢總分門檻", 50, 100, 60)

    elif app_mode == "🔍 號碼區間/清單掃描":
        st.subheader("⚙️ 三維度得分門檻")
        min_tech = st.slider("📈 技術面最低分 (滿分35)", 0, 35, 15)
        min_chip = st.slider("📊 籌碼面最低分 (滿分35)", 0, 35, 20)
        min_fund = st.slider("🛡️ 位階面最低分 (滿分30)", 0, 30, 10)
        calculated_min_total = min_tech + min_chip + min_fund
        st.caption(f"💡 最低門檻總分：**{calculated_min_total} 分**")

        st.divider()
        st.subheader("⚙️ 量能與標的範圍")
        col_vol1, col_vol2 = st.columns(2)
        with col_vol1:
            default_vol = 500 if market_code == "TW" else 100000
            min_vol_actual = st.number_input("當日成交量下限", min_value=0, value=default_vol, step=100)
        
        with col_vol2:
            min_vol_est_default = max(default_vol * 2, min_vol_actual)
            min_vol_est = st.number_input("預估成交量下限", min_value=min_vol_actual, value=min_vol_est_default, step=100)

        st.divider()
        if market_code == "TW":
            scan_mode = st.radio(
                "號碼區間選擇",
                (
                    "2300-2399 (晶圓/代工/組裝)",
                    "2400-2499 (IC設計/記憶體)",
                    "3000-3399 (散熱/PCB/零組件)",
                    "6100-6699 (櫃買設備/IP股)",
                    "自訂號碼區間",
                ),
            )
            if scan_mode == "自訂號碼區間":
                start_code = st.number_input("起始號碼", value=2300, step=10)
                end_code = st.number_input("結束號碼", value=2350, step=10)
        else:
            custom_us_list = st.text_area(
                "輸入美股代號清單 (多筆用逗點分隔)：",
                value="NVDA, TSLA, AAPL, AMD, PLTR, MSFT, AMZN, GOOGL, META, AVGO, COIN, MSTR, QQQ, SPY",
                height=100
            )

    else:
        default_stock = "2408" if market_code == "TW" else "NVDA"
        single_code = st.text_input(f"輸入{target_market}代號", value=default_stock).strip()

# -----------------------------------------------------------------------------
# 模式 1：當日熱錢焦點綜合診斷
# -----------------------------------------------------------------------------
if app_mode == "🔥 當日熱錢焦點綜合診斷":
    st.subheader(f"{target_market} — 當日爆量熱錢三維度綜合診斷報告")
    
    tw_tz = pytz.timezone('Asia/Taipei')
    fetch_time = datetime.now(tw_tz).strftime("%Y-%m-%d %H:%M:%S")
    st.info(f"🕒 **分析時間**：`{fetch_time} (台灣時間)` ｜ 正在自動掃描市場熱門爆量焦點...")

    with st.spinner("正在連線計算全市場熱錢健檢分數..."):
        top_symbols = get_twse_top_tickers() if market_code == "TW" else US_TOP_TICKERS
        results = []
        for symbol in top_symbols:
            res = evaluate_stock_full(symbol, market_type=market_code, min_score_filter=min_score)
            if res:
                results.append(res)

    if results:
        df = pd.DataFrame(results).sort_values(by="健檢總分", ascending=False).reset_index(drop=True)
        
        st.subheader("📌 熱錢動能與健檢分數矩陣 (右上角為最強優質股)")
        fig = px.scatter(
            df,
            x="量能倍數",
            y="健檢總分",
            color="漲跌幅(%)",
            text="代號",
            color_continuous_scale="Reds",
            hover_data=["名稱", "風報比(R/R)"],
            size_max=18
        )
        fig.add_vline(x=1.0, line_dash="dash", line_color="gray", opacity=0.7)
        fig.add_hline(y=70, line_dash="dash", line_color="gray", opacity=0.7)
        fig.update_traces(textposition='top center', marker=dict(size=12))
        fig.update_layout(height=500, xaxis_title="量能倍數 ( > 1.0 代表爆量 )", yaxis_title="三維度健檢總分")
        st.plotly_chart(fig, use_container_width=True)

        st.subheader(f"📋 精選熱錢強勢股 (共 {len(df)} 支，按總分排序)")
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("💡 點擊下方展開個別風控與卡位點位細節：")
        price_col = "現價(元)" if market_code == "TW" else "現價(美元)"
        vol_col = "當日成交量(張)" if market_code == "TW" else "當日成交量(股)"
        est_vol_col = "預估成交量(張)" if market_code == "TW" else "預估成交量(股)"

        for item in results:
            with st.expander(f"🌟 【{item['代號']} - {item['名稱']}】 健檢總分：{item['健檢總分']} 分 | 漲跌幅：{item['漲跌幅(%)']}%"):
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("現價", f"{item[price_col]}", f"{item['漲跌幅(%)']}%")
                col2.metric("成交 / 預估量", f"{item[vol_col]}", f"預估 {item[est_vol_col]}")
                col3.metric("建議卡位區", item["建議卡位進場區"])
                col4.metric("目標 / 停損", f"{item['第一目標價']} / {item['停損防守價']}")
    else:
        st.warning("目前設定之分數門檻過高，無符合標的，請嘗試調低側邊欄的「最低健檢總分門檻」。")

# -----------------------------------------------------------------------------
# 模式 2：號碼區間/清單掃描
# -----------------------------------------------------------------------------
elif app_mode == "🔍 號碼區間/清單掃描":
    if st.button("🚀 開始批次掃描", type="primary"):
        if market_code == "TW":
            if "2300" in scan_mode:
                symbols = [f"{c}.TW" for c in range(2301, 2400)]
            elif "2400" in scan_mode:
                symbols = [f"{c}.TW" for c in range(2401, 2500)]
            elif "3000" in scan_mode:
                symbols = [f"{c}.TW" for c in range(3001, 3100)] + [f"{c}.TWO" for c in range(3201, 3400)]
            elif "6100" in scan_mode:
                symbols = [f"{c}.TWO" for c in range(6101, 6700)]
            else:
                symbols = [f"{c}.TW" for c in range(start_code, end_code + 1)]
        else:
            clean_input = custom_us_list.replace("\n", ",").replace("，", ",")
            symbols = [s.strip().upper() for s in clean_input.split(",") if s.strip()]

        st.info(f"🔍 正在連線分析 {len(symbols)} 檔標的...")
        progress_bar = st.progress(0)

        results = []
        for idx, symbol in enumerate(symbols):
            progress_bar.progress((idx + 1) / len(symbols))
            res = evaluate_stock_full(
                symbol, 
                market_type=market_code,
                min_vol_actual=min_vol_actual, 
                min_vol_est=min_vol_est,
                min_tech=min_tech,
                min_chip=min_chip,
                min_fund=min_fund
            )
            if res:
                results.append(res)

        progress_bar.empty()

        if results:
            df = pd.DataFrame(results).sort_values(by="健檢總分", ascending=False).reset_index(drop=True)
            st.success(f"🎉 掃描完成！共有 {len(df)} 檔符合門檻標的：")
            st.dataframe(df, use_container_width=True, hide_index=True)

            price_col = "現價(元)" if market_code == "TW" else "現價(美元)"
            vol_col = "當日成交量(張)" if market_code == "TW" else "當日成交量(股)"
            est_vol_col = "預估成交量(張)" if market_code == "TW" else "預估成交量(股)"

            for item in results:
                with st.expander(f"🌟 【{item['代號']} - {item['名稱']}】 健檢總分：{item['健檢總分']} 分"):
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("最新價", f"{item[price_col]}", f"{item['漲跌幅(%)']}%")
                    col2.metric("成交量", f"{item[vol_col]}", f"預估 {item[est_vol_col]}")
                    col3.metric("建議進場區", item["建議卡位進場區"])
                    col4.metric("目標 / 停損", f"{item['第一目標價']} / {item['停損防守價']}")
        else:
            st.warning("💡 當前條件下無符合標的，可嘗試調低分數或成交量門檻。")

# -----------------------------------------------------------------------------
# 模組 3：單股精準診斷
# -----------------------------------------------------------------------------
elif app_mode == "🩺 單股精準診斷":
    if single_code:
        search_symbol = single_code if market_code == "US" else f"{single_code}.TW"
        res = evaluate_stock_full(search_symbol, market_type=market_code)
        
        if not res and market_code == "TW":
            res = evaluate_stock_full(f"{single_code}.TWO", market_type=market_code)

        if res:
            st.subheader(f"🩺 【{res['代號']} - {res['名稱']}】 診斷與風控點位報告")

            price_col = "現價(元)" if market_code == "TW" else "現價(美元)"
            vol_col = "當日成交量(張)" if market_code == "TW" else "當日成交量(股)"
            est_vol_col = "預估成交量(張)" if market_code == "TW" else "預估成交量(股)"

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("最新價", f"{res[price_col]}", f"{res['漲跌幅(%)']}%")
            col2.metric("健檢總分", f"{res['健檢總分']} / 100 分")
            col3.metric("當日 / 預估量", f"{res[vol_col]}", f"預估 {res[est_vol_col]}")
            col4.metric("風險報酬比", res["風報比(R/R)"])

            st.divider()
            st.markdown("### 🎯 建議進出場關鍵點位")
            p_col1, p_col2, p_col3 = st.columns(3)
            p_col1.success(f"🟢 **建議卡位進場區**\n\n### {res['建議卡位進場區']}")
            p_col2.info(f"🚀 **第一目標看價位**\n\n### {res['第一目標價']}")
            p_col3.error(f"🛑 **嚴格防守停損價**\n\n### {res['停損防守價']}")

            st.divider()
            st.markdown("### 📊 三維度得分拆解")
            s_col1, s_col2, s_col3 = st.columns(3)
            s_col1.progress(res["技術得分"] / 35, text=f"📈 技術面：{res['技術得分']} / 35 分 ({res['技術明細']})")
            s_col2.progress(res["籌碼得分"] / 35, text=f"📊 籌碼面：{res['籌碼得分']} / 35 分")
            s_col3.progress(res["位階得分"] / 30, text=f"🛡️ 位階面：{res['位階得分']} / 30 分")
        else:
            st.error(f"❌ 查無`{target_market}`代號 `{single_code}` 的資料，請確認輸入是否正確。")
