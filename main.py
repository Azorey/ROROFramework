import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import os
from datetime import datetime

# =================配置区域=================

# 1. 核心监控指标 (你的原有指标)
INDICATORS = [
    {
        "name": "消费周期风向标 (XLY/XLP)",
        "numerator": "XLY",
        "denominator": "XLP",
        "description": "Risk On/Off 核心指标"
    }
]

# 2. 板块轮动配置 (11大行业 + 基准)
SECTOR_CONFIG = {
    'BENCHMARK': 'SPY',
    'SECTORS': {
        'XLK': '科技', 'XLY': '非必需消费', 'XLC': '通讯',
        'XLV': '医疗', 'XLP': '必需消费', 'XLE': '能源',
        'XLF': '金融', 'XLI': '工业', 'XLB': '材料',
        'XLU': '公用', 'XLRE': '地产'
    }
}

# Telegram 配置
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")

# 配色方案
COLORS = {
    'ema20': 'gray', 'sma20': '#D3D3D3',
    'ema60': 'red', 'sma60': '#FDBCB4',
    'ema120': 'blue', 'sma120': '#ADD8E6',
    'dkj': '#FFC40C',
    # 象限颜色
    'leading': '#2ca02c',   # 绿 (领涨)
    'weakening': '#e6aa00', # 黄 (衰退)
    'lagging': '#d62728',   # 红 (落后)
    'improving': '#1f77b4'  # 蓝 (改善)
}
# =========================================

def get_data(tickers, period="3y"):
    """统一数据下载函数"""
    print(f"正在下载数据: {tickers} ...")
    try:
        # yfinance 在下载多个ticker时，如果某个ticker出错可能会影响整体结构
        # group_by='ticker' 确保结构统一
        data = yf.download(list(tickers), period=period, group_by='ticker', auto_adjust=True)
        
        # 提取 Close 列，处理多级索引
        df_close = pd.DataFrame()
        for t in tickers:
            try:
                # 兼容 yfinance 不同版本的返回结构
                if (t, 'Close') in data.columns:
                    df_close[t] = data[(t, 'Close')]
                elif t in data.columns:
                    # 如果只有一级列名（单ticker下载时可能发生）
                    if isinstance(data[t], pd.Series):
                        df_close[t] = data[t]
                    else:
                        df_close[t] = data[t]['Close']
            except Exception:
                pass
        return df_close
    except Exception as e:
        print(f"数据下载严重错误: {e}")
        return pd.DataFrame()

def calculate_rrg_components(df_close):
    """
    计算板块轮动(RRG)坐标
    X轴: Jdrs (相对强度比率) - 衡量趋势强弱
    Y轴: Jdmom (相对强度动量) - 衡量趋势变化速度
    """
    benchmark = SECTOR_CONFIG['BENCHMARK']
    sectors = SECTOR_CONFIG['SECTORS'].keys()
    
    rrg_data = {}
    
    # RRG 参数设置
    window_rs = 60  # 长期趋势窗口 (约一季度)
    window_mom = 10 # 动量窗口 (两周)

    for sec in sectors:
        if sec not in df_close.columns or benchmark not in df_close.columns:
            continue
            
        # 1. 计算原始 RS (Relative Strength)
        rs_raw = df_close[sec] / df_close[benchmark]
        
        # 2. 计算 R_Ratio (X轴): 当前RS相对于过去趋势的位置 (归一化到 100)
        # 简化版算法：(RS / MA(RS)) * 100
        rs_ma = rs_raw.rolling(window=window_rs).mean()
        r_ratio = 100 * (rs_raw / rs_ma)
        
        # 3. 计算 R_Momentum (Y轴): R_Ratio 的变化率 (归一化到 100)
        # 简化版算法：(R_Ratio / MA(R_Ratio)) * 100
        # 这里使用较短的窗口来捕捉动能
        mom_ma = r_ratio.rolling(window=window_mom).mean()
        r_mom = 100 * (r_ratio / mom_ma)
        
        # 保存最后 5 天的数据用于画轨迹 (Tail)
        rrg_data[sec] = {
            'name': SECTOR_CONFIG['SECTORS'][sec],
            'x': r_ratio.tail(5).values,
            'y': r_mom.tail(5).values,
            'current_x': r_ratio.iloc[-1],
            'current_y': r_mom.iloc[-1]
        }
        
    return rrg_data

