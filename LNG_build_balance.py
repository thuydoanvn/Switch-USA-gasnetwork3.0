# Define additional capacity of LNG storage to be built
import os
from pyomo.environ import *
from switch_model.financials import capital_recovery_factor as crf
from switch_model.reporting import write_table
from switch_model.utilities import unique_list

dependencies = "switch_model.timescales", "switch_model.financials"


def define_components(m):
    m.Zone_Gas_Injections = []
    m.Zone_Gas_Withdrawals = []

    m.LNG_storage_capital_cost = Param(within=NonNegativeReals, default=110.4)
    m.LNG_liquefaction_capital_cost = Param(within=NonNegativeReals, default=77.3)
    m.LNG_vaporization_capital_cost = Param(within=NonNegativeReals, default=33.1)

    #### 1. LNG STORAGE BUILD
    # Valid locations and times for gas infrastructure
    m.GAS_ZONES_PERIODS = Set(
        dimen=2, ordered=True, initialize=lambda m: m.GAS_ZONES * m.PERIODS
    )

    m.BLD_YRS_FOR_EXISTING_LNG_STORAGE = Set(dimen=2)
    m.LNG_storage_predet_cap = Param(
        m.BLD_YRS_FOR_EXISTING_LNG_STORAGE, within=NonNegativeReals, default=0
    )

    # allow all states to build LNG storage
    m.LNG_new_build_allowed = Param(m.GAS_ZONES, within=Boolean, default=True)

    m.NEW_LNG_STORAGE_BLD_YRS = Set(
        dimen=2,
        initialize=m.GAS_ZONES * m.PERIODS,
        filter=lambda m, z, p: m.LNG_new_build_allowed[z],
    )

    m.BLD_YRS_FOR_LNG_STORAGE = Set(
        dimen=2,
        ordered=True,
        initialize=lambda m: m.BLD_YRS_FOR_EXISTING_LNG_STORAGE
        | m.NEW_LNG_STORAGE_BLD_YRS,
    )

    m.LNG_storage_removed_cap = Param(
        m.BLD_YRS_FOR_LNG_STORAGE, within=NonNegativeReals, default=0
    )

    m.LNG_storage_life = Param(within=NonNegativeReals, default=50)

    # how much storage capacity to build
    def bounds_BuildLNGStorage(model, z, bld_yr):
        if (z, bld_yr) in model.BLD_YRS_FOR_EXISTING_LNG_STORAGE:
            return (
                model.LNG_storage_predet_cap[z, bld_yr],
                model.LNG_storage_predet_cap[z, bld_yr],
            )
        else:
            return (0, None)

    m.BuildLNGStorageCap = Var(
        m.BLD_YRS_FOR_LNG_STORAGE,
        within=NonNegativeReals,
        bounds=bounds_BuildLNGStorage,
    )

    m.LNGStorageCapacity = Expression(
        m.GAS_ZONES,
        m.PERIODS,
        rule=lambda m, z, period: sum(
            m.BuildLNGStorageCap[z2, bld_yr] - m.LNG_storage_removed_cap[z2, bld_yr]
            for (z2, bld_yr) in m.BLD_YRS_FOR_LNG_STORAGE
            if z2 == z and (bld_yr == "Legacy" or bld_yr <= period)
        ),
    )
    # Summarize capital costs of storage for the objective function. (real $ per MMBtu)
    m.LNGStorageFixedCosts = Expression(
        m.PERIODS,
        rule=lambda m, p: sum(
            m.BuildLNGStorageCap[g, p] * m.LNG_storage_capital_cost
            * crf(m.interest_rate, m.LNG_storage_life)
            for g in m.GAS_ZONES
        ),
    )
    m.Cost_Components_Per_Period.append("LNGStorageFixedCosts")

    #### 2. LNG LIQUEFACTION CAPACITY

    m.BLD_YRS_FOR_EXISTING_LNG_LIQUEFACTION = Set(dimen=2)
    m.LNG_liquefaction_predet_cap = Param(
        m.BLD_YRS_FOR_EXISTING_LNG_LIQUEFACTION, within=NonNegativeReals, default=0
    )

    m.NEW_LNG_LIQUEFACTION_BLD_YRS = Set(
        dimen=2,
        initialize=m.GAS_ZONES * m.PERIODS,
        filter=lambda m, z, p: m.LNG_new_build_allowed[z],
    )

    m.BLD_YRS_FOR_LNG_LIQUEFACTION = Set(
        dimen=2,
        ordered=True,
        initialize=lambda m: m.BLD_YRS_FOR_EXISTING_LNG_LIQUEFACTION
        | m.NEW_LNG_LIQUEFACTION_BLD_YRS,
    )

    m.LNG_liquefaction_removed_cap = Param(
        m.BLD_YRS_FOR_LNG_LIQUEFACTION, within=NonNegativeReals, default=0
    )

    m.LNG_liquefaction_life = Param(within=NonNegativeReals, default=50)

    # how much storage capacity to build
    def bounds_BuildLNGLiquefaction(model, z, bld_yr):
        if (z, bld_yr) in model.BLD_YRS_FOR_EXISTING_LNG_LIQUEFACTION:
            return (
                model.LNG_liquefaction_predet_cap[z, bld_yr],
                model.LNG_liquefaction_predet_cap[z, bld_yr],
            )
        else:
            return (0, None)

    m.BuildLNGLiquefactionCap = Var(
        m.BLD_YRS_FOR_LNG_LIQUEFACTION,
        within=NonNegativeReals,
        bounds=bounds_BuildLNGLiquefaction,
    )

    # Summarize capital costs of storage for the objective function. (real $ per MMBtu)
    m.LNGLiquefactionFixedCosts = Expression(
        m.PERIODS,
        rule=lambda m, p: sum(
            m.BuildLNGLiquefactionCap[g, p] * m.LNG_liquefaction_capital_cost
            * crf(m.interest_rate, m.LNG_storage_life)
            for g in m.GAS_ZONES
        ),
    )
    m.Cost_Components_Per_Period.append("LNGLiquefactionFixedCosts")

    #### 3. LNG VAPORIZATION CAPACITY

    m.BLD_YRS_FOR_EXISTING_LNG_VAPORIZATION = Set(dimen=2)
    m.LNG_vaporization_predet_cap = Param(
        m.BLD_YRS_FOR_EXISTING_LNG_VAPORIZATION, within=NonNegativeReals, default=0
    )

    m.NEW_LNG_VAPORIZATION_BLD_YRS = Set(
        dimen=2,
        initialize=m.GAS_ZONES * m.PERIODS,
        filter=lambda m, z, p: m.LNG_new_build_allowed[z],
    )

    m.BLD_YRS_FOR_LNG_VAPORIZATION = Set(
        dimen=2,
        ordered=True,
        initialize=lambda m: m.BLD_YRS_FOR_EXISTING_LNG_VAPORIZATION
        | m.NEW_LNG_VAPORIZATION_BLD_YRS,
    )

    m.LNG_vaporization_removed_cap = Param(
        m.BLD_YRS_FOR_LNG_VAPORIZATION, within=NonNegativeReals, default=0
    )

    m.LNG_vaporization_life = Param(within=NonNegativeReals, default=50)

    # how much storage capacity to build
    def bounds_BuildLNGVaporization(model, z, bld_yr):
        if (z, bld_yr) in model.BLD_YRS_FOR_EXISTING_LNG_VAPORIZATION:
            return (
                model.LNG_vaporization_predet_cap[z, bld_yr],
                model.LNG_vaporization_predet_cap[z, bld_yr],
            )
        else:
            return (0, None)

    m.BuildLNGVaporizationCap = Var(
        m.BLD_YRS_FOR_LNG_VAPORIZATION,
        within=NonNegativeReals,
        bounds=bounds_BuildLNGVaporization,
    )

    # Summarize capital costs of storage for the objective function. (real $ per MMBtu)
    m.LNGVaporizationFixedCosts = Expression(
        m.PERIODS,
        rule=lambda m, p: sum(
            m.BuildLNGVaporizationCap[g, p] * m.LNG_vaporization_capital_cost
            * crf(m.interest_rate, m.LNG_storage_life)
            for g in m.GAS_ZONES
        ),
    )
    m.Cost_Components_Per_Period.append("LNGVaporizationFixedCosts")

    ####  4. LNG FLOWS

    m.LNG_ROUTE = Set(dimen=1)
    # input parameters defining LNG transportation routes
    m.LNG_route_gz1 = Param(m.LNG_ROUTE, within=m.GAS_ZONES)
    m.LNG_route_gz2 = Param(m.LNG_ROUTE, within=m.GAS_ZONES)
    m.LNG_route_distance = Param(m.LNG_ROUTE, within=NonNegativeReals)
    m.LNG_flow_allowed = Param(m.LNG_ROUTE, within=Boolean)

    m.min_data_check(
        "LNG_route_gz1", "LNG_route_gz2", "LNG_route_distance", "LNG_flow_allowed"
    )

    # Directional LNG transportation
    def init_DIRECTIONAL_ROUTE(model):
        r_dir = set()
        for r in model.LNG_ROUTE:
            r_dir.add((model.LNG_route_gz1[r], model.LNG_route_gz2[r]))
            r_dir.add((model.LNG_route_gz2[r], model.LNG_route_gz1[r]))
        return list(r_dir)

    m.DIRECTIONAL_ROUTE = Set(initialize=init_DIRECTIONAL_ROUTE)
    m.LNG_TRANSPORTIONS_TO_ZONE = Set(
        m.GAS_ZONES,
        initialize=lambda m, gz: [
            z for z in m.GAS_ZONES if (z, gz) in m.DIRECTIONAL_ROUTE
        ],
    )

    def init_LNG_d_route(m, zone_from, zone_to):
        for r in m.LNG_ROUTE:
            if (m.LNG_route_gz1[r] == zone_from and m.LNG_route_gz2[r] == zone_to) or (
                m.LNG_route_gz2[r] == zone_from and m.LNG_route_gz1[r] == zone_to
            ):
                return r

    m.LNG_d_route = Param(
        m.DIRECTIONAL_ROUTE, within=m.LNG_ROUTE, initialize=init_LNG_d_route
    )
    m.LNG_ROUTE_TIMESERIES = Set(
        dimen=3, initialize=lambda m: m.DIRECTIONAL_ROUTE * m.TIMESERIES
    )

    m.LNGShipped = Var(
        m.LNG_ROUTE_TIMESERIES, 
        within=NonNegativeReals,
    )

    m.LNG_ship_efficiency = Param(
        m.LNG_ROUTE, within=PercentFraction, default=1
    )  # assume no loss during shipping (short distance)

    m.LNGReceived = Expression(
        m.LNG_ROUTE_TIMESERIES,
        rule=lambda m, zone_from, zone_to, ts: (
            m.LNGShipped[zone_from, zone_to, ts]
            * m.LNG_ship_efficiency[m.LNG_d_route[zone_from, zone_to]]
        ),
    )

    # 5. LNG quantity at each gas zone
    # 5.1 LNG additions to storage includes: 
    # international imports, receive from (- ship to) other states, liquefy from NG

    m.LNG_import_ref_quantity = Param(
        m.GAS_ZONES_TIMESERIES, within=NonNegativeReals, default=0
    )
    m.SumLNGReceived = Expression(
        m.GAS_ZONES_TIMESERIES,
        rule=lambda m, z, ts: sum(
            m.LNGReceived[zone_from, z, ts]
            for zone_from in m.LNG_TRANSPORTIONS_TO_ZONE[z]
        ),
    )
    m.LNGLiquefiedFromNG = Var(m.GAS_ZONES_TIMESERIES, within=NonNegativeReals)
    # Storage is needed to store LNG produced (before it can be shipped to somewhere else)
    m.LNG_Liquefied_Volume_Upper_Limit = Constraint(
        m.GAS_ZONES_TIMESERIES,
        rule=lambda m, z, ts: m.LNGLiquefiedFromNG[z, ts]
        <= m.LNGStorageCapacity[z, m.ts_period[ts]],
    )

    ### the amount of gas added to storage in each gas zone during each timeseries
    m.LNGStorageAdditionQuantity = Expression(
        m.GAS_ZONES_TIMESERIES,
        rule=lambda m, z, ts: m.LNG_import_ref_quantity[z, ts]
        + m.SumLNGReceived[z, ts]
        + m.LNGLiquefiedFromNG[z, ts],
    )

    # 5.1 LNG withdrawals from storage for: ship to other states, regasify to NG
    m.SumLNGShipped = Expression(
        m.GAS_ZONES_TIMESERIES,
        rule=lambda m, z, ts: sum(
            m.LNGShipped[z, zone_to, ts] for zone_to in m.LNG_TRANSPORTIONS_TO_ZONE[z]
        ),
    )
    m.LNGRegasifiedToNG = Var(m.GAS_ZONES_TIMESERIES, within=NonNegativeReals)
    ## LNG volume used to regasify must be not exceed LNG volume available at the state
    m.LNG_Regasifying_Volume_Upper_Limit = Constraint(
        m.GAS_ZONES_TIMESERIES,
        rule=lambda m, z, ts: m.LNGRegasifiedToNG[z, ts]
        <= m.LNGStorageAdditionQuantity[z, ts] - m.SumLNGShipped[z, ts],
    )
    ### the amount of gas removed from storage in each gas zone during each timeseries
    m.LNGStorageWithdrawalQuantity = Expression(
        m.GAS_ZONES_TIMESERIES,
        rule=lambda m, z, ts: m.SumLNGShipped[z, ts] + m.LNGRegasifiedToNG[z, ts],
    )

    # For LNG, no constraint max number of storage cycles
    m.LNG_storage_max_cycles_per_year = Param(
        m.GAS_ZONES, within=NonNegativeReals, default=float("inf")
    )

    #### 6. LNG storage Constraints
    # 6.1 Storage rule
    # quantity of gas in storage in each gas zone at the end of each timeseries
    # must equal the level at the end of the prior timeseries (wrapping from start of year to end)
    ## LNG inventory
    m.LNGStorageQuantity = Var(m.GAS_ZONES_TIMESERIES, within=NonNegativeReals)

    m.ts_previous = Param(
        m.TIMESERIES,
        within=m.TIMESERIES,
        initialize=lambda m, ts: m.TS_IN_PERIOD[m.ts_period[ts]].prevw(ts),
    )

    # track state of storage: previous quantity + injections - withdrawals
    def Track_State_Of_LNG_Storage_rule(m, z, ts):
        return m.LNGStorageQuantity[z, ts] == m.LNGStorageQuantity[
            z, m.ts_previous[ts]
        ] + (
            m.LNGStorageAdditionQuantity[z, ts] - m.LNGStorageWithdrawalQuantity[z, ts]
        )

    m.Track_State_Of_LNG_Storage = Constraint(
        m.GAS_ZONES_TIMESERIES, rule=Track_State_Of_LNG_Storage_rule
    )

    # 6.2 LNG storage capacity constraint
    # quantity of gas in storage in each gas zone must never be below zero or
    # above the amount of non-retired storage capacity existing during that timeseries

    def State_Of_LNG_Storage_Upper_Limit_rule(m, z, ts):
        return m.LNGStorageQuantity[z, ts] <= m.LNGStorageCapacity[z, m.ts_period[ts]]

    m.State_Of_LNG_Storage_Upper_Limit = Constraint(
        m.GAS_ZONES_TIMESERIES, rule=State_Of_LNG_Storage_Upper_Limit_rule
    )
    # storages can only complete the specified number of cycles per year, averaged over each period
    m.LNG_Storage_Cycle_Limit = Constraint(
        m.GAS_ZONES_PERIODS,
        rule=lambda m, g, p:
        # solvers sometimes perform badly with infinite constraint
        Constraint.Skip
        if m.LNG_storage_max_cycles_per_year[g] == float("inf")
        else (
            sum(
                m.LNGStorageWithdrawalQuantity[g, ts] * m.ts_scale_to_period[ts]
                for ts in m.TS_IN_PERIOD[p]
            )
            <= m.LNG_storage_max_cycles_per_year[g]
            * m.LNGStorageCapacity[g, p]
            * m.period_length_years[p]
        ),
    )

    # 6.3 LNG Liquefaction capacity constraint
    m.LNGLiqefactionCapacity = Expression(
        m.GAS_ZONES,
        m.PERIODS,
        rule=lambda m, z, period: sum(
            m.BuildLNGLiquefactionCap[z2, bld_yr]
            - m.LNG_liquefaction_removed_cap[z2, bld_yr]
            for (z2, bld_yr) in m.BLD_YRS_FOR_LNG_LIQUEFACTION
            if z2 == z and (bld_yr == "Legacy" or bld_yr <= period)
        ),
    )

    m.State_Of_LNG_Liquefaction_Upper_Limit = Constraint(
        m.GAS_ZONES_TIMESERIES,
        rule=lambda m, z, ts: m.LNGLiquefiedFromNG[z, ts]
        <= m.LNGLiqefactionCapacity[z, m.ts_period[ts]],
    )

    # 6.4 LNG VAPORIZATION capacity constraint
    m.LNGVaporizationCapacity = Expression(
        m.GAS_ZONES,
        m.PERIODS,
        rule=lambda m, z, period: sum(
            m.BuildLNGVaporizationCap[z2, bld_yr]
            - m.LNG_vaporization_removed_cap[z2, bld_yr]
            for (z2, bld_yr) in m.BLD_YRS_FOR_LNG_VAPORIZATION
            if z2 == z and (bld_yr == "Legacy" or bld_yr <= period)
        ),
    )

    m.State_Of_LNG_Vaporization_Upper_Limit = Constraint(
        m.GAS_ZONES_TIMESERIES,
        rule=lambda m, z, ts: m.LNGRegasifiedToNG[z, ts]
        <= m.LNGVaporizationCapacity[z, m.ts_period[ts]],
    )

    # 7. Operation/Variable Cost of LNG

    # 7.1 Liquefaction cost
    ## Fuel cost for Liquefaction: 9% of feed gas
    m.LNG_from_NG_loss_ratio = Param(m.GAS_ZONES, within=PercentFraction, default=0.09)
    # NG amount needed for LNG Liquefaction
    m.GasQuantityLiquefiedToLNG = Expression(
        m.GAS_ZONES_TIMESERIES,
        rule=lambda m, z, ts: m.LNGLiquefiedFromNG[z, ts]
        / (1 - m.LNG_from_NG_loss_ratio[z]),
    )
    m.Zone_Gas_Withdrawals.append("GasQuantityLiquefiedToLNG")

    # Liquefaction cost in term of heat amount (MMBtu)
    m.LNGLiquefactionLoss = Expression(
        m.GAS_ZONES_TIMESERIES,
        rule=lambda m, z, ts: m.GasQuantityLiquefiedToLNG[z, ts]
        * m.LNG_from_NG_loss_ratio[z],
    )
    m.Zone_Gas_Withdrawals.append("LNGLiquefactionLoss")
    # Liquefaction cost in term of dollars: compute later in gas_network_balance.py

    # 7.2 Regasification cost
    ## Fuel cost for regasification: 2.5% of feed gas
    m.LNG_to_NG_loss_ratio = Param(m.GAS_ZONES, within=PercentFraction, default=0.025)
    ## In total: fuel loss is about 11.5% of feed gas
    # m.LNG_store_to_release_ratio = Param(
    #     m.GAS_ZONES,
    #     within=PercentFraction,
    #     default=0.885) 

    ## NG amount obtained from regasifying LNG
    m.GasQuantityFromLNG = Expression(
        m.GAS_ZONES_TIMESERIES,
        rule=lambda m, z, ts: m.LNGRegasifiedToNG[z, ts]
        * (1 - m.LNG_to_NG_loss_ratio[z]),
    )
    m.Zone_Gas_Injections.append("GasQuantityFromLNG")

    ## Regasification cost in term of heat amount (MMBtu)
    m.LNGRegasificationLoss = Expression(
        m.GAS_ZONES_TIMESERIES,
        rule=lambda m, z, ts: m.LNGRegasifiedToNG[z, ts] * m.LNG_to_NG_loss_ratio[z],
    )
    m.Zone_Gas_Withdrawals.append("LNGRegasificationLoss")

    ## Regasification (i.e.Vaporization) cost in term of dollars: compute later in gas_network_balance.py

    # 7.3 LNG shipping cost

    m.LNG_shipping_unit_cost = Param(
        m.LNG_ROUTE, within=NonNegativeReals, default=0.011
    )  # $1.1/100km/mmbtu

    m.LNGShippingCostsPerTP = Expression(
        m.TIMEPOINTS,
        rule=lambda m, tp: sum(
            m.LNGShipped[zone_from, zone_to, ts]
            * m.LNG_shipping_unit_cost[m.LNG_d_route[zone_from, zone_to]]
            * m.LNG_route_distance[m.LNG_d_route[zone_from, zone_to]]
            * m.tp_duration_hrs[tp]
            / 24
            for (zone_from, zone_to, ts) in m.LNG_ROUTE_TIMESERIES
            if ts == m.tp_ts[tp]
        ),
    )

    m.Cost_Components_Per_TP.append("LNGShippingCostsPerTP")


