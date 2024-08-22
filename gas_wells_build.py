#### GAS WELLS by Drill Type and GAS ZONES
import os
from pyomo.environ import *
from switch_model.financials import capital_recovery_factor as crf
from switch_model.reporting import write_table

dependencies = 'switch_model.timescales','switch_model.financials'

def define_components(m):
    m.DRILL_TYPE = Set(dimen=1)
    m.GAS_WELL_IN_ZONE = Set(
        dimen=2
        ,initialize=m.GAS_ZONES * m.DRILL_TYPE
        ) #2-dimension index(zone, drill type)
    m.PROD_YEAR = Set(dimen=1)
    m.GAS_WELL_IN_ZONE_PRODYEAR = Set( #3-dimension index(zone, drill type, production year)
        dimen=3
        ,initialize=m.GAS_ZONES * m.DRILL_TYPE * m.PROD_YEAR)
    m.BLD_YRS_FOR_EXISTING_GAS_WELL = Set( #3-dimension index(zone, drill type, build year)
        dimen=3)
    m.gas_well_new_build_allowed = Param(
        m.GAS_ZONES,
        within=Boolean)
    m.gas_well_predet_num = Param(
        m.BLD_YRS_FOR_EXISTING_GAS_WELL,
        within=NonNegativeReals,
        default=0
    )
    m.production_rate_mmbtud = Param(
        m.GAS_WELL_IN_ZONE_PRODYEAR,
        within=NonNegativeReals,
        # if production rate is not available, then assume no well production
        default = 0 
    )
    m.well_capital_cost = Param(
        m.GAS_WELL_IN_ZONE,
        within=PositiveReals,
        # https://www.tidalpetroleum.com/processes/drilling-cost and https://www.tidalpetroleum.com/processes/completion-cost 
        # $5 million is about max value of capital cost in the data
        default=5000000, 
    )

    m.gas_well_max_age = Param(
        m.DRILL_TYPE,
        within=PositiveReals,
        default=30)
    m.NEW_GAS_WELL_BLD_YRS = Set(
        dimen=3,
        ordered=True,
        initialize=m.GAS_WELL_IN_ZONE * m.PERIODS,
        filter=lambda m, z, dt, p: m.gas_well_new_build_allowed[z]) #dt is abbreviation for Well Drill Type
    m.BLD_YRS_FOR_GAS_WELL = Set(
        dimen=3,
        ordered=True,
        initialize=lambda m: m.BLD_YRS_FOR_EXISTING_GAS_WELL | m.NEW_GAS_WELL_BLD_YRS)

    # how many well to build each period
    def bounds_BuildWell(model, z, dt, bld_yr):
        if((z, dt, bld_yr) in model.BLD_YRS_FOR_EXISTING_GAS_WELL):
            return (model.gas_well_predet_num[z,dt,bld_yr], 
                    model.gas_well_predet_num[z,dt,bld_yr])
        else:
            return (0, None)
    m.BuildWellNum = Var(
        m.BLD_YRS_FOR_GAS_WELL,
        within=NonNegativeIntegers,
        bounds=bounds_BuildWell)
    
    # Constraints to limit the total number of wells built in each period
    # Historical data shows that the number of gas wells built in a given year is less than 90000.
    # 2010: number of gas wells built = 488000, 2011: 575000.
    # https://www.statista.com/statistics/187302/number-of-natural-gas-wells-in-the-us-since-2005/

    # Set the constraint at historical maximum number of gas wells built in a given year
    m.max_gas_well_build_year = Param(
        m.GAS_ZONES,
        within=NonNegativeReals,
        # if no data, then do not build any well
        default=0) 

    m.Gas_Well_Upper_Limit = Constraint(
        m.GAS_ZONES,
        m.PERIODS,
        rule=lambda m, z, p: Constraint.Skip
        if not m.gas_well_new_build_allowed[z]
        else (sum(m.BuildWellNum[z, dt, p] for dt in m.DRILL_TYPE) <= 
              m.max_gas_well_build_year[z]),
    )

    # Some projects are retired before the first study period, so they
    # don't appear in the objective function or any constraints.
    # In this case, pyomo may leave the variable value undefined even
    # after a solve, instead of assigning a value within the allowed
    # range. This causes errors in the Progressive Hedging code, which
    # expects every variable to have a value after the solve. So as a
    # starting point we assign an appropriate value to all the existing
    # projects here.
    def BuildWell_assign_default_value(m, z, dt, bld_yr):
        m.BuildWellNum[z,dt, bld_yr] = m.gas_well_predet_num[z, dt, bld_yr]
    m.BuildWell_assign_default_value = BuildAction(
        m.BLD_YRS_FOR_EXISTING_GAS_WELL,
        rule=BuildWell_assign_default_value)

    def well_build_can_operate_in_period(m, dt, build_year, period):
        if build_year in m.PERIODS:
            online = m.period_start[build_year]
        else:
            online = build_year
        retirement = online + m.gas_well_max_age[dt]
        return (
            online <= m.period_start[period] < retirement
        )
    
    """
    BLD_YRS_FOR_WELL_PERIOD[z, dt, period] is a complementary
    indexed set that identify which build years will still be online
    for the given project in the given period. For some project-period
    combinations, this will be an empty set.
    """

    # The set of build years that could be online in the given period
    # for the given project.
    m.BLD_YRS_FOR_WELL_PERIOD = Param(
        m.GAS_WELL_IN_ZONE, m.PERIODS, # zone, drill_type, periods
        within = Any,
        initialize=lambda m, z, dt, period: set(
            bld_yr for (zone, drill_type, bld_yr) in m.BLD_YRS_FOR_GAS_WELL
            if drill_type == dt and zone == z and
               well_build_can_operate_in_period(m, dt, bld_yr, period)))
    m.DRILL_TYPE_OF_WELL_PERIOD = Param(
        m.GAS_ZONES, m.PERIODS,
        within = Any,
        initialize=lambda m, z, p: set(
            drill_type for (zone, drill_type, period) in m.GAS_WELL_IN_ZONE * m.PERIODS
            if zone == z and period == p))
    
    # The set of periods when a well is available to produce
    # WellNum[z, dt, prod_y, period] is an expression that returns the total
    # number of well by drill type and production year in a given period.
    # This is the sum of number of built well minus all retirement

    # Total number of wells by drill_type and production_year of a gas_zone in a given period
    m.WellNumInProdYear = Expression(
        m.GAS_WELL_IN_ZONE_PRODYEAR, m.PERIODS,
        rule=lambda m, z, dt, prod_yr, period: sum(
            m.BuildWellNum[z, dt, bld_yr]
            for bld_yr in m.BLD_YRS_FOR_WELL_PERIOD[z,dt,period]
            if bld_yr == period - prod_yr + 1))
    
    #Gas Supply Quantity is a sum of WellProductionCapacity, i.e.production capacity across wells in each zone in a given timeseries
    m.GasSupplyQuantityByType = Expression(
        m.GAS_WELL_IN_ZONE, m.TIMESERIES,
        rule=lambda m, z, dt, ts: sum(
            m.WellNumInProdYear[z, dt, prod_yr, m.ts_period[ts]] *
            m.production_rate_mmbtud[z, dt, prod_yr] /
            (24/m.ts_duration_hrs[ts]) # convert from daily to timeseries. 
            for prod_yr in m.PROD_YEAR
        )
    )
    
    m.GasSupplyQuantity = Expression(
        m.GAS_ZONES, m.TIMESERIES,
        rule=lambda m, z, ts: sum(
            m.GasSupplyQuantityByType[z, dt, ts] for dt in m.DRILL_TYPE
        )
    )

    m.GasWellFixedCosts = Expression(
        m.PERIODS,
        rule=lambda m, p: sum(m.BuildWellNum[z, dt, p] *
                   m.well_capital_cost[z,dt]*
                   crf(m.interest_rate, m.gas_well_max_age[dt])
                   for (z, dt, p) in m.BLD_YRS_FOR_GAS_WELL))
    
    m.Cost_Components_Per_Period.append('GasWellFixedCosts')

