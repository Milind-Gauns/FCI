import streamlit as st
import pandas as pd
import plotly.express as px
from io import BytesIO
import math

# ————————————————————————————————
# 1. Load & Cache Data
# ————————————————————————————————
@st.cache_data
def load_data(fn):
    settings     = pd.read_excel(fn, sheet_name="Settings")
    dispatch_cg  = pd.read_excel(fn, sheet_name="CG_to_LG_Dispatch")
    dispatch_lg  = pd.read_excel(fn, sheet_name="LG_to_FPS_Dispatch")
    stock_levels = pd.read_excel(fn, sheet_name="Stock_Levels")
    lgs          = pd.read_excel(fn, sheet_name="LGs")
    fps          = pd.read_excel(fn, sheet_name="FPS")
    return settings, dispatch_cg, dispatch_lg, stock_levels, lgs, fps

DATA_FILE = "distribution_dashboard_template.xlsx"
settings, dispatch_cg, dispatch_lg, stock_levels, lgs, fps = load_data(DATA_FILE)

# ————————————————————————————————
# 2. Compute Metrics
# ————————————————————————————————
DAYS      = int(settings.query("Parameter=='Distribution_Days'")["Value"].iloc[0])
MAX_TRIPS = int(settings.query("Parameter=='Vehicles_Total'")["Value"].iloc[0]) * \
            int(settings.query("Parameter=='Max_Trips_Per_Vehicle_Per_Day'")["Value"].iloc[0])
TRUCK_CAP = float(settings.query("Parameter=='Vehicle_Capacity_tons'")["Value"].iloc[0])
DAILY_CAP = MAX_TRIPS * TRUCK_CAP

# Daily dispatch totals
day_totals_cg = (dispatch_cg
    .groupby("Dispatch_Day")["Quantity_tons"]
    .sum().reset_index().rename(columns={"Dispatch_Day":"Day"}))
day_totals_lg = (dispatch_lg
    .groupby("Day")["Quantity_tons"]
    .sum().reset_index())

# Vehicle utilization per day
veh_usage = (dispatch_lg
    .groupby("Day")["Vehicle_ID"]
    .nunique().reset_index(name="Trips_Used"))
veh_usage["Max_Trips"] = MAX_TRIPS

# LG stock over time
lg_stock = (stock_levels[stock_levels.Entity_Type=="LG"]
    .pivot(index="Day", columns="Entity_ID", values="Stock_Level_tons")
    .fillna(method="ffill"))

# FPS stock & at-risk
fps_stock = (stock_levels[stock_levels.Entity_Type=="FPS"]
    .merge(fps[["FPS_ID","Reorder_Threshold_tons"]],
           left_on="Entity_ID", right_on="FPS_ID"))
fps_stock["At_Risk"] = fps_stock.Stock_Level_tons <= fps_stock.Reorder_Threshold_tons

# Total 30-day plan
total_plan = day_totals_lg.Quantity_tons.sum()

# ————————————————————————————————
# 3. Layout & Filters
# ————————————————————————————————
st.set_page_config(page_title="Grain Distribution Dashboard", layout="wide")
st.title("🚛 Grain Distribution Dashboard")

with st.sidebar:
    st.header("Filters")
    day_range = st.slider("Day Range", 1, DAYS, (1, DAYS))
    st.subheader("Select LGs")
    cols = st.columns(4)
    selected_lgs = []
    for i, lg in enumerate(lg_stock.columns):
        if cols[i % 4].checkbox(f"{lg}", value=True, key=f"lg_{lg}"):
            selected_lgs.append(lg)
    st.markdown("---")
    # Day-wise KPIs per sidebar if desired (optional)
    st.header("Quick KPIs")
    cg_sel = day_totals_cg.query("Day>=@day_range[0] & Day<=@day_range[1]")["Quantity_tons"].sum()
    lg_sel = day_totals_lg.query("Day>=@day_range[0] & Day<=@day_range[1]")["Quantity_tons"].sum()
    st.metric("CG→LG Total (t)", f"{cg_sel:,.1f}")
    st.metric("LG→FPS Total (t)", f"{lg_sel:,.1f}")

# Tabs
tab1, tab2, tab3 = st.tabs(["Overview", "FPS Report", "Metrics"])

# ————————————————————————————————
# 4. Tab 1: Overview
# ————————————————————————————————
with tab1:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("CG → LG Dispatch Trend")
        df1 = day_totals_cg.query("Day>=@day_range[0] & Day<=@day_range[1]")
        fig1 = px.line(df1, x="Day", y="Quantity_tons", markers=True,
                       labels={"Quantity_tons":"Tons"})
        st.plotly_chart(fig1, use_container_width=True)
    with c2:
        st.subheader("LG → FPS Dispatch Trend")
        df2 = day_totals_lg.query("Day>=@day_range[0] & Day<=@day_range[1]")
        fig2 = px.line(df2, x="Day", y="Quantity_tons", markers=True,
                       labels={"Quantity_tons":"Tons"})
        st.plotly_chart(fig2, use_container_width=True)

    c3, c4 = st.columns(2)
    with c3:
        st.subheader("Vehicle Utilization")
        vu = veh_usage.query("Day>=@day_range[0] & Day<=@day_range[1]")
        fig3 = px.area(vu, x="Day", y=["Trips_Used","Max_Trips"],
                       labels={"value":"Trips","variable":"Metric"})
        st.plotly_chart(fig3, use_container_width=True)
    with c4:
        st.subheader("LG Stock Levels")
        stock_slice = lg_stock.loc[day_range[0]:day_range[1], selected_lgs]
        fig4 = px.line(stock_slice, labels={"value":"Stock (t)","Day":"Day"})
        st.plotly_chart(fig4, use_container_width=True)

