import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px

# 1. 設定網頁標題與寬度 layout
st.set_page_config(page_title="台股短期資金輪動監控儀表板", layout="wide", page_icon="📈")

st.title("📊 台股短期資金輪動與族群動能監控")
st.caption("即時分析主要產業與權值標的之 3日/5日 動能與成交量異常變化")

# 2. 定義監控標的
SECTOR_MAP = {
    "^TWII": "台股加權大盤",
    "0050.TW": "市值權值股 (元大台灣50)",
    "0051.TW": "中小型股 (元大中型100)",
    "0052.TW": "富邦科技 (電子主軸)",
    "0053.TW": "元大電子 (半導體/電子)",
    "0055.TW": "元大金融 (金融族群)",
    "0056.TW": "高股息 (防禦型資金)",
    "006208.TW": "富邦台50",
}

@st.cache_data(ttl=300) # 快取數據 5 分鐘
def fetch_data():
    tickers = list(SECTOR_MAP.keys())
    # 改抓取最近 3 個月的日 K 資料，確保有足夠交易日
    data = yf.download(tickers, period="3m", interval="1d", progress=False)
    return data

# 3. 執行資料擷取與運算
try:
    data = fetch_data()
    
    # yfinance 回傳多重索引處理
    if isinstance(data.columns, pd.MultiIndex):
        close_prices = data["Close"].dropna(how="all")
        volumes = data["Volume"].dropna(how="all")
    else:
        close_prices = data["Close"].dropna()
        volumes = data["Volume"].dropna()

    # 檢查交易日數量是否充足
    if len(close_prices) < 6:
        st.error("歷史交易資料天數不足（少於 6 天），請稍後再試。")
    else:
        # 計算動能指標 (安全取值)
        ret_3d = (close_prices.iloc[-1] / close_prices.iloc[-4] - 1) * 100
        ret_5d = (close_prices.iloc[-1] / close_prices.iloc[-6] - 1) * 100
        vol_5d_avg = volumes.rolling(5).mean()
        vol_ratio = (volumes.iloc[-1] / vol_5d_avg.iloc[-1])
        
        market_3d = ret_3d["^TWII"]

        # 組合資料表
        results = []
        for ticker, name in SECTOR_MAP.items():
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
                "族群/標的": name,
                "3日漲跌(%)": round(float(r3), 2),
                "5日漲跌(%)": round(float(r5), 2),
                "量比(較5日均量)": round(float(vr), 2),
                "相對強弱": rs_status,
                "資金診斷": status
            })
            
        df = pd.DataFrame(results).sort_values(by="3日漲跌(%)", ascending=False)

        # 4. 網頁視覺化呈現
        top3 = df.head(3)
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("🔥 最強資金聚焦首選", top3.iloc[0]["族群/標的"], f"{top3.iloc[0]['3日漲跌(%)']}%")
        with col2:
            st.metric("🥈 資金流向第二名", top3.iloc[1]["族群/標的"], f"{top3.iloc[1]['3日漲跌(%)']}%")
        with col3:
            st.metric("📈 加權大盤 3日變動", "加權指數", f"{round(float(market_3d), 2)}%")

        st.markdown("---")

        # 動能矩陣散佈圖
        st.subheader("📌 資金輪動動能矩陣 (量價分佈)")
        fig = px.scatter(
            df, 
            x="量比(較5日均量)", 
            y="3日漲跌(%)", 
            color="資金診斷",
            text="族群/標的",
            size_max=30,
            title="右上角區域（大漲+爆量）代表目前資金熱錢核心"
        )
        fig.update_traces(textposition='top center')
        st.plotly_chart(fig, use_container_width=True)

        # 詳細數據資料表
        st.subheader("📋 族群數據排行明細")
        st.dataframe(df, use_container_width=True)

except Exception as e:
    st.error(f"數據載入失敗或美股盤後更新中，請稍後重試：{e}")
