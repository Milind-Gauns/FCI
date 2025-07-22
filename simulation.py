import streamlit as st 
import pandas as pd
import plotly.express as px
from io import BytesIO
import math
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

# ————————————————————————————————
# Inline simulation logic (CG→LG + LG→FPS)
# ————————————————————————————————
def run_simulation(settings, lgs, fps, vehicles):
    # Phase 1: CG → LG pre‑dispatch
    # --------------------------------
    # Read LG daily requirements & capacities
    DEFAULT_FILE = "distribution_dashboard_template.xlsx"
    req = pd.read_excel(DEFAULT_FILE, sheet_name="LG_Daily_Req").fillna(0)
    cap_df = pd.read_excel(DEFAULT_FILE, sheet_name="LG_Capacity")
    capacity = dict(zip(cap_df['LG_ID'], cap_df['Capacity_tons']))

    req_pivot = req.pivot_table(
        index='LG_ID', columns='Day',
        values='Daily_Requirement_tons',
        aggfunc='sum', fill_value=0
    )

    NUM_CG_VEHICLES   = 30
    CG_VEHICLE_CAP    = 11.5
    CG_TOTAL_DAYS     = 30
    CG_MAX_PRE_DAYS   = 30

    def free_room(stock, lg): 
        return max(0.0, capacity[lg] - stock[lg])

    def can_meet_all(pre_days):
        start = 1 - pre_days
        stock = {lg: 0.0 for lg in req_pivot.index}
        for day in range(start, CG_TOTAL_DAYS+1):
            trips = NUM_CG_VEHICLES
            if day >= 1:
                for lg in stock:
                    need = max(0, req_pivot.at[lg, day] - stock[lg])
                    room = free_room(stock, lg)
                    dl = min(need, room)
                    used = min(trips, math.ceil(dl/CG_VEHICLE_CAP))
                    stock[lg] += used * CG_VEHICLE_CAP
                    trips -= used
                    if stock[lg] + 1e-6 < req_pivot.at[lg, day]:
                        return False
            # pre‑stock
            if trips > 0:
                future = {
                    lg: max(0, sum(req_pivot.at[lg, d] for d in range(max(1, day+1), CG_TOTAL_DAYS+1)) - stock[lg])
                    for lg in stock
                }
                cand = [lg for lg, fu in future.items() if fu>1e-6 and free_room(stock,lg)>1e-6]
                idx = 0
                while trips>0 and cand:
                    lg = cand[idx%len(cand)]
                    dl = min(CG_VEHICLE_CAP, future[lg], free_room(stock,lg))
                    if dl>1e-6:
                        stock[lg] += CG_VEHICLE_CAP
                        future[lg] = max(0, future[lg]-CG_VEHICLE_CAP)
                        trips -= 1
                    if future[lg]<1e-6 or free_room(stock,lg)<1e-6:
                        cand.remove(lg); idx -= 1
                    idx += 1
            if day >= 1:
                for lg in stock:
                    stock[lg] = max(0, stock[lg] - req_pivot.at[lg, day])
        return True

    for x in range(CG_MAX_PRE_DAYS+1):
        if can_meet_all(x):
            pre_days = x
            break
    else:
        raise RuntimeError("Cannot meet LG demand within pre‑days limit")

    start_day = 1 - pre_days
    stock = {lg:0.0 for lg in req_pivot.index}
    cg_records = []

    for day in range(start_day, CG_TOTAL_DAYS+1):
        trips = NUM_CG_VEHICLES
        vids = list(range(1, NUM_CG_VEHICLES+1))
        if day >= 1:
            for lg in sorted(req_pivot.index, key=lambda l: -(req_pivot.at[l,day] - stock[l])):
                need = max(0, req_pivot.at[lg,day] - stock[lg])
                room = free_room(stock,lg)
                dl = min(need, room)
                while trips>0 and dl>1e-6:
                    vid = vids.pop(0)
                    qty = min(dl, CG_VEHICLE_CAP)
                    cg_records.append({"Day":day,"Vehicle_ID":vid,"LG_ID":lg,"Quantity_tons":qty})
                    stock[lg] += qty; trips -= 1; dl -= qty
                if trips==0: break
        if trips>0:
            future = {
                lg: max(0, sum(req_pivot.at[lg, d] for d in range(max(1,day+1), CG_TOTAL_DAYS+1)) - stock[lg])
                for lg in stock
            }
            cand = [lg for lg, fu in future.items() if fu>1e-6 and free_room(stock,lg)>1e-6]
            idx = 0
            while trips>0 and cand:
                lg = cand[idx%len(cand)]
                dl = min(CG_VEHICLE_CAP, future[lg], free_room(stock,lg))
                if dl>1e-6:
                    vid = vids.pop(0)
                    qty = min(dl, CG_VEHICLE_CAP)
                    cg_records.append({"Day":day,"Vehicle_ID":vid,"LG_ID":lg,"Quantity_tons":qty})
                    stock[lg] += qty; trips -= 1; future[lg] -= qty
                if future[lg]<1e-6 or free_room(stock,lg)<1e-6:
                    cand.remove(lg); idx-=1
                idx+=1
        if day>=1:
            for lg in stock:
                stock[lg]=max(0, stock[lg]-req_pivot.at[lg,day])

    dispatch_cg_df = pd.DataFrame(cg_records)

    # Phase 2: LG → FPS dynamic dispatch
    # -----------------------------------
    fps2 = fps.copy()
    fps2["Daily_Demand_tons"] = fps2["Monthly_Demand_tons"]/30.0
    default_lead = float(settings.query("Parameter=='Default_Lead_Time_days'")["Value"].iloc[0])
    fps2["Lead_Time_days"] = fps2["Lead_Time_days"].fillna(default_lead)
    fps2["Reorder_Threshold_tons"] = fps2["Daily_Demand_tons"] * fps2["Lead_Time_days"]

    # map Linked_LG_ID → LG_ID if needed
    if "Linked_LG_ID" in fps2.columns:
        name_to_id = {n.strip().lower():i for n,i in zip(lgs["LG_Name"], lgs["LG_ID"])}
        fps2["LG_ID"] = fps2["Linked_LG_ID"].str.lower().map(name_to_id)

    lg_stock2  = dict(zip(lgs["LG_ID"], lgs["Initial_Allocation_tons"]))
    fps_stock2 = {fid:0.0 for fid in fps2["FPS_ID"]}

    # vehicle mapping
    trips_per = int(settings.query("Parameter=='Max_Trips_Per_Vehicle_Per_Day'")["Value"].iloc[0])
    veh = vehicles.copy()
    if "Mapped_LG_IDs" in veh.columns:
        veh["Mapped_LGs_List"] = veh["Mapped_LG_IDs"].apply(lambda s:[int(x) for x in str(s).split(",") if x.strip().isdigit()])
    else:
        veh["Mapped_LGs_List"] = [list(lgs["LG_ID"]) for _ in veh.index]
    veh["Capacity"] = veh.get("Capacity_tons", CG_VEHICLE_CAP).fillna(CG_VEHICLE_CAP)

    lgp_records = []
    stock_records = []

    for day in range(1, CG_TOTAL_DAYS+1):
        # consume FPS demand
        for _,r in fps2.iterrows():
            fid = r["FPS_ID"]
            fps_stock2[fid] = max(0, fps_stock2[fid] - r["Daily_Demand_tons"])
        # compute needs
        needs=[]
        for _,r in fps2.iterrows():
            fid, lgid = r["FPS_ID"], int(r["LG_ID"])
            cur, thr = fps_stock2[fid], r["Reorder_Threshold_tons"]
            if cur <= thr:
                avail = lg_stock2.get(lgid,0.0)
                space = r["Max_Capacity_tons"]-cur
                qty = min(avail, space)
                if qty>0:
                    urg = (thr-cur)/r["Daily_Demand_tons"]
                    needs.append((urg,fid,lgid,qty))
        needs.sort(reverse=True,key=lambda x:x[0])
        veh["Trips_Used"] = 0
        for _,fid,lgid,need in needs:
            cand = veh[veh["Mapped_LGs_List"].apply(lambda lst:lgid in lst)]
            cand = cand[cand["Trips_Used"]<trips_per]
            if cand.empty: continue
            shared = cand[cand["Mapped_LGs_List"].apply(len)>1]
            truck = shared.iloc[0] if not shared.empty else cand.iloc[0]
            vid, capv = truck["Vehicle_ID"], truck["Capacity"]
            send = min(capv, need, lg_stock2[lgid])
            if send<=0: continue
            lgp_records.append({"Day":day,"Vehicle_ID":vid,"LG_ID":lgid,"FPS_ID":fid,"Quantity_tons":send})
            lg_stock2[lgid]-=send; fps_stock2[fid]+=send
            veh.loc[veh.Vehicle_ID==vid,"Trips_Used"] += 1
        # record stocks
        for lgid,st in lg_stock2.items():
            stock_records.append({"Day":day,"Entity_Type":"LG","Entity_ID":lgid,"Stock_Level_tons":st})
        for fid,st in fps_stock2.items():
            stock_records.append({"Day":day,"Entity_Type":"FPS","Entity_ID":fid,"Stock_Level_tons":st})

    dispatch_lg_df    = pd.DataFrame(lgp_records)
    stock_levels_df   = pd.DataFrame(stock_records)

    return dispatch_cg_df, dispatch_lg_df, stock_levels_df


