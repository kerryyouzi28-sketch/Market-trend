import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go
import requests
from datetime import datetime
import pytz

# 1. 設定網頁標題與寬度 layout
st.set_page_config(page_title="台股動態熱錢與資金輪動儀表板", layout="wide", page_icon="📈")

st.title("🔥 台股當日動態熱錢與資金輪動監控儀表板")
st.caption("自動抓取台灣證交所 (TWSE) 當日成交量排行榜，即時分析個股與 ETF 之熱錢動能")

# 2. 自動爬取證交所 (TWSE) 當日成交量排行榜 (區分個股與 ETF)
@st.cache_data(ttl=600)
def get_twse_top_tickers():
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX20?response=json"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    stocks_dict = {"^TWII": "台股加權大盤"}
    etf_dict = {"^TWII": "台股加權大盤"}
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        data = res.json()
        if "data" in data:
            for row in data["data"]:
                code = str(row[1]).strip()
                name = str(row[2]).strip()
                
                if len(code) == 4 and code.isdigit() and not code.startswith("00"):
                    if len(stocks_dict) < 40:
                        stocks_dict[f"{code}.TW"] = f"{name} ({code})"
                elif code.startswith("00"):
                    if len(etf_dict) < 30:
                        etf_dict[f"{code}.TW"] = f"{name} ({code})"
    except Exception as e:
        st.warning(f"無法自動連結證交所熱門榜，啟動備援熱門清單：{e}")
        backup_stocks = {
            "2330.TW": "台積電", "2317.TW": "鴻海", "2454.TW": "聯發科", 
            "2382.TW": "廣達", "3231.TW": "緯創", "2603.TW": "長榮"
        }
        backup_etf = {
            "0050.TW": "元大台灣50", "0056.TW": "元大高股息", "00878.TW": "國泰永續高股息",
            "00919.TW": "群益台灣精選高息", "00929.TW": "復華台灣科技優息"
        }
        stocks_dict.update(backup_stocks)
        etf_dict.update(backup_etf)
        
    return stocks_dict, etf_dict

@st.cache_data(ttl=86400)
def get_stock_name(ticker_code):
    try:
        clean_code = ticker_code.replace(".TW", "").replace(".TWO", "")
        url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX20?response=json"
        res = requests.get(url, timeout=3).json()
        if "data" in res:
            for row in res["data"]:
                if str(row[1]).strip() == clean_code:
                    return f"{row[2].strip()} ({clean_code})"
    except:
        pass
    
    try:
        t = yf.Ticker(ticker_code)
        info = t.info
        name = info.get("shortName", clean_code)
        return f"{name} ({clean_code})"
    except:
        return f"股票代碼 ({clean_code})"

# 3. 側邊欄控制項
st.sidebar.header("⚙️ 篩選與模式設定")

view_mode = st.sidebar.selectbox(
    "請選擇分析目標：",
    ["🔥 證交所當日爆量熱門個股 (自動更新)", "📊 證交所當日爆量熱門 ETF (自動更新)", "➕ 僅檢視自訂股票"]
)

stocks_map, etf_map = get_twse_top_tickers()

if "爆量熱門個股" in view_mode:
    target_map = stocks_map
elif "爆量熱門 ETF" in view_mode:
    target_map = etf_map
else:
    custom_tickers_input = st.sidebar.text_input(
        "手動輸入自訂股票代碼 (多筆可用逗點分隔，例如：2408, 2330)：", 
        value="2408"
    )
    target_map = {"^TWII": "台股加權大盤"}
    if custom_tickers_input.strip():
        items = custom_tickers_input.replace("，", ",").split(",")
        for raw_item in items:
            code = raw_item.strip().upper()
            if code:
                if not code.endswith(".TW") and not code.startswith("^"):
                    full_code = code + ".TW"
                else:
                    full_code = code
                stock_name = get_stock_name(full_code)
                target_map[full_code] = stock_name

# 4. 下載數據
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

        st.info(f"🕒 **數據抓取時間**：`{fetch_time} (台灣時間)` ｜ 📅 **最新市場交易日**：`{latest_market_date}`")

        # 計算指標
        ret_3d = (close_prices.iloc[-1] / close_prices.iloc[-4] - 1) * 100
        ret_5d = (close_prices.iloc[-1] / close_prices.iloc[-6] - 1) * 100
        vol_5d_avg = volumes.tail(5).mean()
        vol_ratio = volumes.iloc[-1] / vol_5d_avg
        market_3d = ret_3d["^TWII"] if "^TWII" in ret_3d else 0.0

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
            
        df = pd.DataFrame(results).sort_values(by="3日漲跌(%)", ascending=False).reset_index(drop=True)

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

            # 🔥 手機優化版四象限散佈圖 🔥
            st.subheader(f"📌 {view_mode} - 四象限熱錢分布圖")
            
            # 使用 Plotly Express 建立基礎圖
            fig = px.scatter(
                df, 
                x="量比(較5日均量)", 
                y="3日漲跌(%)", 
                color="資金診斷",
                hover_name="股票/標的名稱",
                hover_data={"代號": True, "3日漲跌(%)": ":.2f%", "量比(較5日均量)": ":.2f", "資金診斷": False},
                size_max=18
            )

            # 加上散佈點標籤 (精簡名稱避開重疊)
            fig.update_traces(
                text=df["股票/標的名稱"].apply(lambda x: x.split(" ")[0]), # 只顯示簡稱
                textposition='top center',
                textfont=dict(size=11),
                marker=dict(size=12, line=dict(width=1, color='DarkSlateGrey'))
            )

            # 加入輔助參考十字線 (量比=1.0, 漲跌=0%)
            fig.add_vline(x=1.0, line_dash="dash", line_color="gray", opacity=0.7)
            fig.add_hline(y=0.0, line_dash="dash", line_color="gray", opacity=0.7)

            # 調整手機佈局與邊距
            fig.update_layout(
                height=550, # 加高圖表
                margin=dict(l=10, r=10, t=30, b=10),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=10)),
                xaxis_title="量比 ( > 1.0 代表爆量 )",
                yaxis_title="3 日漲跌幅 (%)",
                hoverlabel=dict(font_size=13)
            )

            st.plotly_chart(fig, use_container_width=True)

            # 🔥 新增：手機友善的「熱錢強度直條圖」
            st.subheader("📊 資金關注動能前 10 名")
            fig_bar = px.bar(
                df.head(10),
                x="3日漲跌(%)",
                y="股票/標的名稱",
                orientation='h',
                color="量比(較5日均量)",
                color_continuous_scale="Reds",
                text="3日漲跌(%)"
            )
            fig_bar.update_layout(
                yaxis=dict(autorange="reversed"), # 強者排最上方
                height=400,
                margin=dict(l=10, r=10, t=10, b=10)
            )
            fig_bar.update_traces(texttemplate='%{text}%', textposition='outside')
            st.plotly_chart(fig_bar, use_container_width=True)

            # 詳細數據明細表
            st.subheader(f"📋 數據排行榜明細 (共 {len(df)} 支)")
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("沒有可顯示的標的，請於左側選單輸入自訂股票代號。")

except Exception as e:
    st.error(f"數據載入失敗，請稍後重試或重新整理：{e}")
