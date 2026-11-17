"""Read-only trade dashboard for archived daily signals."""
import pandas as pd
import streamlit as st

def render_trade_dashboard(list_report_dates, load_daily_report, categories):
    st.header("📊 Trade Dashboard｜台股交易決策中心")
    st.caption("唯讀歷史盤後訊號；不是即時報價、實際成交或投資組合績效。不會執行掃描、下單或修改監控清單。")
    dates = list_report_dates()
    if not dates:
        st.info("尚無每日訊號報表。請先完成盤後掃描。")
        return
    date = st.selectbox("交易報表日期", dates, key="trade_dash_date")
    try:
        report = load_daily_report(date)
    except (OSError, ValueError, KeyError) as exc:
        st.error(f"讀取報表失敗：{exc}")
        return
    if not report:
        st.warning("此日期的報表不存在。")
        return
    st.caption(f"行情日期：{report.get('market_date') or '未提供'} ｜ 報表產生：{report.get('generated_at') or '未提供'}")
    keys = list(categories)
    cols = st.columns(len(keys))
    for col, key in zip(cols, keys):
        col.metric(categories[key], len(report.get(key) or []))
    rows = []
    for key, label in categories.items():
        for item in report.get(key) or []:
            rows.append({
                "類別": label, "代碼": item.get("ticker"), "名稱": item.get("name"),
                "資料日期": item.get("data_date"), "參考收盤價": item.get("close"),
                "最終策略": item.get("action"), "原始判定": item.get("raw_action"),
                "評分": item.get("score"), "參考報酬(%)": item.get("reference_return_pct"),
                "風控原因": "、".join(str(x) for x in (item.get("risk_reasons") or [])),
                "判斷理由": item.get("reason"),
            })
    if not rows:
        st.info("此報表沒有訊號。")
        return
    frame = pd.DataFrame(rows)
    a, b = st.columns([1, 2])
    category = a.selectbox("訊號篩選", ["全部", *categories.values()], key="trade_dash_category")
    query = b.text_input("搜尋股票代碼／名稱", key="trade_dash_query").strip()
    if category != "全部":
        frame = frame[frame["類別"] == category]
    if query:
        frame = frame[frame["代碼"].fillna("").astype(str).str.contains(query, case=False, regex=False) |
                      frame["名稱"].fillna("").astype(str).str.contains(query, case=False, regex=False)]
    st.subheader("訊號明細")
    st.dataframe(frame, use_container_width=True, hide_index=True)
    st.download_button("下載篩選結果 CSV", frame.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"trade_dashboard_{date}.csv", mime="text/csv")
    st.subheader("歷史訊號數量趨勢")
    history = []
    for d in dates[:30]:
        try:
            r = load_daily_report(d)
        except (OSError, ValueError, KeyError):
            continue
        if r:
            history.append({"日期": d, **{label: len(r.get(key) or []) for key, label in categories.items()}})
    if history:
        hist = pd.DataFrame(history).sort_values("日期").set_index("日期")
        st.line_chart(hist)
    st.caption("同一股票可能在同日買入與賣出清單中同時出現；這是訊號事件，不是實際成交。")
