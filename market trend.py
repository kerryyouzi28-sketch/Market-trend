import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import requests
from datetime import datetime
import pytz

# 1. 設定網頁標題與寬度 layout
st.set_page_config(page_title="台股動態熱錢與資金輪動儀表板", layout="wide", page_icon="📈")

st.title("🔥 台股當日動態熱錢與資金輪動監控儀表板")
st.caption("自動抓取台灣證交所 (TWSE) 當日成交量排行榜與熱門概念股，即時分析熱錢動能")

# 2. 自動爬取證交所 (TWSE) 當日成交量排行榜
@st.cache_data(ttl=600) # 快取 10 分鐘，避免頻繁請求證交所 API
def get_twse_top_volume_tickers():
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX20?response=json"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    ticker_dict = {"^TWII": "台股加權大盤"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        data = res.json()
        if "data" in data:
            # 取得前 40 大成交量個股
            for row in data["data"][:40]:
                code = row[1].strip() # 股票代碼
                name = row[2].strip() # 股票名稱
                # 排除 ETF (代碼長度>4 或 00開頭) 以確保抓到的是純個股
                if len(code) == 4 and not code.startswith("00"):
                    ticker_dict[f"{code}.TW"] = f"{name} ({code})"
    except Exception as e:
        st.warning(f"無法自動連結證交所熱門榜，改啟動核心產業備援清單：{e}")
        backup = {
            "2330.TW": "台積電", "2317.TW": "鴻海", "2454.TW": "聯發科", 
            "2382.TW": "廣達", "3231.TW": "緯創", "2603.TW": "長榮", 
            "1519.TW": "華城", "3017.TW": "奇鋐", "2359.TW": "所羅門"
        }
        ticker_dict.update(backup)
        
    return ticker_dict

ETF_MAP = {
    "^TWII": "台股加權大盤",
    "0050.TW": "元大台灣50",
    "0056.TW": "元大高股息",
    "00878.TW": "國泰永續高股息",
    "00919.TW": "群益台灣精選高息",
    "00929.TW": "復華台灣科技優息",
    "00940.TW": "元大台灣價值高息",
    "0052.TW": "富邦科技",
    "0055.TW": "元大金融",
    "0051.TW": "元大中型100",
}

# 3. 側邊欄控制項
st.sidebar.header("⚙️ 篩選與模式設定")

view_mode = st.sidebar.selectbox(
    "請選擇分析目標：",
    ["🔥 證交所當日爆量熱門股 (自動更新)", "📊 核心主題型/產業 ETF", "➕ 僅檢視自訂股票"]
)

# 手動輸入股票代碼（僅在選取「僅檢視自訂股票」時或需自行新增時提供輸入框）
custom_tickers_input = st.sidebar.text_input(
    "手動輸入自訂股票代碼 (多筆可用逗點分隔，例如：2357, 2454)：", 
    value="2357.TW"
)

# 根據選單模式嚴格分離標的，手動輸入標的不混入其他頁面
if "當日爆量熱門股" in view_mode:
    target_map = get_twse_top_volume_tickers()
elif "主題型" in view_mode:
    target_map = ETF_MAP.copy()
else:
    # 僅檢視自訂股票模式
    target_map = {"^TWII": "台股加權大盤"}
    if custom_tickers_input.strip():
        items = custom_tickers_input.replace("，", ",").split(",")
        for raw_item in items:
            code = raw_item.strip().upper()
            if code:
                if not code.endswith(".TW") and not code.startswith("^"):
                    code += ".TW"
                target_map[code] = f"自訂標的 ({code})"

# 4. 下載歷史數據並計算動能
@st.cache_data(ttl=300)
def fetch_data(tickers):
    data = yf.download(tickers, period="20d", interval="1d", progress=False)
    tw_tz = pytz.timezone('Asia/Taipei')
    fetch_time = datetime.now(tw_tz).strftime("%Y-%m-%d %H:%M:%S")
    return data, fetch_time

