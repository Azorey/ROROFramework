import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import os
from datetime import datetime

# =================配置区域=================

# 1. 合成指数配置 (新增)
# 定义如何用现有 ETF 合成新的指数
SYNTHETIC_CONFIG = {
    'ERH': {
        'name': '新可选消费',
        'components': {'PEJ': 0.35, 'XHB': 0.35, 'XRT': 0.30}
    }
}

# 2. 核心监控指标 (已更新为 ERH/XLP)
INDICATORS = [
    {
        "name": "真实消费周期 (ERH/XLP)", # 名字改了
        "numerator": "ERH",             # 分子改为合成的 ERH
        "denominator": "XLP",
        "description": "去除科技权重干扰的纯实体消费风向标"
    },
    {
        "name": "经济扩张/避险 (XLI/XLU)",
        "numerator": "XLI",
        "denominator": "XLU",
        "description": "上升代表经济扩张预期，下降代表避险情绪"
    }
]

# 3. 板块配置
# 注意：这里我们把 XLY 换成了 ERH
SECTOR_CONFIG = {
    'BENCHMARK': 'SPY',
    'SECTORS': {
        'XLK':  '⚔️ 科技', 
        'ERH':  '⚔️ 新可选消费', # 替换了原来的 XLY
        'XLC':  '⚔️ 通讯',
        'XLF':  '⚔️ 金融', 
        'XLI':  '⚔️ 工业', 
        'XLB':  '⚔️ 材料',
        'XLRE': '⚔️ 地产',
        'XLP':  '🛡️ 必需消费', 
        'XLV':  '🛡️ 医疗', 
        'XLU':  '🛡️ 公用', 
        'XLE':  '🛢️ 能源',
    }
}

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")

COLORS = {
    'ema20': 'gray', 'sma20': '#D3D3D3',
    'ema60': 'red', 'sma60': '#FDBCB4',
    'ema120': 'blue', 'sma120': '#ADD8E6',
    'dkj': '#FFC40C',
    'leading': '#2ca02c',   'weakening': '#e6aa00',
    'lagging': '#d62728',   'improving': '#1f77b4'
}
# =========================================

def get_data_and_synthesize(period="3y"):
    """下载原始数据并计算合成指数"""
    
    # 1. 收集所有需要下载的真实 Ticker
    # 包括 Benchmark, 板块列表里的真实Ticker, 指标里的真实Ticker, 合成公式里的成分股
    real_tickers = set([SECTOR_CONFIG['BENCHMARK']])
    
    # 添加板块 (如果是合成的先跳过)
    for sec in SECTOR_CONFIG['SECTORS'].keys():
        if sec not in SYNTHETIC_CONFIG:
            real_tickers.add(sec)
            
    # 添加指标成分 (如果是合成的先跳过)
    for item in INDICATORS:
        if item['numerator'] not in SYNTHETIC_CONFIG: real_tickers.add(item['numerator'])
        if item['denominator'] not in SYNTHETIC_CONFIG: real_tickers.add(item['denominator'])
        
    # 添加合成指数的成分股 (PEJ, XHB, XRT 等)
    for synth_name, config in SYNTHETIC_CONFIG.items():
        for component in config['components'].keys():
            real_tickers.add(component)

    print(f"正在下载原始数据: {real_tickers} ...")
    try:
        data = yf.download(list(real_tickers), period=period, group_by='ticker', auto_adjust=True)
        
        # 整理 DataFrame
        df_close = pd.DataFrame()
        for t in real_tickers:
            try:
                if (t, 'Close') in data.columns:
                    df_close[t] = data[(t, 'Close')]
                elif t in data.columns:
                     # 处理单 Ticker 下载情况
                    col_data = data[t]
                    if isinstance(col_data, pd.DataFrame):
                        df_close[t] = col_data['Close']
                    else:
                        df_close[t] = col_data
            except Exception:
                pass
        
        # 2. 计算合成指数 (ERH)
        # 逻辑：加权求和。虽然严谨的指数需要除数调整，但作为 Proxy，直接加权股价即可反映趋势。
        for synth_name, config in SYNTHETIC_CONFIG.items():
            print(f"正在计算合成指数: {synth_name} ...")
            try:
                # 初始化为0
                composite_series = pd.Series(0, index=df_close.index)
                valid_calc = True
                
                for ticker, weight in config['components'].items():
                    if ticker in df_close.columns:
                        composite_series += df_close[ticker] * weight
                    else:
                        print(f"缺少成分股 {ticker} 数据，无法合成 {synth_name}")
                        valid_calc = False
                        break
                
                if valid_calc:
                    df_close[synth_name] = composite_series
            except Exception as e:
                print(f"合成 {synth_name} 失败: {e}")

        return df_close
        
    except Exception as e:
        print(f"数据处理严重错误: {e}")
        return pd.DataFrame()

