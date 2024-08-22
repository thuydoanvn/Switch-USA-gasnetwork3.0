import os
from pyomo.environ import *
from switch_model.reporting import write_table

dependencies = 'switch_model.timescales','switch_model.financials'

def define_components(m):
    #1 GAS LINES
    """
    Zone_Gas_Injections and Zone_Gas_Withdrawals are lists of
    components that contribute to gas-zone level gas balance equations.
    sum(Zone_Gas_Injections[z,t]) == sum(Zone_Gas_Withdrawals[z,t])
        for all z,t
    Other modules may append to either list, as long as the components they
    add are indexed by [zone, timeseries] and have units of MMBtu. Other modules
    often include Expressions to summarize decision variables on a zonal basis.
    """
    m.GAS_LINES_TIMESERIES = Set(
        dimen=3,
        initialize=lambda m: m.DIRECTIONAL_GL * m.TIMESERIES
    )
    m.DispatchGl = Var(m.GAS_LINES_TIMESERIES, within=NonNegativeReals)
    ## Constraints: 
    # Flow on each gas line-direction must be less than installed capacity on that corridor as of that timeseries
    m.Maximum_DispatchGl = Constraint(
        m.GAS_LINES_TIMESERIES,
        rule=lambda m, zone_from, zone_to, ts: (
            m.DispatchGl[zone_from, zone_to, ts] <=
            m.DirectionalGlCapacityNameplate[zone_from, zone_to,
                                     m.ts_period[ts]]))
    m.GlGasSent = Expression(
        m.GAS_LINES_TIMESERIES,
        rule=lambda m, zone_from, zone_to, ts: (
            m.DispatchGl[zone_from, zone_to, ts]))
    ### Gas line fuel cost = 3.04% of total consumption (US average, 2015-2019, EIA data).
    #  Temporarily use the same number for all states.
    # ==>  m.gl_efficiency: default = 1 - 0.03 = 0.97 --> GlGasReceived = 0.97*GlGasSent
    # Gas line fuel is accounted in gas line fuel expense already. Here set gl_efficiency = 1
    m.gl_efficiency = Param(
        m.GAS_LINES,
        within=PercentFraction,
        default=1)
    m.GlGasReceived = Expression(
        m.GAS_LINES_TIMESERIES,
        rule=lambda m, zone_from, zone_to, ts: (
            m.DispatchGl[zone_from, zone_to, ts]*
            m.gl_efficiency[m.gas_d_line[zone_from, zone_to]]))
    def GLGasNet_calculation(m, z, ts):
        return (
            sum(m.GlGasReceived[zone_from, z, ts]
                for zone_from in m.GL_CONNECTIONS_TO_ZONE[z]) -
            sum(m.GlGasSent[z, zone_to, ts]
                for zone_to in m.GL_CONNECTIONS_TO_ZONE[z]))
    m.GLGasNet = Expression(
        m.GAS_ZONES, m.TIMESERIES,
        rule=GLGasNet_calculation)
    # Register net transmission as contributing to zonal energy balance
    m.Zone_Gas_Injections.append('GLGasNet')

    #2 GAS STORAGE
    m.GZ_STORAGE_TYPE_TIMESERIES = Set(
        dimen=3,
        ordered=True,
        initialize=lambda m: m.GAS_ZONES * m.GAS_STORAGE_TYPES * m.TIMESERIES
    )
    ### the amount of gas added to storage in each gas zone during each timeseries
    m.GasStorageQuantity = Var(m.GZ_STORAGE_TYPE_TIMESERIES, within=NonNegativeReals)
    m.GasStorageInjectionQuantity = Var(
        m.GZ_STORAGE_TYPE_TIMESERIES,
        within=NonNegativeReals)
    ### the amount of gas removed from storage in each gas zone during each timeseries,
    m.GasStorageWithdrawalQuantity = Var(
        m.GZ_STORAGE_TYPE_TIMESERIES,
        within=NonNegativeReals)
    m.GasStorageNetWithdrawal = Expression(
        m.GZ_STORAGE_TYPE_TIMESERIES,
        rule = lambda m, z, ty, ts:
            m.GasStorageWithdrawalQuantity[z, ty, ts] - m.GasStorageInjectionQuantity[z, ty, ts])
    ### the quantity of gas in storage in each (gas zone - timeseries)
    m.GasStorageNetWithdrawalSum = Expression(
        m.GAS_ZONES_TIMESERIES,
        rule = lambda m, z, ts: sum(
            m.GasStorageNetWithdrawal[z, ty, ts]
            for ty in m.GAS_STORAGE_TYPES)
        )

    ### Register net injections with zonal gas balance
    m.Zone_Gas_Injections.append('GasStorageNetWithdrawalSum')

    ## Constraints - Storage
    ### the amount of gas in storage at the end of each timeseries
    ### must equal the level at the end of the prior timeseries (wrapping from start of year to end)
    ### assume storage fuel cost = 4% gross of injection gas

    ### track state of storage: previous quantity + injections - withdrawals - gas fuel loss
    def Track_State_Of_Storage_rule(m, z, ty, ts):
        return m.GasStorageQuantity[z, ty, ts] == \
            m.GasStorageQuantity[z, ty, m.ts_previous[ts]] + \
            (m.GasStorageInjectionQuantity[z, ty, ts] * m.gas_storage_efficiency[z, ty] -
            m.GasStorageWithdrawalQuantity[z, ty, ts]) - \
            ((m.GasStorageInjectionQuantity[z, ty, ts]) * (1 - m.gas_store_to_release_ratio[z, ty])) #equal to zero for now
    m.Track_State_Of_Storage = Constraint(
        m.GZ_STORAGE_TYPE_TIMESERIES,
        rule=Track_State_Of_Storage_rule)
    
    ### quantity of gas in storage in each gas zone must never be below zero or
    ### above the amount of non-retired storage capacity existing during that timeseries
    def State_Of_Storage_Upper_Limit_rule(m, z, ty, ts):
        return m.GasStorageQuantity[z, ty, ts] <= \
            m.GasStorageCapacity[z, ty, m.ts_period[ts]]
    m.State_Of_Storage_Upper_Limit = Constraint(
        m.GZ_STORAGE_TYPE_TIMESERIES,
        rule=State_Of_Storage_Upper_Limit_rule)
    ### storages can only complete the specified number of cycles per year, averaged over each period
    m.Storage_Cycle_Limit = Constraint(
        m.GZ_STORAGE_TYPE_PERIODS,
        rule=lambda m, z, ty, p:
            # solvers sometimes perform badly with infinite constraint
            Constraint.Skip if m.gas_storage_max_cycles_per_year[ty] == float('inf')
            else (
                sum(m.GasStorageWithdrawalQuantity[z, ty, ts] * m.ts_scale_to_year[ts] for ts in m.TS_IN_PERIOD[p])
                <=
                m.GasStorageCapacity[z, ty, p] * m.gas_storage_max_cycles_per_year[ty]
            ))

    #4 GAS IMPORT - EXPORT
    m.gas_import_ref_quantity = Param(
        m.GAS_ZONES_TIMESERIES,
        within=NonNegativeReals,
        default=0
    )
    m.gas_export_ref_quantity = Param(
        m.GAS_ZONES_TIMESERIES,
        within=NonNegativeReals,
        default=0
    )
    m.Zone_Gas_Withdrawals.append('gas_export_ref_quantity')
    m.Zone_Gas_Injections.append('gas_import_ref_quantity')
    
    #4 GAS DEMAND
    ## Define demand sectors
    m.DEMAND_SECTORS = Set(dimen=1, initialize=['EI', 'RC'])
    
    ## use demand price to compute cost of fuel loss
    ## for simplicity, assume the cost of natural gas loss during transmission, storage, and LNG processing is the same as the cost of gas in the RC sector.
    m.gas_ref_price = Param(
        m.GAS_ZONES, m.TIMESERIES, m.DEMAND_SECTORS,
        within=NonNegativeReals,
        # Max city gate price among contiguous US states in 2019: 7.22*1000/(NG_btu_per_cf);
        # [or 5.17 = weighted average of gas price in US in 2019]
        default=6.96 
    )
    
    m.gas_unit_cost = Param(
        m.GAS_ZONES, m.TIMESERIES,
        rule=lambda m, z, ts: (m.gas_ref_price[z,ts,'RC']) 
    )
    ## Demand in each sector
    m.gas_demand_ref_quantity = Param(
        m.GAS_ZONES, m.TIMESERIES, m.DEMAND_SECTORS,
        within=NonNegativeReals,
        default=0.001 #avoid 'float division by zero' error in the 'gas_iterative_demand_response.py'
    )
    ## Total demand, sum of all sectors
    m.gas_demand_total = Param(
        m.GAS_ZONES,
        m.TIMESERIES,
        within=NonNegativeReals,
        initialize=lambda m, z, ts: sum(
            m.gas_demand_ref_quantity[z, ts, ds]
            for ds in m.DEMAND_SECTORS
        ),
    )

    m.Zone_Gas_Withdrawals.append('gas_demand_total')
    # Total demand in each period
    m.zone_total_gas_demand_in_period_mmbtu = Param(
        m.GAS_ZONES, m.PERIODS,
        within=NonNegativeReals,
        initialize=lambda m, z, p: (
            sum(m.gas_demand_total[z, ts] * m.ts_scale_to_period[ts]
                for ts in m.TS_IN_PERIOD[p]))
    )

    # #5 OPERATIONAL COST
    # # 5.1 GAS PRODUCTION COST
    ## The amount of gas produced in each gas zone during each period depends on
    # number of wells available and production_year.
    ### Determined in gas_well_build.py
    m.Zone_Gas_Injections.append("GasSupplyQuantity")
    
    # Summarize gas production costs in each timepoint for the objective function
    m.gas_well_operating_cost_perMMbtud = Param(
        m.GAS_ZONES_TIMESERIES,
        within=NonNegativeReals,
        #$0.8/MMcfd ~ $0.0008/MMbtud in 2013 for operation cost only, not yet count labor cost etc.
        # https://rbnenergy.com/shale-production-economics-part-4-variable-cost-and-net-present-value
        default= 0.1 
    )
    m.gas_well_operating_cost = Param(
        m.GAS_ZONES_TIMESERIES,
        within=NonNegativeReals,
        initialize=lambda m, z, ts: (
        # cost per timeseries equals cost per day / number of timeseries per day
        m.gas_well_operating_cost_perMMbtud[z,ts] / 
        (24/m.ts_duration_hrs[ts]) 
        )
    )
    m.GasProdCostsPerTP = Expression(
        m.TIMEPOINTS,
        rule=lambda m, tp:
        sum(
            m.GasSupplyQuantity[z,ts] * m.gas_well_operating_cost[z,ts] / m.ts_num_tps[ts]
            for (z,ts) in m.GAS_ZONES_TIMESERIES
            if ts==m.tp_ts[tp]
            )
    )
    m.Cost_Components_Per_TP.append('GasProdCostsPerTP')

    # 5.2 TRANSMISSION FUEL COST: the volume of gas pipeline uses was also included as m.gl_efficiency
    m.gas_transmission_fuel_cost = Param(
        within=NonNegativeReals,
        # pipeline and distribution uses is 1.5% of total U.S. inter-state movement volume (US average, 2019, EIA data). 
        # For simplicity, use the same number for all states.
        default=0.03 
    )
    def DispatchGl_calculation(m, z, ts):
        return (
            sum(m.DispatchGl[z, zone_to, ts]
                for zone_to in m.GL_CONNECTIONS_TO_ZONE[z]))
    m.SumDispatchGl = Expression(
        m.GAS_ZONES, m.TIMESERIES,
        rule=DispatchGl_calculation)
    
    m.TransmissionCostsPerTP = Expression(
        m.TIMEPOINTS,
        rule=lambda m, tp:
        sum(
            m.gas_transmission_fuel_cost * m.SumDispatchGl[z,ts] * m.gas_unit_cost[z,ts]* m.tp_duration_hrs[tp]/ 24
            for (z,ts) in m.GAS_ZONES_TIMESERIES
            if ts==m.tp_ts[tp]
            )
    )
    m.Cost_Components_Per_TP.append('TransmissionCostsPerTP')

    # 5.3 STORAGE FUEL COST:
    m.gas_storage_fuel_cost = Param(
        m.GAS_STORAGE_TYPES,
        within=NonNegativeReals,
        # 2% of gross storage injections and withdrawals
        default=0.02 
    )
    m.StorageFuelCostTS = Expression(
        m.GAS_ZONES_TIMESERIES,
        rule=lambda m, z, ts:
        sum(
            m.gas_storage_fuel_cost[ty] * (
            m.GasStorageInjectionQuantity[z, ty, ts] +
            m.GasStorageWithdrawalQuantity[z, ty, ts]
            )
            for ty in m.GAS_STORAGE_TYPES
        )
    )
    m.StorageCostsPerTP = Expression(
        m.TIMEPOINTS,
        rule=lambda m, tp:
        sum(
            m.StorageFuelCostTS[z,ts] *
            m.gas_unit_cost[z, ts] *
            m.tp_duration_hrs[tp]/ 24
            for (z,ts) in m.GAS_ZONES_TIMESERIES
            if ts==m.tp_ts[tp]
            )
    )
    m.Cost_Components_Per_TP.append('StorageCostsPerTP')

    # LNG processing cost
    # Liquefaction cost in term of dollars
    m.LNGLiquefactionCostsPerTP = Expression(
        m.TIMEPOINTS,
        rule=lambda m, tp:
        sum(
            m.LNGLiquefactionLoss[z,ts] * m.gas_unit_cost[z,ts]* m.tp_duration_hrs[tp]/ 24
            for (z,ts) in m.GAS_ZONES_TIMESERIES
            if ts==m.tp_ts[tp]
            )
    )
    m.Cost_Components_Per_TP.append('LNGLiquefactionCostsPerTP')
    ## Regasification (i.e.Vaporization) cost in term of dollars
    m.LNGRegasificationCostsPerTP = Expression(
        m.TIMEPOINTS,
        rule=lambda m, tp:
        sum(
            m.LNGRegasificationLoss[z,ts] * m.gas_unit_cost[z,ts]* m.tp_duration_hrs[tp]/ 24
            for (z,ts) in m.GAS_ZONES_TIMESERIES
            if ts==m.tp_ts[tp]
            )
    )
    m.Cost_Components_Per_TP.append('LNGRegasificationCostsPerTP')