def load_inputs(m, gas_switch_data, inputs_dir):
    gas_switch_data.load_aug(
        filename=os.path.join(inputs_dir, "LNG_routes.csv"),
        select=(
            "LNG_ROUTE",
            "LNG_route_gz1",
            "LNG_route_gz2",
            "LNG_route_distance",
            "LNG_flow_allowed",
        ),
        index=m.LNG_ROUTE,
        param=(
            m.LNG_route_gz1,
            m.LNG_route_gz2,
            m.LNG_route_distance,
            m.LNG_flow_allowed,
        ),
    )
    # LNG storage
    gas_switch_data.load_aug(
        filename=os.path.join(inputs_dir, "LNG_storage_predetermined.csv"),
        # auto_select=True,
        select=("GAS_ZONES", "LNG_storage_predet_build_year", "LNG_storage_predet_cap", "LNG_storage_removed_cap"),
        index=m.BLD_YRS_FOR_EXISTING_LNG_STORAGE,
        param=(m.LNG_storage_predet_cap, m.LNG_storage_removed_cap),
    )
    # LNG Liquefaction
    gas_switch_data.load_aug(
        filename=os.path.join(inputs_dir, "LNG_liquefaction_predetermined.csv"),
        select=(
            "GAS_ZONES",
            "LNG_liquefaction_predet_build_year",
            "LNG_liquefaction_predet_cap",
            "LNG_liquefaction_removed_cap"
        ),
        index=m.BLD_YRS_FOR_EXISTING_LNG_LIQUEFACTION,
        param=(m.LNG_liquefaction_predet_cap,
               m.LNG_liquefaction_removed_cap),
    )
    # LNG Regasification
    gas_switch_data.load_aug(
        filename=os.path.join(inputs_dir, "LNG_vaporization_predetermined.csv"),
        select=(
            "GAS_ZONES",
            "LNG_vaporization_predet_build_year",
            "LNG_vaporization_predet_cap",
            "LNG_vaporization_removed_cap"
        ),
        index=m.BLD_YRS_FOR_EXISTING_LNG_VAPORIZATION,
        param=(m.LNG_vaporization_predet_cap,
               m.LNG_vaporization_removed_cap),
    )

    # LNG imports
    gas_switch_data.load_aug(
        filename=os.path.join(inputs_dir, "LNG_imports.csv"),
        select=("GAS_ZONES", "TIMESERIES", "LNG_import_ref_quantity"),
        param=(m.LNG_import_ref_quantity),
    )