def calculate_rrg_components(df_close):
    """计算 RRG 坐标"""
    benchmark = SECTOR_CONFIG['BENCHMARK']
    sectors = SECTOR_CONFIG['SECTORS'].keys()
    rrg_data = {}
    
    window_rs = 60
    window_mom = 10 

    for sec in sectors:
        # 检查数据是否存在 (ERH 已经在上一步合成进去了，所以这里能找到)
        if sec not in df_close.columns or benchmark not in df_close.columns:
            continue
            
        rs_raw = df_close[sec] / df_close[benchmark]
        rs_ma = rs_raw.rolling(window=window_rs).mean()
        r_ratio = 100 * (rs_raw / rs_ma)
        mom_ma = r_ratio.rolling(window=window_mom).mean()
        r_mom = 100 * (r_ratio / mom_ma)
        
        config_val = SECTOR_CONFIG['SECTORS'][sec]
        emoji = config_val.split(' ')[0] if ' ' in config_val else ''
        chart_label = f"{emoji} {sec}"
        display_name = f"{sec} {config_val}"

        rrg_data[sec] = {
            'chart_label': chart_label,
            'display_name': display_name,
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
            # ERH 这里也可以直接被调用
            ratio = df_close[item['numerator']] / df_close[item['denominator']]
            df = pd.DataFrame({'close': ratio})
            for w in [20, 60, 120]:
                df[f'sma{w}'] = df['close'].rolling(window=w).mean()
                df[f'ema{w}'] = df['close'].ewm(span=w, adjust=False).mean()
            results.append({"meta": item, "df": df, "latest_value": df['close'].iloc[-1]})
        except KeyError as e:
            print(f"指标 {item['name']} 计算失败: 缺少数据 {e}")
            pass
    return results

def get_quadrant_color(x, y):
    if x > 100 and y > 100: return COLORS['leading']
    if x < 100 and y > 100: return COLORS['improving']
    if x < 100 and y < 100: return COLORS['lagging']
    return COLORS['weakening']

def generate_dashboard(rrg_data, indicator_results):
    """生成仪表盘"""
    rows = 1 + len(indicator_results)
    row_heights = [0.55] + [0.45/len(indicator_results)] * len(indicator_results) if indicator_results else [1.0]

    fig = make_subplots(
        rows=rows, cols=1,
        row_heights=row_heights,
        subplot_titles=["🛡️ <b>板块轮动雷达 (RRG)</b>"] + [item['meta']['name'] for item in indicator_results],
        vertical_spacing=0.08
    )

    # RRG Background
    fig.add_shape(type="line", x0=0, x1=1, xref="x domain", y0=100, y1=100, yref="y", line=dict(color="black", width=2, dash="solid"), layer="below", row=1, col=1)
    fig.add_shape(type="line", x0=100, x1=100, xref="x", y0=0, y1=1, yref="y domain", line=dict(color="black", width=2, dash="solid"), layer="below", row=1, col=1)
    
    annotations = [
        dict(x=0.98, y=0.98, text="领先 (Leading)", font=dict(color="green", size=16, weight="bold"), xanchor="right", yanchor="top"),
        dict(x=0.02, y=0.98, text="改善 (Improving)", font=dict(color="blue", size=16, weight="bold"), xanchor="left", yanchor="top"),
        dict(x=0.02, y=0.02, text="落后 (Lagging)", font=dict(color="red", size=16, weight="bold"), xanchor="left", yanchor="bottom"),
        dict(x=0.98, y=0.02, text="衰退 (Weakening)", font=dict(color="orange", size=16, weight="bold"), xanchor="right", yanchor="bottom"),
    ]
    for ann in annotations:
        fig.add_annotation(xref="x domain", yref="y domain", row=1, col=1, showarrow=False, **ann)

    for sec, data in rrg_data.items():
        color = get_quadrant_color(data['current_x'], data['current_y'])
        fig.add_trace(go.Scatter(x=data['x'], y=data['y'], mode='lines', line=dict(color='gray', width=1), opacity=0.5, showlegend=False, hoverinfo='skip'), row=1, col=1)
        fig.add_trace(go.Scatter(x=[data['current_x']], y=[data['current_y']], mode='markers+text', name=data['display_name'], text=data['chart_label'], textposition="top center", marker=dict(size=14, color=color, line=dict(width=1, color='black')), hovertemplate=f"<b>{data['display_name']}</b><br>RS: %{{x:.2f}}<br>Mom: %{{y:.2f}}<extra></extra>"), row=1, col=1)

    for idx, res in enumerate(indicator_results):
        row = idx + 2
        df = res['df']
        fig.add_trace(go.Scatter(x=df.index, y=df['close'], name="Ratio", line=dict(color='black', width=1.5), opacity=0.6), row=row, col=1)
        for w in [20, 60, 120]:
            fig.add_trace(go.Scatter(x=df.index, y=df[f'sma{w}'], name=f"SMA{w}", line=dict(color=COLORS[f'sma{w}'], width=1)), row=row, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df[f'ema{w}'], name=f"EMA{w}", line=dict(color=COLORS[f'ema{w}'], width=1)), row=row, col=1)
        
        curr_idx = len(df) - 1
        dkj_x, dkj_y = [], []
        for lb in [20, 60, 120]:
            target = curr_idx - lb
            if target >= 0:
                dkj_x.append(df.index[target])
                dkj_y.append(df['close'].iloc[target])
        if dkj_x:
            fig.add_trace(go.Scatter(x=dkj_x, y=dkj_y, mode='markers', name="DKJ", marker=dict(color=COLORS['dkj'], size=8)), row=row, col=1)

    fig.update_layout(title_text=f"量化交易员看板 ({datetime.now().strftime('%Y-%m-%d')})", width=1000, height=800 + 400 * len(indicator_results), template="plotly_white", showlegend=True)
    fig.update_yaxes(scaleanchor="x", scaleratio=1, row=1, col=1)
    fig.update_xaxes(constrain='domain', row=1, col=1)
    fig.write_html("index.html")