def load_inputs(m, gas_switch_data, inputs_dir):
    gas_switch_data.load_aug(
        filename=os.path.join(inputs_dir, 'drill_type.csv'),
        select=('DRILL_TYPE', 'gas_well_max_age'),
        index=m.DRILL_TYPE,
        param=m.gas_well_max_age
    )
    gas_switch_data.load_aug(
        filename=os.path.join(inputs_dir, 'prod_year.csv'),
        index=m.PROD_YEAR,
        param=tuple()
    )
    gas_switch_data.load_aug(
        filename=os.path.join(inputs_dir, 'gas_well_predetermined.csv'),
        index=m.BLD_YRS_FOR_EXISTING_GAS_WELL, #3-dimension index(zone, drill type, build year)
        param=(m.gas_well_predet_num)
    )
    gas_switch_data.load_aug(
        filename=os.path.join(inputs_dir, 'gas_well_production_curve_annual.csv'),
        select=('GAS_ZONES','DRILL_TYPE','PROD_YEAR','gas_production_rate_mmbtud'),
        param=(m.production_rate_mmbtud)
    )
    gas_switch_data.load_aug(
        filename=os.path.join(inputs_dir, 'gas_well_capital_cost.csv'),
        select=('GAS_ZONES','DRILL_TYPE','well_capital_cost'),
        param=(m.well_capital_cost)
    )
    gas_switch_data.load_aug(
        filename=os.path.join(inputs_dir, 'max_gas_well_build.csv'),
        param=(m.max_gas_well_build_year)
    )
