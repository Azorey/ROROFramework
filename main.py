import yfinance as yf
import pandas as pd
import numpy as np
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
        "description": "Risk On/Off 核心指标"
    }
]

SECTOR_CONFIG = {
    'BENCHMARK': 'SPY',
    'SECTORS': {
        'XLK': '科技', 'XLY': '非必需消费', 'XLC': '通讯',
        'XLV': '医疗', 'XLP': '必需消费', 'XLE': '能源',
        'XLF': '金融', 'XLI': '工业', 'XLB': '材料',
        'XLU': '公用', 'XLRE': '地产'
    }
}

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")

COLORS = {
    'ema20': 'gray', 'sma20': '#D3D3D3',
    'ema60': 'red', 'sma60': '#FDBCB4',
    'ema120': 'blue', 'sma120': '#ADD8E6',
    'dkj': '#FFC40C',
    'leading': '#2ca02c',   # 绿
    'weakening': '#e6aa00', # 黄
    'lagging': '#d62728',   # 红
    'improving': '#1f77b4'  # 蓝
}
# =========================================

def get_data(tickers, period="3y"):
    """下载数据"""
    print(f"正在下载数据: {tickers} ...")
    try:
        data = yf.download(list(tickers), period=period, group_by='ticker', auto_adjust=True)
        df_close = pd.DataFrame()
        for t in tickers:
            try:
                if (t, 'Close') in data.columns:
                    df_close[t] = data[(t, 'Close')]
                elif t in data.columns:
                    if isinstance(data[t], pd.Series):
                        df_close[t] = data[t]
                    else:
                        df_close[t] = data[t]['Close']
            except Exception:
                pass
        return df_close
    except Exception as e:
        print(f"数据下载错误: {e}")
        return pd.DataFrame()

def calculate_rrg_components(df_close):
    """计算 RRG 坐标"""
    benchmark = SECTOR_CONFIG['BENCHMARK']
    sectors = SECTOR_CONFIG['SECTORS'].keys()
    rrg_data = {}
    
    window_rs = 60
    window_mom = 10 

    for sec in sectors:
        if sec not in df_close.columns or benchmark not in df_close.columns:
            continue
            
        rs_raw = df_close[sec] / df_close[benchmark]
        
        # 归一化计算
        rs_ma = rs_raw.rolling(window=window_rs).mean()
        r_ratio = 100 * (rs_raw / rs_ma)
        
        mom_ma = r_ratio.rolling(window=window_mom).mean()
        r_mom = 100 * (r_ratio / mom_ma)
        
        rrg_data[sec] = {
            'name': SECTOR_CONFIG['SECTORS'][sec],
            'x': r_ratio.tail(5).values,
            'y': r_mom.tail(5).values,
            'current_x': r_ratio.iloc[-1],
            'current_y': r_mom.iloc[-1]
        }
    return rrg_data

def calculate_indicators(indicators, df_close):
    """计算常规指标"""
    results = []
    for item in indicators:
        try:
            ratio = df_close[item['numerator']] / df_close[item['denominator']]
            df = pd.DataFrame({'close': ratio})
            for w in [20, 60, 120]:
                df[f'sma{w}'] = df['close'].rolling(window=w).mean()
                df[f'ema{w}'] = df['close'].ewm(span=w, adjust=False).mean()
            results.append({"meta": item, "df": df, "latest_value": df['close'].iloc[-1]})
        except KeyError:
            pass
    return results

def get_quadrant_color(x, y):
    if x > 100 and y > 100: return COLORS['leading']
    if x < 100 and y > 100: return COLORS['improving']
    if x < 100 and y < 100: return COLORS['lagging']
    return COLORS['weakening']

