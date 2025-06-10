import streamlit as st
import pandas as pd
import plotly.express as px
from io import BytesIO
import math
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

# 1. Page config
st.set_page_config(page_title="Grain Distribution Dashboard", layout="wide")

# 2. Helper to export DataFrame to Excel
def to_excel(df):
    buf = BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()

# 3. Load & cache data
@st.cache_data
def load_data(fn):
    settings     = pd.read_excel(fn, sheet_name="Settings")
    dispatch_cg  = pd.read_excel(fn, sheet_name="CG_to_LG_Dispatch")
    dispatch_lg  = pd.read_excel(fn, sheet_name="LG_to_FPS_Dispatch")
    stock_levels = pd.read_excel(fn, sheet_name="Stock_Levels")
    lgs          = pd.read_excel(fn, sheet_name="LGs")
    fps          = pd.read_excel(fn, sheet_name="FPS")
    return settings, dispatch_cg, dispatch_lg, stock_levels, lgs, fps

settings, dispatch_cg, dispatch_lg, stock_levels, lgs, fps = load_data("distribution_dashboard_template.xlsx")

# 4. Compute core metrics
DAYS      = int(settings.query("Parameter=='Distribution_Days'")["Value"].iloc[0])
TRUCK_CAP = float(settings.query("Parameter=='Vehicle_Capacity_tons'")["Value"].iloc[0])
MAX_TRIPS = int(settings.query("Parameter=='Vehicles_Total'")["Value"].iloc[0]) * \
            int(settings.query("Parameter=='Max_Trips_Per_Vehicle_Per_Day'")["Value"].iloc[0])
DAILY_CAP = MAX_TRIPS * TRUCK_CAP

# Pre-dispatch offset X
dt = dispatch_cg.groupby("Dispatch_Day")["Quantity_tons"].sum()
cum, adv = 0, []
for d in range(1, DAYS+1):
    cum += dt.get(d,0)
    over = (cum - DAILY_CAP*d)/DAILY_CAP
    adv.append(math.ceil(over) if over>0 else 0)
X = max(adv); MIN_DAY=1-X; MAX_DAY=DAYS

# Summaries
day_totals_cg = dispatch_cg.groupby("Dispatch_Day")["Quantity_tons"].sum().reset_index().rename(columns={"Dispatch_Day":"Day"})
day_totals_lg = dispatch_lg.groupby("Day")["Quantity_tons"].sum().reset_index()
veh_usage     = dispatch_lg.groupby("Day")["Vehicle_ID"].nunique().reset_index(name="Trips_Used")
veh_usage["Max_Trips"] = MAX_TRIPS

# LG stock pivot (auto-detect column name)
entity_col = next(c for c in stock_levels.columns if c.lower().replace("_"," ")=="entity type")
lg_stock = (
    stock_levels[stock_levels[entity_col]=="LG"]
    .pivot_table(index="Day", columns="Entity_ID", values="Stock_Level_tons", aggfunc="first")
    .fillna(method="ffill")
)

# FPS stock & at-risk
fps_stock = (
    stock_levels[stock_levels[entity_col]=="FPS"]
    .rename(columns={"Entity_ID":"FPS_ID"})
    .merge(fps[["FPS_ID","Reorder_Threshold_tons"]], on="FPS_ID", how="left")
)
fps_stock["At_Risk"] = fps_stock["Stock_Level_tons"] <= fps_stock["Reorder_Threshold_tons"]

total_plan = day_totals_lg.Quantity_tons.sum()

# 5. Sidebar filters & Quick KPIs
st.title("🚛 Grain Distribution Dashboard")
with st.sidebar:
    st.header("Filters")
    day_range = st.slider("Dispatch Window (days)", MIN_DAY, MAX_DAY, (MIN_DAY, MAX_DAY), format="%d")
    st.subheader("Select LGs")
    cols = st.columns(4)
    lg_ids   = lgs["LG_ID"].astype(int).tolist()
    lg_names = lgs["LG_Name"].tolist()
    selected_lgs = []
    for i, name in enumerate(lg_names):
        if cols[i%4].checkbox(name, True, key=f"lg_{i}"):
            selected_lgs.append(lg_ids[i])
    st.markdown("---")
    cg_sel = day_totals_cg.query("Day>=@day_range[0] & Day<=@day_range[1]")["Quantity_tons"].sum()
    lg_sel = day_totals_lg.query("Day>=1 & Day<=@day_range[1]")["Quantity_tons"].sum()
    st.header("Quick KPIs")
    st.metric("CG→LG Total (t)", f"{cg_sel:,.1f}")
    st.metric("LG→FPS Total (t)", f"{lg_sel:,.1f}")
    st.metric("Max Trucks/Day",     f"{MAX_TRIPS}")
    st.metric("Truck Capacity (t)", f"{TRUCK_CAP}")

