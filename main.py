import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import os
from datetime import datetime

# =================配置区域=================
# 这里是为了未来的灵活性设计的。
# 如果你想加新指标，只需在这个列表中添加字典即可。
INDICATORS = [
    {
        "name": "消费周期风向标 (XLY/XLP)",
        "numerator": "XLY",   # 分子：非必需消费品
        "denominator": "XLP", # 分母：必需消费品
        "description": "上升代表风险偏好增强 (Risk On)，下降代表防御心态 (Risk Off)"
    },
    # 未来可以取消注释添加如下指标：
    # {
    #     "name": "科技 vs 宽基 (QQQ/SPY)",
    #     "numerator": "QQQ",
    #     "denominator": "SPY",
    #     "description": "衡量科技股相对于大盘的强弱"
    # }
]

# Telegram 配置 (从环境变量读取，为了安全)
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")
# =========================================

def get_data_and_calculate(indicators):
    """下载数据并计算比率"""
    results = []
    
    # 收集所有需要下载的 Ticker 以便一次性下载（减少请求次数）
    tickers = set()
    for item in indicators:
        tickers.add(item['numerator'])
        tickers.add(item['denominator'])
    
    print(f"正在下载数据: {tickers} ...")
    # 下载过去 2 年的数据，足以判断中短期趋势
    try:
        data = yf.download(list(tickers), period="2y", auto_adjust=True)['Close']
    except Exception as e:
        print(f"数据下载失败: {e}")
        return []

    for item in indicators:
        try:
            # 计算比率
            ratio_series = data[item['numerator']] / data[item['denominator']]
            
            # 计算简单的 20日和 50日 均线作为辅助参考
            sma20 = ratio_series.rolling(window=20).mean()
            
            results.append({
                "meta": item,
                "data": ratio_series,
                "sma20": sma20,
                "latest_value": ratio_series.iloc[-1],
                "prev_value": ratio_series.iloc[-2],
                "latest_date": ratio_series.index[-1].strftime('%Y-%m-%d')
            })
        except KeyError as e:
            print(f"计算 {item['name']} 失败，可能是数据缺失: {e}")
    
    return results

def generate_plot(results):
    """生成交互式 HTML 图表"""
    # 创建子图，如果有多个指标，会垂直排列
    fig = make_subplots(
        rows=len(results), cols=1,
        subplot_titles=[item['meta']['name'] for item in results],
        vertical_spacing=0.1
    )

    for idx, res in enumerate(results):
        row = idx + 1
        # 添加比率线
        fig.add_trace(
            go.Scatter(x=res['data'].index, y=res['data'], name=f"{res['meta']['name']} Ratio",
                       line=dict(color='blue', width=2)),
            row=row, col=1
        )
        # 添加 SMA20 辅助线
        fig.add_trace(
            go.Scatter(x=res['sma20'].index, y=res['sma20'], name="SMA 20",
                       line=dict(color='orange', width=1, dash='dash')),
            row=row, col=1
        )

    fig.update_layout(
        title_text=f"市场情绪监控看板 (生成于 {datetime.now().strftime('%Y-%m-%d')})",
        height=400 * len(results), # 根据图表数量动态调整高度
        showlegend=True,
        template="plotly_white"
    )
    
    # 保存为 HTML 文件
    fig.write_html("index.html")
    print("图表已生成: index.html")

def send_telegram_alert(results):
    """发送 Telegram 摘要"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("未配置 Telegram Token，跳过发送。")
        return

    # 获取 GitHub Pages 链接 (假设你的仓库名格式正确)
    repo_name = os.environ.get("GITHUB_REPOSITORY", "your_repo")
    page_url = f"https://{repo_name.split('/')[0]}.github.io/{repo_name.split('/')[1]}/"

    message_lines = [f"📅 **{datetime.now().strftime('%Y-%m-%d')} 交易员日报**\n"]
    
    for res in results:
        name = res['meta']['name']
        val = res['latest_value']
        prev = res['prev_value']
        change = (val - prev) / prev * 100
        icon = "⬆️" if change > 0 else "⬇️"
        
        message_lines.append(f"📊 **{name}**")
        message_lines.append(f"当前值: {val:.4f} ({icon} {change:.2f}%)")
        message_lines.append(f"_{res['meta']['description']}_\n")

    message_lines.append(f"🔗 [查看交互式图表]({page_url})")
    
    msg = "\n".join(message_lines)
    
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown"
    }
    
    resp = requests.post(url, json=payload)
    print(f"Telegram 推送结果: {resp.status_code}")

def main():
    results = get_data_and_calculate(INDICATORS)
    if results:
        generate_plot(results)
        send_telegram_alert(results)
    else:
        print("无数据生成，流程结束。")

if __name__ == "__main__":
    main()