def get_ma_status_text(current_val, row):
    mas = {'SMA20': row['sma20'], 'EMA20': row['ema20'], 'SMA60': row['sma60'], 'EMA60': row['ema60'], 'SMA120': row['sma120'], 'EMA120': row['ema120']}
    support_count = sum(1 for v in mas.values() if current_val > v)
    if support_count == 6: return "🚀 **超强多头** (高于所有均线)"
    if support_count == 0: return "🩸 **极度弱势** (低于所有均线)"
    
    sorted_mas = sorted(mas.items(), key=lambda item: item[1])
    floor_ma, ceil_ma = None, None
    for name, val in sorted_mas:
        if current_val > val: floor_ma = name
        else:
            ceil_ma = name
            break
    if floor_ma and ceil_ma: return f"⚖️ **震荡** ({floor_ma} < 现价 < {ceil_ma})"
    return f"⚠️ **均线纠缠** (支撑: {support_count}/6)"

def send_telegram(rrg_data, indicator_results):
    if not TG_BOT_TOKEN or not TG_CHAT_ID: return

    leading = [d['display_name'] for d in rrg_data.values() if d['current_x']>100 and d['current_y']>100]
    improving = [d['display_name'] for d in rrg_data.values() if d['current_x']<100 and d['current_y']>100]
    
    repo = os.environ.get("GITHUB_REPOSITORY", "repo")
    url = f"https://{repo.split('/')[0]}.github.io/{repo.split('/')[1]}/" if "/" in repo else "http://github.com"
    
    lines = [f"🚀 **{datetime.now().strftime('%Y-%m-%d')} 市场雷达**\n"]
    if leading: lines.append(f"🔥 **强势领涨:**\n" + "  " + "\n  ".join(leading))
    if improving: lines.append(f"📈 **蓄势待发:**\n" + "  " + "\n  ".join(improving))
    lines.append("\n" + "-"*15)
    
    for res in indicator_results:
        last_row = res['df'].iloc[-1]
        curr_val = res['latest_value']
        status_text = get_ma_status_text(curr_val, last_row)
        lines.append(f"📊 **{res['meta']['name']}**")
        lines.append(f"现值: `{curr_val:.4f}`")
        lines.append(f"状态: {status_text}")
        lines.append("")

    lines.append(f"🔗 [查看可视化报表]({url})")
    requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage", json={"chat_id": TG_CHAT_ID, "text": "\n".join(lines), "parse_mode": "Markdown"})

def main():
    # 改为调用新的包含合成逻辑的数据获取函数
    df_all = get_data_and_synthesize() 
    if df_all.empty: return

    rrg = calculate_rrg_components(df_all)
    ind = calculate_indicators(INDICATORS, df_all)
    generate_dashboard(rrg, ind)
    send_telegram(rrg, ind)

if __name__ == "__main__":
    main()
