import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import os
from datetime import datetime

# =================配置区域=================
INDICATORS = [
    {
        "name": "消费周期风向标 (XLY/XLP)",
        "numerator": "XLY",
        "denominator": "XLP",
        "description": "上升代表风险偏好增强 (Risk On)，下降代表防御心态 (Risk Off)"
    },
    # 你可以在这里继续添加其他指标，例如 QQQ/SPY
]

# Telegram 配置
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")

# 配色方案 (对应 PineScript)
COLORS = {
    'ema20': 'gray',
    'sma20': '#D3D3D3', # Light Gray
    'ema60': 'red',
    'sma60': '#FDBCB4', # Light Red
    'ema120': 'blue',
    'sma120': '#ADD8E6', # Light Blue
    'dkj': '#FFC40C'     # Gold (抵扣价标记)
}
# =========================================

def get_data_and_calculate(indicators):
    """下载数据并计算比率及均线系统"""
    results = []
    
    # 收集 Ticker
    tickers = set()
    for item in indicators:
        tickers.add(item['numerator'])
        tickers.add(item['denominator'])
    
    print(f"正在下载数据: {tickers} ...")
    # 下载 3 年数据，确保 120 日均线有足够的数据计算
    try:
        data = yf.download(list(tickers), period="3y", auto_adjust=True)['Close']
    except Exception as e:
        print(f"数据下载失败: {e}")
        return []

    for item in indicators:
        try:
            # 1. 计算基础比率 (Close / Close)
            # 注意：合成指标通常没有 High/Low 概念，我们基于收盘价计算比率
            ratio = data[item['numerator']] / data[item['denominator']]
            
            # 创建 DataFrame 用于存储所有指标
            df = pd.DataFrame({'close': ratio})
            
            # 2. 计算 SMA (Simple Moving Average)
            df['sma20'] = df['close'].rolling(window=20).mean()
            df['sma60'] = df['close'].rolling(window=60).mean()
            df['sma120'] = df['close'].rolling(window=120).mean()
            
            # 3. 计算 EMA (Exponential Moving Average)
            # pandas ewm span=N 对应 PineScript ta.ema(N)
            df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
            df['ema60'] = df['close'].ewm(span=60, adjust=False).mean()
            df['ema120'] = df['close'].ewm(span=120, adjust=False).mean()

            # 4. 获取抵扣价 (Lookback Data)
            # 为了在图上画圈，我们需要找到 T-20, T-60, T-120 的位置
            # 使用 shift 来获取历史数据，或者直接在绘图时按索引提取
            
            results.append({
                "meta": item,
                "df": df, # 包含所有计算结果的 DataFrame
                "latest_value": df['close'].iloc[-1],
                "prev_value": df['close'].iloc[-2]
            })
        except KeyError as e:
            print(f"计算 {item['name']} 失败，可能是数据缺失: {e}")
    
    return results

def generate_plot(results):
    """生成包含完整均线系统和 DKJ 标记的图表"""
    fig = make_subplots(
        rows=len(results), cols=1,
        subplot_titles=[item['meta']['name'] for item in results],
        vertical_spacing=0.1
    )

    for idx, res in enumerate(results):
        row = idx + 1
        df = res['df']
        
        # --- 1. 绘制 K线/收盘线 (比率本身) ---
        fig.add_trace(
            go.Scatter(x=df.index, y=df['close'], name="Ratio (Close)",
                       line=dict(color='black', width=1.5), opacity=0.6),
            row=row, col=1
        )

        # --- 2. 绘制均线系统 (EMA 在前，SMA 在后) ---
        # 20周期
        fig.add_trace(go.Scatter(x=df.index, y=df['sma20'], name="SMA 20", line=dict(color=COLORS['sma20'], width=1.5)), row=row, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['ema20'], name="EMA 20", line=dict(color=COLORS['ema20'], width=1.5)), row=row, col=1)
        
        # 60周期
        fig.add_trace(go.Scatter(x=df.index, y=df['sma60'], name="SMA 60", line=dict(color=COLORS['sma60'], width=1.5)), row=row, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['ema60'], name="EMA 60", line=dict(color=COLORS['ema60'], width=1.5)), row=row, col=1)
        
        # 120周期
        fig.add_trace(go.Scatter(x=df.index, y=df['sma120'], name="SMA 120", line=dict(color=COLORS['sma120'], width=1.5)), row=row, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['ema120'], name="EMA 120", line=dict(color=COLORS['ema120'], width=1.5)), row=row, col=1)

        # --- 3. 绘制 DKJ 抵扣价标记 (Circles) ---
        # 逻辑：找到当前日期往前推 20/60/120 天的数据点
        lookbacks = [20, 60, 120]
        
        # 收集要打点的 x (时间) 和 y (数值)
        dkj_x = []
        dkj_y = []
        dkj_text = []

        curr_idx = len(df) - 1
        
        for lb in lookbacks:
            target_idx = curr_idx - lb
            if target_idx >= 0:
                # 获取该位置的时间和数值
                point_time = df.index[target_idx]
                point_val = df['close'].iloc[target_idx]
                
                dkj_x.append(point_time)
                dkj_y.append(point_val)
                dkj_text.append(f"T-{lb} (抵扣价)")

        if dkj_x:
            fig.add_trace(
                go.Scatter(
                    x=dkj_x, 
                    y=dkj_y,
                    mode='markers',
                    name="DKJ (抵扣价)",
                    marker=dict(color=COLORS['dkj'], size=10, symbol='circle', line=dict(width=2, color='black')),
                    text=dkj_text,
                    hovertemplate="%{text}<br>Value: %{y:.4f}<extra></extra>"
                ),
                row=row, col=1
            )

    fig.update_layout(
        title_text=f"量化交易辅助面板 (生成于 {datetime.now().strftime('%Y-%m-%d')})",
        height=600 * len(results), # 增加高度以便看清细节
        template="plotly_white",
        hovermode="x unified" # 鼠标悬停时显示该时间点所有指标的值
    )
    
    fig.write_html("index.html")
    print("图表已生成: index.html")

def send_telegram_alert(results):
    """发送 Telegram 摘要"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("未配置 Telegram Token，跳过发送。")
        return

    repo_name = os.environ.get("GITHUB_REPOSITORY", "your_repo")
    # 处理 Github Pages URL，通常是 https://username.github.io/repo_name/
    if "/" in repo_name:
        username, repo = repo_name.split("/")
        page_url = f"https://{username}.github.io/{repo}/"
    else:
        page_url = "Check Repo"

    message_lines = [f"📅 **{datetime.now().strftime('%Y-%m-%d')} 市场信号**\n"]
    
    for res in results:
        df = res['df']
        name = res['meta']['name']
        curr = res['latest_value']
        
        # 简单的趋势判断：当前价格 vs EMA20
        ema20 = df['ema20'].iloc[-1]
        trend = "看多 🐂" if curr > ema20 else "看空 🐻"
        
        message_lines.append(f"📊 **{name}**")
        message_lines.append(f"现值: `{curr:.4f}`")
        message_lines.append(f"EMA20: `{ema20:.4f}` ({trend})")
        message_lines.append(f"DKJ位置: T-20, T-60 已在图中标注")
        message_lines.append("---")

    message_lines.append(f"🔗 [点击查看完整交互图表]({page_url})")
    
    msg = "\n".join(message_lines)
    
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram 推送错误: {e}")

def main():
    results = get_data_and_calculate(INDICATORS)
    if results:
        generate_plot(results)
        send_telegram_alert(results)
    else:
        print("无数据生成。")

if __name__ == "__main__":
    main()