try:
    with st.spinner("正在自動掃描當日市場熱錢焦點與動能..."):
        data, fetch_time = fetch_data(list(target_map.keys()))
    
    if isinstance(data.columns, pd.MultiIndex):
        close_prices = data["Close"]
        volumes = data["Volume"]
    else:
        close_prices = data["Close"]
        volumes = data["Volume"]

    close_prices = close_prices.dropna(how="all").ffill()
    volumes = volumes.dropna(how="all").fillna(0)

    if len(close_prices) < 6:
        st.warning("目前市場數據連線較慢，請重新整理頁面。")
    else:
        latest_market_date = close_prices.index[-1].strftime("%Y-%m-%d")

        # 顯示數據時間標示
        st.info(f"🕒 **數據抓取時間**：`{fetch_time} (台灣時間)` ｜ 📅 **最新市場交易日**：`{latest_market_date}`")

        # 計算動能指標
        ret_3d = (close_prices.iloc[-1] / close_prices.iloc[-4] - 1) * 100
        ret_5d = (close_prices.iloc[-1] / close_prices.iloc[-6] - 1) * 100
        
        # 5日成交均量
        vol_5d_avg = volumes.tail(5).mean()
        vol_ratio = volumes.iloc[-1] / vol_5d_avg
        
        market_3d = ret_3d["^TWII"] if "^TWII" in ret_3d else 0.0

        # 組合數據表
        results = []
        for ticker, name in target_map.items():
            if ticker == "^TWII" or ticker not in close_prices.columns:
                continue
                
            r3 = ret_3d[ticker]
            r5 = ret_5d[ticker]
            vr = vol_ratio[ticker]
            
            if pd.isna(r3) or pd.isna(vr):
                continue

            rs_status = "強於大盤" if r3 > market_3d else "弱於大盤"
            
            if r3 > 1.5 and vr > 1.2:
                status = "🔥 資金急流（爆量突破）"
            elif r3 > 0 and vr > 1.0:
                status = "📈 資金持續流入"
            elif r3 < 0 and vr > 1.2:
                status = "⚠️ 資金大幅撤出（爆量下跌）"
            else:
                status = "💤 沉寂/觀望"
                
            results.append({
                "代號": ticker,
                "股票/標的名稱": name,
                "3日漲跌(%)": round(float(r3), 2),
                "5日漲跌(%)": round(float(r5), 2),
                "量比(較5日均量)": round(float(vr), 2),
                "相對強弱": rs_status,
                "資金診斷": status
            })
            
        df = pd.DataFrame(results).sort_values(by="3日漲跌(%)", ascending=False)

        # 5. 視覺化呈現
        if not df.empty:
            top3 = df.head(3)
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("🔥 當前熱錢最強首選", top3.iloc[0]["股票/標的名稱"], f"{top3.iloc[0]['3日漲跌(%)']}%")
            with col2:
                if len(top3) > 1:
                    st.metric("🥈 熱錢強勢第二名", top3.iloc[1]["股票/標的名稱"], f"{top3.iloc[1]['3日漲跌(%)']}%")
            with col3:
                st.metric("📈 加權大盤 3日變動", "加權指數", f"{round(float(market_3d), 2)}%")

            st.markdown("---")

            # 散佈圖
            st.subheader(f"📌 {view_mode} - 動態資金分布矩陣 (量價分佈)")
            fig = px.scatter(
                df, 
                x="量比(較5日均量)", 
                y="3日漲跌(%)", 
                color="資金診斷",
                text="股票/標的名稱",
                size_max=30,
                hover_data=["代號", "5日漲跌(%)"],
                title="右上角區域（大漲+爆量）代表當天熱錢極度集中之標的"
            )
            fig.update_traces(textposition='top center')
            st.plotly_chart(fig, use_container_width=True)

            # 詳細數據資料表
            st.subheader(f"📋 數據排行榜明細 (共 {len(df)} 支)")
            st.dataframe(df, use_container_width=True)
        else:
            st.info("沒有可顯示的標的，請於左側選單輸入自訂股票代號。")

except Exception as e:
    st.error(f"數據載入失敗，請稍後重試或重新整理：{e}")