# 6. Tabs
tabs = st.tabs([
    "CG→LG Dispatch", "LG→FPS Dispatch",
    "LG Details",     "FPS Report",
    "FPS At-Risk",    "FPS Data",
    "Downloads",      "Metrics"
])

# Tab0: CG→LG Overview
with tabs[0]:
    st.subheader("CG → LG Dispatch")
    df1 = day_totals_cg.query("Day>=@day_range[0] & Day<=@day_range[1]")
    fig1=px.bar(df1, x="Day", y="Quantity_tons", text="Quantity_tons")
    fig1.update_traces(texttemplate="%{text:.1f}t", textposition="outside")
    st.plotly_chart(fig1, use_container_width=True)

# Tab1: LG→FPS Overview
with tabs[1]:
    st.subheader("LG → FPS Dispatch")
    df2 = day_totals_lg.query("Day>=1 & Day<=@day_range[1]")
    fig2=px.bar(df2, x="Day", y="Quantity_tons", text="Quantity_tons")
    fig2.update_traces(texttemplate="%{text:.1f}t", textposition="outside")
    st.plotly_chart(fig2, use_container_width=True)

# Tab2: LG Details
with tabs[2]:
    st.subheader("Local Godown Details")
    # Build selection strings
    lg_options = [f"{row.LG_ID} – {row.LG_Name}" for _, row in lgs.iterrows()]
    lg_choice  = st.selectbox("Choose an LG", options=lg_options)
    lg_id_str  = lg_choice.split(" – ")[0]
    lg_id      = int(lg_id_str)

    # 1) Capacity
    cap = lgs.set_index("LG_ID").loc[lg_id,"Storage_Capacity_tons"]
    st.markdown(f"**Capacity:** {cap} t")

    # 2) CG→LG receipts
    rec = (
        dispatch_cg[dispatch_cg.LG_ID == lg_id]
        .groupby("Dispatch_Day")["Quantity_tons"]
        .sum().reset_index()
        .rename(columns={"Dispatch_Day":"Day","Quantity_tons":"Received"})
    )
    st.line_chart(rec.set_index("Day")["Received"], height=200)
    st.metric("Total Received", f"{rec.Received.sum():,.1f} t")

    # 3) Stock timeline
    st.line_chart(lg_stock[lg_id].rename("Stock (t)"), height=200)

    # 4) End-day fill %
    stock_end = lg_stock.loc[day_range[1], lg_id]
    pct_fill  = stock_end / cap * 100
    st.metric("End-day Fill %", f"{pct_fill:.1f}%")

    # 5) Outbound dispatch
    out = dispatch_lg[dispatch_lg.LG_ID == lg_id]
    st.metric("Dispatched to FPS", f"{out.Quantity_tons.sum():,.1f} t")
    st.metric("Trips Made", f"{out.Vehicle_ID.nunique()}")

    # 6) FPS under this LG
    fps_under = fps[ lgs.loc[lgs['LG_Name'] == fps.Linked_LG_ID, 'LG_ID'].values[0] == lg_id]
    fps_summary = (
        out.groupby("FPS_ID")["Quantity_tons"]
        .sum().reset_index(name="Dispatched_tons")
        .merge(fps_under[["FPS_ID","FPS_Name"]], on="FPS_ID", how="left")
    )
    st.dataframe(fps_summary, use_container_width=True)

    # 7) FPS At-Risk timeline
    at_lg   = fps_stock[fps_stock.FPS_ID.isin(fps_under.FPS_ID)]
    risk_ts = (
        at_lg.groupby("Day")["At_Risk"]
        .sum().reset_index(name="At_Risk_Count")
    )
    st.line_chart(risk_ts.set_index("Day")["At_Risk_Count"], height=200)



# Tab3: FPS Report
with tabs[3]:
    st.subheader("FPS-wise Dispatch Details")
    mask = (dispatch_lg.Day>=1)&(dispatch_lg.Day<=day_range[1])&(dispatch_lg.LG_ID.isin(selected_lgs))
    fps_df = dispatch_lg[mask]
    report = (fps_df.groupby("FPS_ID")
        .agg(Total_Dispatched_tons=pd.NamedAgg("Quantity_tons","sum"),
             Trips_Count=pd.NamedAgg("Vehicle_ID","nunique"),
             Vehicle_IDs=pd.NamedAgg("Vehicle_ID",lambda vs: ",".join(map(str,sorted(set(vs))))))
        .reset_index()
        .merge(fps[["FPS_ID","FPS_Name"]],on="FPS_ID",how="left")
        .sort_values("Total_Dispatched_tons",ascending=False))
    st.dataframe(report,use_container_width=True)

