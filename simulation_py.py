import pandas as pd
import math

# Simulation module to generate CG->LG and LG->FPS outputs
def run_simulation(input_source):
    """
    Run the full grain distribution simulation.
    input_source: path or file-like object for raw input Excel with sheets:
        - LG_Daily_Req, LG_Capacity
        - Settings, LGs, FPS, Vehicles
    Returns:
        settings: DataFrame
        dispatch_cg: DataFrame with columns [Dispatch_Day, Vehicle_ID, LG_ID, Quantity_tons]
        dispatch_lg: DataFrame with columns [Day, Vehicle_ID, LG_ID, FPS_ID, Quantity_tons]
        stock_levels: DataFrame with columns [Day, Entity_Type, Entity_ID, Stock_Level_tons]
        lgs: DataFrame
        fps: DataFrame
    """
    # --- CG->LG Simulation ---
    # Read requirements and capacities
    req = pd.read_excel(input_source, sheet_name='LG_Daily_Req').fillna(0)
    cap_df = pd.read_excel(input_source, sheet_name='LG_Capacity')
    capacity = dict(zip(cap_df['LG_ID'], cap_df['Capacity_tons']))
    # Pivot for daily needs
    req_pivot = req.pivot_table(
        index='LG_ID',
        columns='Day',
        values='Daily_Requirement_tons',
        aggfunc='sum',
        fill_value=0
    )
    NUM_VEHICLES     = 30
    VEHICLE_CAPACITY = 11.5
    TOTAL_DAYS       = 30
    MAX_PRE_DAYS     = 30
    def free_room(stock, lg):
        return max(0.0, capacity[lg] - stock[lg])
    def can_meet_all(pre_days):
        start_day = 1 - pre_days
        stock = {lg: 0.0 for lg in req_pivot.index}
        for day in range(start_day, TOTAL_DAYS + 1):
            trips_left = NUM_VEHICLES
            # Serve today's needs
            if day >= 1:
                for lg in stock:
                    need = max(0.0, req_pivot.at[lg, day] - stock[lg])
                    room = free_room(stock, lg)
                    deliver = min(need, room)
                    t = min(trips_left, math.ceil(deliver / VEHICLE_CAPACITY))
                    stock[lg] += t * VEHICLE_CAPACITY
                    trips_left -= t
                    if stock[lg] + 1e-6 < req_pivot.at[lg, day]:
                        return False
            # Pre-stock future demand
            if trips_left > 0:
                future_unmet = {
                    lg: max(0.0, sum(req_pivot.at[lg, d]
                                     for d in range(max(1, day+1), TOTAL_DAYS+1))
                             - stock[lg])
                    for lg in stock
                }
                candidates = [lg for lg, fu in future_unmet.items() if fu > 1e-6 and free_room(stock, lg) > 1e-6]
                idx = 0
                while trips_left > 0 and candidates:
                    lg = candidates[idx % len(candidates)]
                    room = free_room(stock, lg)
                    deliver = min(VEHICLE_CAPACITY, future_unmet[lg], room)
                    if deliver > 1e-6:
                        stock[lg] += VEHICLE_CAPACITY
                        future_unmet[lg] = max(0.0, future_unmet[lg] - VEHICLE_CAPACITY)
                        trips_left -= 1
                    if future_unmet[lg] < 1e-6 or free_room(stock, lg) < 1e-6:
                        candidates.remove(lg)
                        idx -= 1
                    idx += 1
            # Consume
            if day >= 1:
                for lg in stock:
                    stock[lg] = max(0.0, stock[lg] - req_pivot.at[lg, day])
        return True
    # Find minimal advance days
    pre_days = 0
    for x in range(MAX_PRE_DAYS + 1):
        if can_meet_all(x):
            pre_days = x
            break
    # Build CG->LG dispatch records
    start_day = 1 - pre_days
    stock = {lg: 0.0 for lg in req_pivot.index}
    records_cg = []
    for day in range(start_day, TOTAL_DAYS + 1):
        trips_left = NUM_VEHICLES
        vehicle_ids = list(range(1, NUM_VEHICLES + 1))
        # Serve today's needs
        if day >= 1:
            for lg in sorted(req_pivot.index, key=lambda lg: -(req_pivot.at[lg, day] - stock[lg])):
                need = max(0.0, req_pivot.at[lg, day] - stock[lg])
                room = free_room(stock, lg)
                deliver = min(need, room)
                while trips_left > 0 and deliver > 1e-6:
                    vid = vehicle_ids.pop(0)
                    qty = min(deliver, VEHICLE_CAPACITY)
                    records_cg.append({'Dispatch_Day': day, 'Vehicle_ID': vid, 'LG_ID': lg, 'Quantity_tons': qty})
                    stock[lg] += qty
                    trips_left -= 1
                    deliver -= qty
                if trips_left == 0:
                    break
        # Pre-stock
        if trips_left > 0:
            future_unmet = {
                lg: max(0.0, sum(req_pivot.at[lg, d]
                                 for d in range(max(1, day+1), TOTAL_DAYS+1))
                         - stock[lg])
                for lg in stock
            }
            candidates = [lg for lg, fu in future_unmet.items() if fu > 1e-6 and free_room(stock, lg) > 1e-6]
            idx = 0
            while trips_left > 0 and candidates:
                lg = candidates[idx % len(candidates)]
                room = free_room(stock, lg)
                deliver = min(VEHICLE_CAPACITY, future_unmet[lg], room)
                if deliver > 1e-6:
                    vid = vehicle_ids.pop(0)
                    qty = min(deliver, VEHICLE_CAPACITY)
                    records_cg.append({'Dispatch_Day': day, 'Vehicle_ID': vid, 'LG_ID': lg, 'Quantity_tons': qty})
                    stock[lg] += qty
                    trips_left -= 1
                    future_unmet[lg] = max(0.0, future_unmet[lg] - qty)
                if future_unmet[lg] < 1e-6 or free_room(stock, lg) < 1e-6:
                    candidates.remove(lg)
                    idx -= 1
                idx += 1
        # Consume
        if day >= 1:
            for lg in stock:
                stock[lg] = max(0.0, stock[lg] - req_pivot.at[lg, day])
    dispatch_cg = pd.DataFrame(records_cg)

    # --- LG->FPS Simulation ---
    # Read sheets
    settings = pd.read_excel(input_source, sheet_name="Settings")
    lgs      = pd.read_excel(input_source, sheet_name="LGs")
    fps      = pd.read_excel(input_source, sheet_name="FPS")
    vehicles = pd.read_excel(input_source, sheet_name="Vehicles")
    # Compute thresholds
    fps = fps.copy()
    fps["Daily_Demand_tons"] = fps["Monthly_Demand_tons"] / 30.0
    default_lead = float(settings.loc[settings["Parameter"] == "Default_Lead_Time_days", "Value"].iloc[0])
    fps["Lead_Time_days"] = fps["Lead_Time_days"].fillna(default_lead)
    fps["Reorder_Threshold_tons"] = fps["Daily_Demand_tons"] * fps["Lead_Time_days"]
    # Map LG names
    name_to_id = {name.strip().lower(): lg_id for name, lg_id in zip(lgs["LG_Name"], lgs["LG_ID"])}
    fps["LG_ID"] = fps["Linked_LG_ID"].str.strip().str.lower().map(name_to_id)
    # Vehicles mapping
    vehicles = vehicles.copy()
    vehicles["Mapped_LGs_List"] = vehicles["Mapped_LG_IDs"].apply(
        lambda s: [int(x) for x in str(s).split(",") if x.strip().isdigit()]
    )
    vehicles["Capacity"] = vehicles["Capacity_tons"].fillna(
        float(settings.loc[settings["Parameter"] == "Vehicle_Capacity_tons", "Value"].iloc[0])
    )
    days = int(settings.loc[settings["Parameter"] == "Distribution_Days", "Value"].iloc[0])
    max_trips = int(settings.loc[settings["Parameter"] == "Max_Trips_Per_Vehicle_Per_Day", "Value"].iloc[0])
    # Initialize stocks and records
    lg_stock = dict(zip(lgs["LG_ID"], lgs["Initial_Allocation_tons"]))
    fps_stock = {fid: 0.0 for fid in fps["FPS_ID"]}
    dispatch_records = []
    stock_records = []
    # Loop days
    for day in range(1, days+1):
        # Consume FPS demand
        for _, row in fps.iterrows():
            fps_stock[row["FPS_ID"]] = max(0.0, fps_stock[row["FPS_ID"]] - row["Daily_Demand_tons"])
        # Compute needs
        needs = []
        for _, row in fps.iterrows():
            fid, lgid = row["FPS_ID"], int(row["LG_ID"])
            current = fps_stock[fid]
            thresh = row["Reorder_Threshold_tons"]
            if current <= thresh:
                max_cap = row["Max_Capacity_tons"]
                avail = lg_stock.get(lgid, 0.0)
                need_qty = min(max_cap - current, avail)
                if need_qty > 0:
                    urgency = (thresh - current) / row["Daily_Demand_tons"]
                    needs.append((urgency, fid, lgid, need_qty))
        needs.sort(reverse=True, key=lambda x: x[0])
        vehicles["Trips_Used"] = 0
        # Dispatch
        for urgency, fid, lgid, need_qty in needs:
            cands = vehicles[vehicles["Mapped_LGs_List"].apply(lambda lst: lgid in lst)]
            cands = cands[cands["Trips_Used"] < max_trips]
            if cands.empty:
                continue
            shared = cands[cands["Mapped_LGs_List"].str.len() > 1]
            chosen = shared.iloc[0] if not shared.empty else cands.iloc[0]
            vid, cap = chosen["Vehicle_ID"], chosen["Capacity"]
            qty = min(cap, need_qty, lg_stock[lgid])
            if qty <= 0.0:
                continue
            dispatch_records.append({
                "Day": day,
                "Vehicle_ID": vid,
                "LG_ID": lgid,
                "FPS_ID": fid,
                "Quantity_tons": qty
            })
            lg_stock[lgid] -= qty
            fps_stock[fid] += qty
            vehicles.loc[vehicles["Vehicle_ID"] == vid, "Trips_Used"] += 1
        # Record stocks
        for lgid, st in lg_stock.items():
            stock_records.append({
                "Day": day,
                "Entity_Type": "LG",
                "Entity_ID": lgid,
                "Stock_Level_tons": st
            })
        for fid, st in fps_stock.items():
            stock_records.append({
                "Day": day,
                "Entity_Type": "FPS",
                "Entity_ID": fid,
                "Stock_Level_tons": st
            })
    dispatch_lg = pd.DataFrame(dispatch_records)
    stock_levels = pd.DataFrame(stock_records)

    # Return outputs
    return settings, dispatch_cg, dispatch_lg, stock_levels, lgs, fps