def calculate_indicators(indicators, df_close):
    """计算 XLY/XLP 等独立指标"""
    results = []
    for item in indicators:
        try:
            ratio = df_close[item['numerator']] / df_close[item['denominator']]
            df = pd.DataFrame({'close': ratio})
            
            # 均线系统
            for w in [20, 60, 120]:
                df[f'sma{w}'] = df['close'].rolling(window=w).mean()
                df[f'ema{w}'] = df['close'].ewm(span=w, adjust=False).mean()
            
            results.append({
                "meta": item,
                "df": df,
                "latest_value": df['close'].iloc[-1]
            })
        except KeyError:
            print(f"计算指标 {item['name']} 失败，数据缺失")
    return results

def get_quadrant_color(x, y):
    """根据坐标判断颜色"""
    if x > 100 and y > 100: return COLORS['leading']   # 领涨 (右上)
    if x < 100 and y > 100: return COLORS['improving'] # 改善 (左上)
    if x < 100 and y < 100: return COLORS['lagging']   # 落后 (左下)
    return COLORS['weakening']                         # 衰退 (右下)

def generate_dashboard(rrg_data, indicator_results):
    """生成综合仪表盘 HTML"""
    
    # 布局: 第一行给 RRG 雷达图 (高度较大)，后面给普通指标
    rows = 1 + len(indicator_results)
    specs = [[{"type": "xy"}]] + [[{"type": "xy"}]] * len(indicator_results)
    
    fig = make_subplots(
        rows=rows, cols=1,
        row_heights=[0.5] + [0.5/len(indicator_results)] * len(indicator_results) if indicator_results else [1.0],
        subplot_titles=["🛡️ <b>板块轮动雷达 (RRG)</b> - 寻找领涨主线"] + [item['meta']['name'] for item in indicator_results],
        vertical_spacing=0.08
    )

    # --- 绘制 RRG 雷达图 (Row 1) ---
    # 绘制象限背景线
    fig.add_hline(y=100, line_dash="dot", line_color="gray", row=1, col=1)
    fig.add_vline(x=100, line_dash="dot", line_color="gray", row=1, col=1)
    
    # 绘制背景文字
    fig.add_annotation(x=104, y=104, text="领先 (Leading)", showarrow=False, font=dict(color="green", size=14), row=1, col=1)
    fig.add_annotation(x=96, y=104, text="改善 (Improving)", showarrow=False, font=dict(color="blue", size=14), row=1, col=1)
    fig.add_annotation(x=96, y=96, text="落后 (Lagging)", showarrow=False, font=dict(color="red", size=14), row=1, col=1)
    fig.add_annotation(x=104, y=96, text="衰退 (Weakening)", showarrow=False, font=dict(color="orange", size=14), row=1, col=1)

    for sec, data in rrg_data.items():
        # 1. 绘制轨迹 (Tail) - 线条
        fig.add_trace(
            go.Scatter(
                x=data['x'], y=data['y'],
                mode='lines',
                line=dict(color='gray', width=1),
                opacity=0.5,
                showlegend=False,
                hoverinfo='skip'
            ), row=1, col=1
        )
        
        # 2. 绘制当前点 - 散点
        color = get_quadrant_color(data['current_x'], data['current_y'])
        fig.add_trace(
            go.Scatter(
                x=[data['current_x']], 
                y=[data['current_y']],
                mode='markers+text',
                name=f"{sec} {data['name']}",
                text=sec,
                textposition="top center",
                marker=dict(size=12, color=color, line=dict(width=1, color='black')),
                hovertemplate=f"<b>{data['name']} ({sec})</b><br>趋势强度: %{{x:.2f}}<br>动量: %{{y:.2f}}<extra></extra>"
            ), row=1, col=1
        )

    # --- 绘制常规指标图 (Row 2+) ---
    for idx, res in enumerate(indicator_results):
        row = idx + 2
        df = res['df']
        
        # K线
        fig.add_trace(go.Scatter(x=df.index, y=df['close'], name="Ratio", line=dict(color='black', width=1.5), opacity=0.6), row=row, col=1)
        
        # 均线
        for w in [20, 60, 120]:
            fig.add_trace(go.Scatter(x=df.index, y=df[f'sma{w}'], name=f"SMA{w}", line=dict(color=COLORS[f'sma{w}'], width=1)), row=row, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df[f'ema{w}'], name=f"EMA{w}", line=dict(color=COLORS[f'ema{w}'], width=1)), row=row, col=1)

        # DKJ 标记
        curr_idx = len(df) - 1
        dkj_x, dkj_y, dkj_text = [], [], []
        for lb in [20, 60, 120]:
            target = curr_idx - lb
            if target >= 0:
                dkj_x.append(df.index[target])
                dkj_y.append(df['close'].iloc[target])
                dkj_text.append(f"T-{lb}")
        
        if dkj_x:
            fig.add_trace(go.Scatter(x=dkj_x, y=dkj_y, mode='markers', name="DKJ", marker=dict(color=COLORS['dkj'], size=8), text=dkj_text), row=row, col=1)

    fig.update_layout(
        title_text=f"量化交易员看板 (生成于 {datetime.now().strftime('%Y-%m-%d')})",
        height=700 + 400 * len(indicator_results),
        template="plotly_white",
        showlegend=True
    )
    
    fig.write_html("index.html")
    print("Dashboard 生成完毕: index.html")

