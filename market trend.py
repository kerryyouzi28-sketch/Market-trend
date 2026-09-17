import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px

# 1. 設定網頁標題與寬度 layout
st.set_page_config(page_title="台股資金輪動監控儀表板", layout="wide", page_icon="📈")

st.title("📊 台股短期資金輪動與族群動能監控")
st.caption("即時分析台股主要產業、個股與 ETF 之 3日/5日 動能與成交量異常變化")

# 2. 定義監控標的群組 (分成：個股、ETF)
STOCKS_MAP = {
    "2330.TW": "台積電 (晶圓代工)",
    "2454.TW": "聯發科 (IC設計)",
    "2317.TW": "鴻海 (AI伺服器/代工)",
    "2382.TW": "廣達 (AI伺服器/代工)",
    "3231.TW": "緯創 (AI代工)",
    "2308.TW": "台達電 (電源/綠能/散熱)",
    "1519.TW": "華城 (重電/電網)",
    "1503.TW": "士電 (重電/電力設備)",
    "2603.TW": "長榮 (貨櫃航運)",
    "2609.TW": "陽明 (貨櫃航運)",
    "2881.TW": "富邦金 (大型金控)",
    "2882.TW": "國泰金 (大型金控)",
    "2379.TW": "瑞昱 (網通IC)",
    "3661.TW": "世芯-KY (IP矽智財)",
    "2408.TW": "南亞科 (記憶體/DRAM)",
    "1795.TW": "美時 (生技製藥)",
    "2002.TW": "中鋼 (原物料/鋼鐵)",
}

ETF_MAP = {
    "0050.TW": "元大台灣50 (市值權值)",
    "0051.TW": "元大中型100 (中小型股)",
    "0052.TW": "富邦科技 (電子主軸)",
    "0053.TW": "元大電子 (半導體/電子)",
    "0055.TW": "元大金融 (金融族群)",
    "0056.TW": "元大高股息 (防禦型資金)",
    "006208.TW": "富邦台50 (市值權值)",
    "00878.TW": "國泰永續高股息 (高股息)",
    "00919.TW": "群益台灣精選高息 (高股息)",
    "00929.TW": "復華台灣科技優息 (科技高股息)",
}

# 3. 側邊欄切換選單
st.sidebar.header("⚙️ 檢視設定")
view_mode = st.sidebar.selectbox(
    "請選擇分析目標種類：",
    ["產業龍頭個股", "主題型/產業 ETF", "全部標的綜合比較"]
)

# 根據選單決定要下載的標的清單
if view_mode == "產業龍頭個股":
    target_map = {**{"^TWII": "台股加權大盤"}, **STOCKS_MAP}
elif view_mode == "主題型/產業 ETF":
    target_map = {**{"^TWII": "台股加權大盤"}, **ETF_MAP}
else:
    target_map = {**{"^TWII": "台股加權大盤"}, **STOCKS_MAP, **ETF_MAP}

@st.cache_data(ttl=300) # 快取 5 分鐘
def fetch_data(tickers):
    data = yf.download(tickers, period="20d", interval="1d", progress=False)
    return data

# 4. 執行資料擷取與運算
try:
    data = fetch_data(list(target_map.keys()))
    
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
        # 計算動能指標
        ret_3d = (close_prices.iloc[-1] / close_prices.iloc[-4] - 1) * 100
        ret_5d = (close_prices.iloc[-1] / close_prices.iloc[-6] - 1) * 100
        
        # 5日成交均量
        vol_5d_avg = volumes.tail(5).mean()
        # 最新一日成交量相對於 5 日均量的倍數
        vol_ratio = volumes.iloc[-1] / vol_5d_avg
        
        market_3d = ret_3d["^TWII"]

        # 組合資料表
        results = []
        for ticker, name in target_map.items():
            if ticker == "^TWII":
                continue
                
            r3 = ret_3d[ticker]
            r5 = ret_5d[ticker]
            vr = vol_ratio[ticker]
            
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
                "標的名稱": name,
                "3日漲跌(%)": round(float(r3), 2),
                "5日漲跌(%)": round(float(r5), 2),
                "量比(較5日均量)": round(float(vr), 2),
                "相對強弱": rs_status,
                "資金診斷": status
            })
            
        df = pd.DataFrame(results).sort_values(by="3日漲跌(%)", ascending=False)

        # 5. 網頁視覺化呈現
        top3 = df.head(3)
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("🔥 最強資金聚焦首選", top3.iloc[0]["標的名稱"], f"{top3.iloc[0]['3日漲跌(%)']}%")
        with col2:
            st.metric("🥈 資金流向第二名", top3.iloc[1]["標的名稱"], f"{top3.iloc[1]['3日漲跌(%)']}%")
        with col3:
            st.metric("📈 加權大盤 3日變動", "加權指數", f"{round(float(market_3d), 2)}%")

        st.markdown("---")

        # 動能矩陣散佈圖
        st.subheader(f"📌 {view_mode} - 資金動能矩陣 (量價分佈)")
        fig = px.scatter(
            df, 
            x="量比(較5日均量)", 
            y="3日漲跌(%)", 
            color="資金診斷",
            text="標的名稱",
            size_max=30,
            title="右上角區域（大漲+爆量）代表目前資金熱錢核心"
        )
        fig.update_traces(textposition='top center')
        st.plotly_chart(fig, use_container_width=True)

        # 詳細數據資料表
        st.subheader(f"📋 {view_mode} - 數據排行明細")
        st.dataframe(df, use_container_width=True)

except Exception as e:
    st.error(f"數據載入失敗，請稍後重試或重新整理：{e}")
