import streamlit as st
import pandas as pd
import akshare as ak
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta

# --- 1. 页面配置 ---
st.set_page_config(page_title="A股K线五线推演系统", layout="wide", initial_sidebar_state="expanded")

# --- 2. 数据获取函数 ---
@st.cache_data(ttl=3600, show_spinner=False)
def get_stock_history_safe(symbol, start_date, end_date):
    symbol = symbol.strip()
    try:
        # 为了计算120日均线，我们需要确保获取的数据量足够
        df = ak.stock_zh_a_hist(
            symbol=symbol, period="daily", 
            start_date=start_date, end_date=end_date, adjust="qfq"
        )
        return df if df is not None and not df.empty else pd.DataFrame()
    except Exception as e:
        st.sidebar.error(f"接口调用失败: {e}")
        return pd.DataFrame()

# --- 3. 侧边栏：推演参数 ---
with st.sidebar:
    st.title("🔮 五线走势预演")
    st.subheader("未来5日预期设置")
    
    predict_settings = []
    for i in range(1, 6):
        with st.expander(f"第 {i} 个交易日推演", expanded=(i==1)):
            mode = st.radio(f"模式_{i}", ["按价格", "按涨跌幅(%)"], horizontal=True, key=f"m_{i}")
            if mode == "按价格":
                val = st.number_input(f"设定价格", value=0.0, step=0.01, format="%.2f", key=f"p_{i}")
                predict_settings.append({"type": "price", "value": val})
            else:
                pct = st.number_input(f"设定涨跌幅%", value=0.0, step=0.1, format="%.1f", key=f"pct_{i}")
                predict_settings.append({"type": "percent", "value": pct})

    st.markdown("---")
    if st.button("强制刷新数据"):
        st.cache_data.clear()
        st.rerun()

# --- 4. 主页面 ---
st.header("📈 A股个股K线推演 (MA5/10/20/60/120)")

c1, c2 = st.columns([1, 3])
with c1:
    target_stock = st.text_input("输入股票代码", value="000001")
with c2:
    # 既然要看120日线，建议回溯长度至少从250天(一年)起步
    lookback = st.select_slider("显示历史长度", options=[120, 250, 500, 1000], value=250)

# 核心：为了让图表左侧第一天就有120日均线，获取数据的时间要比显示的时间更早
fetch_days = lookback + 150 
end_dt = datetime.now()
start_dt = end_dt - timedelta(days=fetch_days)
with st.spinner('调取深度数据中...'):
    raw_df = get_stock_history_safe(target_stock, start_dt.strftime("%Y%m%d"), end_dt.strftime("%Y%m%d"))

if not raw_df.empty:
    df = raw_df.copy()
    df['日期'] = pd.to_datetime(df['日期'])
    df['is_predict'] = False
    
    # 初始参考数据
    last_price = df['收盘'].iloc[-1]
    last_date = df['日期'].iloc[-1]
    
    future_rows = []
    current_ref_price = last_price
    current_date = last_date
    
    # 推演计算
    for item in predict_settings:
        current_date += timedelta(days=1)
        while current_date.weekday() >= 5: current_date += timedelta(days=1)
            
        if item['type'] == "price" and item['value'] > 0:
            target_p = item['value']
        elif item['type'] == "percent":
            target_p = current_ref_price * (1 + item['value'] / 100)
        else:
            target_p = current_ref_price
            
        future_rows.append({
            '日期': current_date, '开盘': current_ref_price, 
            '最高': max(current_ref_price, target_p), '最低': min(current_ref_price, target_p), 
            '收盘': target_p, '成交量': 0, 'is_predict': True
        })
        current_ref_price = target_p
        
    # 合并数据并计算五线
    df_full = pd.concat([df, pd.DataFrame(future_rows)], ignore_index=True)
    df_full['日期str'] = df_full['日期'].dt.strftime('%Y-%m-%d')
    
    # 计算5线：5, 10, 20, 60, 120
    ma_list = [5, 10, 20, 60, 120]
    for m in ma_list:
        df_full[f'MA{m}'] = df_full['收盘'].rolling(m).mean()

    # 只保留用户想要显示的长度进行绘图
    df_plot = df_full.iloc[-(lookback + 5):]

    # --- 5. 绘图 ---
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.7, 0.3])

    h_df = df_plot[~df_plot['is_predict']]
    p_df = df_plot[df_plot['is_predict']]
    
    # K线
    fig.add_trace(go.Candlestick(x=h_df['日期str'], open=h_df['开盘'], high=h_df['最高'], low=h_df['最低'], close=h_df['收盘'], name='历史'), row=1, col=1)
    fig.add_trace(go.Candlestick(x=p_df['日期str'], open=p_df['开盘'], high=p_df['最高'], low=p_df['最低'], close=p_df['收盘'], name='预演', opacity=0.4), row=1, col=1)

    # 五线配色方案
    colors = {
        'MA5': '#FFD700',   # 金色
        'MA10': '#1E90FF',  # 闪亮蓝
        'MA20': '#FF00FF',  # 紫色/洋红
        'MA60': '#00FF00',  # 鲜绿色 (生命线)
        'MA120': '#FFFFFF'  # 白色 (半年线)
    }
    for ma in ma_list:
        name = f'MA{ma}'
        fig.add_trace(go.Scatter(x=df_plot['日期str'], y=df_plot[name], name=name, line=dict(color=colors[name], width=1.2)), row=1, col=1)

    # 成交量
    v_colors = ['red' if r.收盘 >= r.开盘 else 'green' for r in h_df.itertuples()]
    fig.add_trace(go.Bar(x=h_df['日期str'], y=h_df['成交量'], name='成交量', marker_color=v_colors), row=2, col=1)

    fig.update_layout(height=800, template="plotly_dark", xaxis_rangeslider_visible=False, hovermode="x unified")
    fig.update_xaxes(type='category', nticks=15)
    st.plotly_chart(fig, use_container_width=True)

    # 6. 数据看板
    st.subheader("📋 均线推演细节表")
    table_df = p_df[['日期str', '收盘', 'MA5', 'MA10', 'MA20', 'MA60', 'MA120']].copy()
    st.dataframe(table_df.style.format(precision=2), use_container_width=True)

else:
    st.warning("数据调取中，请稍后... 若失败请检查代码或网络。")