# ————————————————————————————————
# 1. Page config
# ————————————————————————————————
st.set_page_config(page_title="Grain Distribution Dashboard", layout="wide")

# ————————————————————————————————
# 2. Excel export helper
# ————————————————————————————————
def to_excel(df):
    buf = BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()

# ————————————————————————————————
# 3. Load & cache defaults
# ————————————————————————————————
DEFAULT_FILE = "distribution_dashboard_template.xlsx"

@st.cache_data
def load_defaults():
    xlsx = pd.ExcelFile(DEFAULT_FILE)
    settings = pd.read_excel(xlsx, sheet_name="Settings")
    default_lgs = pd.read_excel(xlsx, sheet_name="LGs")
    default_fps = pd.read_excel(xlsx, sheet_name="FPS")
    if "Vehicles" in xlsx.sheet_names:
        default_veh = pd.read_excel(xlsx, sheet_name="Vehicles")
    else:
        default_veh = pd.DataFrame(columns=["Vehicle_ID","Capacity_tons","Mapped_LG_IDs"])
    return settings, default_lgs, default_fps, default_veh

settings, default_lgs, default_fps, default_veh = load_defaults()

# ————————————————————————————————
# 4. Upload / download master data
# ————————————————————————————————
st.sidebar.subheader("📁 Edit Master Data")
def make_excel(dfs):
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        for name, df in dfs.items():
            df.to_excel(w, sheet_name=name, index=False)
    return buf.getvalue()