def generate_dashboard(rrg_data, indicator_results):
    """生成仪表盘 (含视觉修正)"""
    
    # 计算行数，RRG 占第一行
    rows = 1 + len(indicator_results)
    
    # 调整高度：RRG 给大一点的正方形空间
    row_heights = [0.6] + [0.4/len(indicator_results)] * len(indicator_results) if indicator_results else [1.0]

    fig = make_subplots(
        rows=rows, cols=1,
        row_heights=row_heights,
        subplot_titles=["🛡️ <b>板块轮动雷达 (RRG)</b>"] + [item['meta']['name'] for item in indicator_results],
        vertical_spacing=0.1
    )

    # --- 1. RRG 雷达图绘制 ---
    
    # 【修正2】 加粗分界线
    # 使用实线 (solid) 或 长虚线 (longdash)，宽度设为 3，颜色纯黑
    fig.add_hline(y=100, line_dash="solid", line_color="black", line_width=2, opacity=0.8, row=1, col=1)
    fig.add_vline(x=100, line_dash="solid", line_color="black", line_width=2, opacity=0.8, row=1, col=1)
    
    # 标注文字
    fig.add_annotation(x=104, y=104, text="领先", showarrow=False, font=dict(color="green", size=16, weight="bold"), row=1, col=1)
    fig.add_annotation(x=96, y=104, text="改善", showarrow=False, font=dict(color="blue", size=16, weight="bold"), row=1, col=1)
    fig.add_annotation(x=96, y=96, text="落后", showarrow=False, font=dict(color="red", size=16, weight="bold"), row=1, col=1)
    fig.add_annotation(x=104, y=96, text="衰退", showarrow=False, font=dict(color="orange", size=16, weight="bold"), row=1, col=1)

    for sec, data in rrg_data.items():
        # 轨迹线
        fig.add_trace(
            go.Scatter(x=data['x'], y=data['y'], mode='lines', line=dict(color='gray', width=1), opacity=0.5, showlegend=False, hoverinfo='skip'),
            row=1, col=1
        )
        # 当前点
        color = get_quadrant_color(data['current_x'], data['current_y'])
        fig.add_trace(
            go.Scatter(
                x=[data['current_x']], y=[data['current_y']],
                mode='markers+text',
                name=sec,
                text=sec, textposition="top center",
                marker=dict(size=14, color=color, line=dict(width=1, color='black')),
                hovertemplate=f"<b>{data['name']}</b><br>RS: %{{x:.2f}}<br>Mom: %{{y:.2f}}<extra></extra>"
            ), row=1, col=1
        )

    # --- 2. 常规指标绘制 ---
    for idx, res in enumerate(indicator_results):
        row = idx + 2
        df = res['df']
        # K线
        fig.add_trace(go.Scatter(x=df.index, y=df['close'], name="Ratio", line=dict(color='black', width=1.5), opacity=0.6), row=row, col=1)
        # 均线
        for w in [20, 60, 120]:
            fig.add_trace(go.Scatter(x=df.index, y=df[f'sma{w}'], name=f"SMA{w}", line=dict(color=COLORS[f'sma{w}'], width=1)), row=row, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df[f'ema{w}'], name=f"EMA{w}", line=dict(color=COLORS[f'ema{w}'], width=1)), row=row, col=1)
        # DKJ
        curr_idx = len(df) - 1
        dkj_x, dkj_y = [], []
        for lb in [20, 60, 120]:
            target = curr_idx - lb
            if target >= 0:
                dkj_x.append(df.index[target])
                dkj_y.append(df['close'].iloc[target])
        if dkj_x:
            fig.add_trace(go.Scatter(x=dkj_x, y=dkj_y, mode='markers', name="DKJ", marker=dict(color=COLORS['dkj'], size=8)), row=row, col=1)

    # --- 全局 Layout 修正 ---
    fig.update_layout(
        title_text=f"量化交易员看板 ({datetime.now().strftime('%Y-%m-%d')})",
        # 【重要】锁定总宽度，防止带鱼屏拉伸过长
        width=1000, 
        height=800 + 300 * len(indicator_results),
        template="plotly_white",
        showlegend=True
    )

    # 【修正1】 强制 RRG 区域 (Row 1) 为正方形比例 (1 unit x = 1 unit y)
    fig.update_yaxes(
        scaleanchor="x",
        scaleratio=1,
        row=1, col=1
    )
    # 为 RRG 设置合理的 Range padding，避免点贴在边框上
    fig.update_xaxes(constrain='domain', row=1, col=1)
    
    fig.write_html("index.html")
    print("Dashboard 生成完毕: index.html")

def send_telegram(rrg_data, indicator_results):
    if not TG_BOT_TOKEN or not TG_CHAT_ID: return

    leading = [d['name'] for d in rrg_data.values() if d['current_x']>100 and d['current_y']>100]
    improving = [d['name'] for d in rrg_data.values() if d['current_x']<100 and d['current_y']>100]
    
    repo = os.environ.get("GITHUB_REPOSITORY", "repo")
    url = f"https://{repo.split('/')[0]}.github.io/{repo.split('/')[1]}/" if "/" in repo else "http://github.com"
    
    lines = [f"🚀 **{datetime.now().strftime('%Y-%m-%d')} 市场雷达**\n"]
    if leading: lines.append(f"🔥 **领涨:** {', '.join(leading)}")
    if improving: lines.append(f"📈 **蓄势:** {', '.join(improving)}")
    lines.append("\n" + "-"*15)
    
    for res in indicator_results:
        trend = "🐂" if res['latest_value'] > res['df']['ema20'].iloc[-1] else "🐻"
        lines.append(f"📊 {res['meta']['name']}: `{res['latest_value']:.4f}` {trend}")

    lines.append(f"\n🔗 [查看可视化报表]({url})")
    
    requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage", 
                  json={"chat_id": TG_CHAT_ID, "text": "\n".join(lines), "parse_mode": "Markdown"})

def main():
    all_tickers = set([SECTOR_CONFIG['BENCHMARK']])
    all_tickers.update(SECTOR_CONFIG['SECTORS'].keys())
    for item in INDICATORS:
        all_tickers.add(item['numerator'])
        all_tickers.add(item['denominator'])
    
    df_all = get_data(all_tickers)
    if df_all.empty: return

    rrg = calculate_rrg_components(df_all)
    ind = calculate_indicators(INDICATORS, df_all)
    generate_dashboard(rrg, ind)
    send_telegram(rrg, ind)

if __name__ == "__main__":
    main()