# ————————————————————————————————
# 5. Tab 2: FPS Report
# ————————————————————————————————
with tab2:
    st.subheader("FPS‐wise Dispatch Details")
    fps_df = dispatch_lg.query("Day>=@day_range[0] & Day<=@day_range[1]")
    report = (
        fps_df.groupby("FPS_ID")
        .agg(
            Total_Dispatched_tons = pd.NamedAgg("Quantity_tons","sum"),
            Trips_Count           = pd.NamedAgg("Vehicle_ID","nunique"),
            Vehicle_IDs           = pd.NamedAgg("Vehicle_ID", lambda vs: ",".join(map(str,sorted(set(vs)))))
        )
        .reset_index()
        .merge(fps[["FPS_ID","FPS_Name"]], on="FPS_ID", how="left")
        .sort_values("Total_Dispatched_tons", ascending=False)
    )
    st.dataframe(report, use_container_width=True)

    def to_excel(df):
        buf = BytesIO()
        df.to_excel(buf, index=False)
        return buf.getvalue()

    st.download_button(
        "📥 Download FPS Report",
        to_excel(report),
        f"FPS_Report_{day_range[0]}to{day_range[1]}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ————————————————————————————————
# 6. Tab 3: Metrics
# ————————————————————————————————
with tab3:
    st.subheader("Key Performance Indicators")
    # compute metrics
    sel_days = day_range[1] - day_range[0] + 1
    avg_daily_cg = cg_sel / sel_days if sel_days else 0
    avg_daily_lg = lg_sel / sel_days if sel_days else 0
    avg_trips    = veh_usage.query("Day>=@day_range[0] & Day<=@day_range[1]")["Trips_Used"].mean()
    pct_fleet    = (avg_trips / MAX_TRIPS)*100 if MAX_TRIPS else 0

    # LG & FPS stock at end day
    end_day = day_range[1]
    lg_onhand  = lg_stock.loc[end_day, selected_lgs].sum()
    # FPS stock sum
    fps_end_stock = fps_stock.query("Day==@end_day")["Stock_Level_tons"].sum()
    # % LG capacity filled
    lg_caps = lgs.set_index("LG_ID").loc[selected_lgs]["Storage_Capacity_tons"].sum()
    pct_lg_filled = (lg_onhand / lg_caps)*100 if lg_caps else 0
    # FPS stock-outs
    fps_zero = fps_stock.query("Day==@end_day & Stock_Level_tons==0")["FPS_ID"].nunique()
    # FPS at-risk
    fps_risk = fps_stock.query("Day==@end_day & At_Risk")["FPS_ID"].nunique()
    # % plan completed
    dispatched_cum = day_totals_lg.query("Day<=@end_day")["Quantity_tons"].sum()
    pct_plan = (dispatched_cum/total_plan)*100 if total_plan else 0
    # days remaining
    remaining_t = total_plan - dispatched_cum
    days_rem = math.ceil(remaining_t / DAILY_CAP) if DAILY_CAP else None

    # Display cards in grid
    metrics = [
        ("Total CG→LG (t)", f"{cg_sel:,.1f}"),
        ("Total LG→FPS (t)", f"{lg_sel:,.1f}"),
        ("Avg Daily CG→LG (t/d)", f"{avg_daily_cg:,.1f}"),
        ("Avg Daily LG→FPS (t/d)", f"{avg_daily_lg:,.1f}"),
        ("Avg Trips/Day",       f"{avg_trips:.1f}"),
        ("% Fleet Utilization", f"{pct_fleet:.1f}%"),
        ("LG Stock on Hand (t)",f"{lg_onhand:,.1f}"),
        ("FPS Stock on Hand (t)",f"{fps_end_stock:,.1f}"),
        ("% LG Cap Filled",     f"{pct_lg_filled:.1f}%"),
        ("FPS Stock-Outs",      f"{fps_zero}"),
        ("FPS At-Risk Count",   f"{fps_risk}"),
        ("% Plan Completed",    f"{pct_plan:.1f}%"),
        ("Days Remaining",      f"{days_rem}")
    ]

    cols = st.columns(3)
    for i, (label, val) in enumerate(metrics):
        cols[i%3].metric(label, val)

dl_cg = to_excel(dispatch_cg)
dl_lg = to_excel(dispatch_lg)
st.download_button("Download CG→LG Dispatch", dl_cg, "cg_to_lg.xlsx")
st.download_button("Download LG→FPS Dispatch", dl_lg, "lg_to_fps.xlsx")