def send_telegram(rrg_data, indicator_results):
    if not TG_BOT_TOKEN or not TG_CHAT_ID: return

    # 1. 分析 RRG 领涨板块
    leading_sectors = []
    improving_sectors = []
    for sec, data in rrg_data.items():
        if data['current_x'] > 100 and data['current_y'] > 100:
            leading_sectors.append(data['name'])
        elif data['current_x'] < 100 and data['current_y'] > 100:
            improving_sectors.append(data['name'])

    # 2. 构建消息
    repo = os.environ.get("GITHUB_REPOSITORY", "repo")
    url = f"https://{repo.split('/')[0]}.github.io/{repo.split('/')[1]}/" if "/" in repo else "http://github.com"
    
    lines = [f"🚀 **{datetime.now().strftime('%Y-%m-%d')} 市场雷达**\n"]
    
    if leading_sectors:
        lines.append(f"🔥 **强势领涨 (Leading):**\n" + "、".join(leading_sectors))
    if improving_sectors:
        lines.append(f"📈 **蓄势待发 (Improving):**\n" + "、".join(improving_sectors))
    
    lines.append("\n" + "-"*15 + "\n")
    
    # 3. 添加指标状态
    for res in indicator_results:
        name = res['meta']['name']
        curr = res['latest_value']
        ema20 = res['df']['ema20'].iloc[-1]
        trend = "看多 🐂" if curr > ema20 else "看空 🐻"
        lines.append(f"📊 **{name}**")
        lines.append(f"现值: `{curr:.4f}` ({trend})")

    lines.append(f"\n🔗 [查看完整交互仪表盘]({url})")
    
    requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage", 
                  json={"chat_id": TG_CHAT_ID, "text": "\n".join(lines), "parse_mode": "Markdown"})

def main():
    # 1. 收集所有需要下载的 Ticker
    all_tickers = set([SECTOR_CONFIG['BENCHMARK']])
    all_tickers.update(SECTOR_CONFIG['SECTORS'].keys())
    for item in INDICATORS:
        all_tickers.add(item['numerator'])
        all_tickers.add(item['denominator'])
    
    # 2. 批量下载
    df_all = get_data(all_tickers)
    if df_all.empty: return

    # 3. 计算各个模块
    rrg_data = calculate_rrg_components(df_all)
    indicator_results = calculate_indicators(INDICATORS, df_all)
    
    # 4. 生成与推送
    generate_dashboard(rrg_data, indicator_results)
    send_telegram(rrg_data, indicator_results)

if __name__ == "__main__":
    main()
