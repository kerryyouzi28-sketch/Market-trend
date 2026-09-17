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
    page_title="台股熱錢掃描與三維度選股診斷系統", 
    page_icon="📈", 
    layout="wide"
)

st.title("🔥 台股『當日熱錢掃描 x 三維度健檢風控』系統")
st.caption("結合證交所當日爆量熱錢、三維度評分（技術/籌碼/位階）與即時進出場風控點位計算")

# -----------------------------------------------------------------------------
# 核心演算法函數
# -----------------------------------------------------------------------------

def estimate_daily_volume(volume_so_far):
    """根據台灣時間 (UTC+8) 盤中進度 (09:00 - 13:30 共 270 分鐘) 推算預估成交量"""
    tw_tz = timezone(timedelta(hours=8))
    now_tw = datetime.now(tw_tz)

    market_open = now_tw.replace(hour=9, minute=0, second=0, microsecond=0)
    market_close = now_tw.replace(hour=13, minute=30, second=0, microsecond=0)

    if now_tw < market_open or now_tw >= market_close:
        return volume_so_far

    elapsed_minutes = (now_tw - market_open).total_seconds() / 60.0
    if elapsed_minutes < 5:
        return volume_so_far

    return int(volume_so_far * (270.0 / elapsed_minutes))

@st.cache_data(ttl=300)
def fetch_yahoo_detail(symbol):
    chart_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=60d&interval=1d"
    req_chart = urllib.request.Request(
        chart_url, headers={"User-Agent": "Mozilla/5.0"}
    )
    try:
        with urllib.request.urlopen(req_chart, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            result = data["chart"]["result"][0]
            meta = result["meta"]
            stock_name = meta.get("shortName") or meta.get("symbol") or symbol

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

def evaluate_stock_full(symbol, min_volume_actual=30, min_volume_est=30, ignore_filters=False):
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
    latest_price = closes[-1]
    vol_shares = int(volumes[-1] / 1000)
    est_vol_shares = estimate_daily_volume(vol_shares)

    if not ignore_filters:
        if latest_price < 5.0 or vol_shares < min_volume_actual or est_vol_shares < min_volume_est:
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
        tech_details.append("站穩 20 日月線")
    else:
        tech_details.append("跌破 20 日月線")

    if ma5 >= ma20 >= ma60:
        tech_score += 12
        tech_details.append("均線多頭排列")
    elif ma5 >= ma20:
        tech_score += 6
        tech_details.append("短中期均線偏多")

    upper_shadow = highs[-1] - max(latest_price, opens[-1])
    body_size = abs(latest_price - opens[-1])
    if upper_shadow <= (body_size * 0.8):
        tech_score += 8
        tech_details.append("無過長上影線")

    # 2. 籌碼量能 (35%)
    chip_score = 0
    recent_vols = [v / 1000 for v in volumes[-6:-1]]
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

    # 風控進出場點位推算
    low_10d, high_20d = min(lows[-10:]), max(highs[-20:])
    entry_low = round(min(ma20, min(lows[-5:])), 2)
    entry_high = round(latest_price if latest_price < ma5 else (latest_price + ma20) / 2.0, 2)
    stop_loss = round(min(low_10d, ma20 * 0.97), 2)
    target_price = round(max(high_20d * 1.03, entry_high * 1.10), 2)

    risk = max(0.1, entry_high - stop_loss)
    reward = target_price - entry_high
    rr_ratio = round(reward / risk, 2)

    return {
        "代號": code,
        "名稱": name,
        "現價": latest_price,
        "漲跌幅(%)": change_pct,
        "健檢總分": total_score,
        "量能倍數": vol_ratio,
        "建議卡位進場區": f"{entry_low:.2f} ~ {entry_high:.2f}",
        "第一目標價": target_price,
        "停損防守價": stop_loss,
        "風報比(R/R)": rr_ratio,
        "當日成交張數": vol_shares,
        "預估成交張數": est_vol_shares,
        "技術得分": tech_score,
        "籌碼得分": chip_score,
        "位階得分": fund_score,
        "技術明細": ", ".join(tech_details),
    }

@st.cache_data(ttl=600)
def get_twse_top_tickers():
    """自動從證交所抓取當日成交量 Top 40"""
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX20?response=json"
    headers = {"User-Agent": "Mozilla/5.0"}
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
        symbols = ["2330.TW", "2317.TW", "2454.TW", "2382.TW", "3231.TW", "2603.TW", "2408.TW"]
    return symbols

# -----------------------------------------------------------------------------
# 側邊欄與模式分流
# -----------------------------------------------------------------------------

with st.sidebar:
    st.header("🎯 操作選單")
    app_mode = st.radio(
        "選擇功能模式", 
        ("🔥 證交所當日熱錢綜合診斷", "🔍 號碼區間掃描", "🩺 單股精準診斷")
    )
    st.divider()

    if app_mode == "🔥 證交所當日熱錢綜合診斷":
        st.subheader("⚙️ 熱錢健檢門檻")
        min_score = st.slider("最低健檢總分門檻", 50, 100, 70)
        min_vol_actual = st.number_input("當日成交量下限(張)", value=1000, step=500)

    elif app_mode == "🔍 號碼區間掃描":
        st.subheader("⚙️ 區間篩選門檻")
        min_score, max_score = st.slider("健檢分數區間", 50, 100, (75, 100))
        col_vol1, col_vol2 = st.columns(2)
        with col_vol1:
            min_vol_actual = st.number_input("當日成交量(張)", value=500, step=100)
        with col_vol2:
            min_vol_est = st.number_input("預估成交量(張)", value=500, step=100)

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
        st.info("💡 單股診斷不受成交量與分數門檻限制")
        single_code = st.text_input("輸入股票代號", value="2408").strip()

# -----------------------------------------------------------------------------
# 模式 1：證交所當日熱錢綜合診斷 (全新強大整合模式)
# -----------------------------------------------------------------------------
if app_mode == "🔥 證交所當日熱錢綜合診斷":
    st.subheader("🔥 證交所當日爆量熱錢 — 三維度綜合診斷報告")
    
    tw_tz = pytz.timezone('Asia/Taipei')
    fetch_time = datetime.now(tw_tz).strftime("%Y-%m-%d %H:%M:%S")
    st.info(f"🕒 **分析時間**：`{fetch_time} (台灣時間)` ｜ 正在自動掃描證交所成交量 Top 40 熱門股...")

    with st.spinner("正在計算熱錢動能與三維度健康評分..."):
        top_symbols = get_twse_top_tickers()
        results = []
        for symbol in top_symbols:
            res = evaluate_stock_full(symbol, min_volume_actual=min_vol_actual, ignore_filters=False)
            if res and res["健檢總分"] >= min_score:
                results.append(res)

    if results:
        df = pd.DataFrame(results).sort_values(by="健檢總分", ascending=False).reset_index(drop=True)
        
        # 散佈圖（四象限：X軸=量能倍數，Y軸=健檢總分）
        st.subheader("📌 熱錢動能與健檢分數矩陣 (右上角為最強優質股)")
        fig = px.scatter(
            df,
            x="量能倍數",
            y="健檢總分",
            color="漲跌幅(%)",
            text="名稱",
            color_continuous_scale="Reds",
            hover_data=["代號", "現價", "風報比(R/R)"],
            size_max=18
        )
        fig.add_vline(x=1.0, line_dash="dash", line_color="gray", opacity=0.7)
        fig.add_hline(y=75, line_dash="dash", line_color="gray", opacity=0.7)
        fig.update_traces(textposition='top center', marker=dict(size=12))
        fig.update_layout(height=500, xaxis_title="量能倍數 ( > 1.0 代表爆量 )", yaxis_title="三維度健檢總分 ( >= 75 代表優質 )")
        st.plotly_chart(fig, use_container_width=True)

        # 數據資料表
        st.subheader(f"📋 今日精選優質熱錢強勢股 (共 {len(df)} 支，按總分排序)")
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("💡 點擊下方展開個別風控與卡位點位細節：")
        for item in results:
            with st.expander(f"🌟 【{item['代號']} {item['名稱']}】 健檢總分：{item['健檢總分']} 分 | 漲跌幅：{item['漲跌幅(%)']}%"):
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("現價", f"{item['現價']} 元", f"{item['漲跌幅(%)']}%")
                col2.metric("成交 / 預估量", f"{item['當日成交張數']} 張", f"預估 {item['預估成交張數']} 張")
                col3.metric("建議卡位區", item["建議卡位進場區"])
                col4.metric("目標 / 停損", f"{item['第一目標價']} / {item['停損防守價']}")

# -----------------------------------------------------------------------------
# 模式 2：號碼區間掃描
# -----------------------------------------------------------------------------
elif app_mode == "🔍 號碼區間掃描":
    if st.button("🚀 開始區間掃描", type="primary"):
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

        st.info(f"🔍 正在連線分析 {len(symbols)} 檔標的...")
        progress_bar = st.progress(0)

        results = []
        for idx, symbol in enumerate(symbols):
            progress_bar.progress((idx + 1) / len(symbols))
            res = evaluate_stock_full(symbol, min_volume_actual=min_vol_actual, min_volume_est=min_vol_est)
            if res and min_score[0] <= res["健檢總分"] <= min_score[1]:
                results.append(res)

        progress_bar.empty()

        if results:
            df = pd.DataFrame(results).sort_values(by="健檢總分", ascending=False).reset_index(drop=True)
            st.success(f"🎉 掃描完成！共有 {len(df)} 檔符合門檻標的：")
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.warning("💡 當前條件下無符合標的，可嘗試調低成交量或分數門檻。")

# -----------------------------------------------------------------------------
# 模式 3：單股精準診斷
# -----------------------------------------------------------------------------
elif app_mode == "🩺 單股精準診斷":
    if single_code:
        res = evaluate_stock_full(f"{single_code}.TW", ignore_filters=True)
        if not res:
            res = evaluate_stock_full(f"{single_code}.TWO", ignore_filters=True)

        if res:
            st.subheader(f"🩺 【{res['代號']} {res['名稱']}】 診斷與風控點位報告")

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("最新價", f"{res['現價']} 元", f"{res['漲跌幅(%)']}%")
            col2.metric("健檢總分", f"{res['健檢總分']} / 100 分")
            col3.metric("當日 / 預估量", f"{res['當日成交張數']} 張", f"預估 {res['預估成交張數']} 張")
            col4.metric("風險報酬比", res["風報比(R/R)"])

            st.divider()
            st.markdown("### 🎯 建議進出場關鍵點位")
            p_col1, p_col2, p_col3 = st.columns(3)
            p_col1.success(f"🟢 **建議卡位進場區**\n\n### {res['建議卡位進場區']} 元")
            p_col2.info(f"🚀 **第一目標看價位**\n\n### {res['第一目標價']} 元")
            p_col3.error(f"🛑 **嚴格防守停損價**\n\n### {res['停損防守價']} 元")

            st.divider()
            st.markdown("### 📊 三維度得分拆解")
            s_col1, s_col2, s_col3 = st.columns(3)
            s_col1.progress(res["技術得分"] / 35, text=f"📈 技術面：{res['技術得分']} / 35 分 ({res['技術明細']})")
            s_col2.progress(res["籌碼得分"] / 35, text=f"📊 籌碼面：{res['籌碼得分']} / 35 分")
            s_col3.progress(res["位階得分"] / 30, text=f"🛡️ 位階面：{res['位階得分']} / 30 分")
        else:
            st.error(f"❌ 查無代號 `{single_code}` 的資料，請確認輸入是否正確。")