# Tab4: FPS At-Risk
with tabs[4]:
    st.subheader("FPS At-Risk List")
    arf = fps_stock[(fps_stock.Day>=1)&(fps_stock.Day<=day_range[1])&(fps_stock.FPS_ID.isin(report.FPS_ID))&(fps_stock.At_Risk)]
    st.dataframe(arf[["Day","FPS_ID","Stock_Level_tons","Reorder_Threshold_tons"]],use_container_width=True)
    st.download_button("Download At-Risk Excel", to_excel(arf), "fps_at_risk.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# Tab5: FPS Data
with tabs[5]:
    st.subheader("FPS Stock & Upcoming Receipts")
    end_day = min(day_range[1], DAYS)
    fps_data=[]
    for fid in report.FPS_ID:
        s = fps_stock[(fps_stock.FPS_ID==fid)&(fps_stock.Day==end_day)]["Stock_Level_tons"]
        stock_now = float(s.iloc[0]) if not s.empty else 0.0
        fut = dispatch_lg[(dispatch_lg.FPS_ID==fid)&(dispatch_lg.LG_ID.isin(selected_lgs))&(dispatch_lg.Day> end_day)]["Day"]
        nd = int(fut.min()) if not fut.empty else None
        dt = nd - end_day if nd else None
        fps_data.append({"FPS_ID":fid,"Current_Stock_tons":stock_now,"Next_Receipt_Day":nd,"Days_To_Receipt":dt})
    df5=pd.DataFrame(fps_data)
    st.dataframe(df5,use_container_width=True)
    st.download_button("Download FPS Data Excel", to_excel(df5),"fps_data.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# Tab6: Downloads
with tabs[6]:
    st.subheader("Download FPS Report")
    st.download_button("Excel", to_excel(report), "FPS_Report.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    pdf_buf=BytesIO()
    with PdfPages(pdf_buf) as pdf:
        fig,ax=plt.subplots(figsize=(8,len(report)*0.3+1));ax.axis('off')
        tbl=ax.table(cellText=report.values,colLabels=report.columns,loc='center');tbl.auto_set_font_size(False);tbl.set_fontsize(10)
        pdf.savefig(fig,bbox_inches='tight')
    st.download_button("Download PDF",pdf_buf.getvalue(),"FPS_Report.pdf","application/pdf")

# Tab7: Metrics
with tabs[7]:
    st.subheader("Key Performance Indicators")
    sel_days = day_range[1] - max(day_range[0],1) + 1
    avg_cg   = cg_sel/sel_days if sel_days>0 else 0
    avg_lg   = lg_sel/sel_days if sel_days>0 else 0
    avg_tr   = veh_usage[veh_usage.Day.between(1,day_range[1])]["Trips_Used"].mean()
    pct_f    = (avg_tr/MAX_TRIPS)*100 if MAX_TRIPS else 0
    lg_on    = lg_stock.loc[end_day, selected_lgs].sum()
    fps_on   = fps_stock[fps_stock.Day==end_day]["Stock_Level_tons"].sum()
    lg_cap   = lgs[lgs.LG_ID.isin(map(str,selected_lgs))]["Storage_Capacity_tons"].sum()
    pct_lg   = (lg_on/lg_cap)*100 if lg_cap else 0
    fps_zero = fps_stock[(fps_stock.Day==end_day)&(fps_stock.Stock_Level_tons==0)]["FPS_ID"].nunique()
    fps_r    = fps_stock[(fps_stock.Day==end_day)&(fps_stock.At_Risk)]["FPS_ID"].nunique()
    disp     = day_totals_lg[day_totals_lg.Day<=end_day]["Quantity_tons"].sum()
    pct_p    = (disp/total_plan)*100 if total_plan else 0
    rem      = total_plan-disp; days_r=math.ceil(rem/DAILY_CAP) if DAILY_CAP else None
    KP = [
        ("CG→LG (t)",f"{cg_sel:,.1f}"),
        ("LG→FPS (t)",f"{lg_sel:,.1f}"),
        ("Avg CG→LG",f"{avg_cg:,.1f}"),
        ("Avg LG→FPS",f"{avg_lg:,.1f}"),
        ("Avg Trips",f"{avg_tr:.1f}"),
        ("% Fleet Util",f"{pct_f:.1f}%"),
        ("LG Stock",f"{lg_on:,.1f}"),
        ("FPS Stock",f"{fps_on:,.1f}"),
        ("% LG Fill",f"{pct_lg:.1f}%"),
        ("FPS Zero",f"{fps_zero}"),
        ("FPS Risk",f"{fps_r}"),
        ("% Plan Comp",f"{pct_p:.1f}%"),
        ("Days Left",f"{days_r}")
    ]
    cols=st.columns(3)
    for i,(l,v) in enumerate(KP): cols[i%3].metric(l,v)