# LGs
st.sidebar.markdown("**LGs**")
xls_lg = make_excel({"LGs": default_lgs})
st.sidebar.download_button("Download LGs", xls_lg, "LGs.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
up = st.sidebar.file_uploader("Upload LGs", type=["xlsx","csv"], key="lg")
if up:
    lgs = pd.read_csv(up) if up.name.lower().endswith(".csv") else pd.read_excel(up, sheet_name="LGs")
else:
    lgs = default_lgs.copy()

# FPS
st.sidebar.markdown("**FPS**")
xls_fps = make_excel({"FPS": default_fps})
st.sidebar.download_button("Download FPS", xls_fps, "FPS.xlsx","application/vnd.openxmlformats-officedocument-spreadsheetml.sheet")
up = st.sidebar.file_uploader("Upload FPS", type=["xlsx","csv"], key="fps")
if up:
    fps = pd.read_csv(up) if up.name.lower().endswith(".csv") else pd.read_excel(up, sheet_name="FPS")
else:
    fps = default_fps.copy()

# Vehicles
st.sidebar.markdown("**Vehicles**")
xls_veh = make_excel({"Vehicles": default_veh})
st.sidebar.download_button("Download Vehicles", xls_veh, "Vehicles.xlsx","application/vnd.openxmlformats-officedocument-spreadsheetml.sheet")
up = st.sidebar.file_uploader("Upload Vehicles", type=["xlsx","csv"], key="veh")
if up:
    vehicles = pd.read_csv(up) if up.name.lower().endswith(".csv") else pd.read_excel(up, sheet_name="Vehicles")
else:
    vehicles = default_veh.copy()

# ————————————————————————————————
# 5. Run Simulation
# ————————————————————————————————
dispatch_cg  = pd.DataFrame()
dispatch_lg  = pd.DataFrame()
stock_levels = pd.DataFrame()

if st.sidebar.button("▶️ Run Simulation"):
    with st.spinner("Running simulation…"):
        dispatch_cg, dispatch_lg, stock_levels = run_simulation(settings, lgs, fps, vehicles)
    st.sidebar.success("Simulation complete!")
else:
    st.sidebar.info("Upload masters and click ▶️ to run.")

# fallback to static if empty
if dispatch_lg.empty:
    dispatch_cg  = pd.read_excel(DEFAULT_FILE, sheet_name="CG_to_LG_Dispatch")
    dispatch_lg  = pd.read_excel(DEFAULT_FILE, sheet_name="LG_to_FPS_Dispatch")
    stock_levels = pd.read_excel(DEFAULT_FILE, sheet_name="Stock_Levels")

# ————————————————————————————————
# 6. Dashboard logic (compute metrics, filters, tabs, charts, KPIs)
# ————————————————————————————————
# … (insert your existing code here, referencing dispatch_cg, dispatch_lg, stock_levels, lgs, fps) …
