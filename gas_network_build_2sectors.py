# Define additional capacity of pipeline and underground storage to be built
import os
from pyomo.environ import *
from pyomo.util.infeasible import *
from switch_model.financials import capital_recovery_factor as crf
from switch_model.reporting import write_table

# turn off SWITCH financial reporting, which currently expects to find LOAD_ZONES
import switch_model.financials

del switch_model.financials.post_solve

dependencies = "switch_model.timescales", "switch_model.financials"


def define_components(m):
    # indexing sets
    m.GAS_ZONES = Set(dimen=1, ordered=True)
    m.GAS_ZONES_TIMESERIES = Set(
        dimen=2, ordered=True, 
        initialize=lambda m: m.GAS_ZONES * m.TIMESERIES
    )
    
    #### GAS LINES
    # input parameters defining gas lines
    m.GAS_LINES = Set(dimen=1, ordered=True)
    m.gas_line_gz1 = Param(m.GAS_LINES, within=m.GAS_ZONES)
    m.gas_line_gz2 = Param(m.GAS_LINES, within=m.GAS_ZONES)
    m.gas_line_length = Param(m.GAS_LINES, within=NonNegativeReals)
    ## BLD_YRS_FOR_EXISTING_GL set is composed of two elements with members: (gas_line, build_year).
    ## For existing gas lines where the build years are not known, build_year is set to 'Legacy'.
    m.BLD_YRS_FOR_EXISTING_GL = Set(dimen=2)
    m.gas_line_predet_cap_general = Param(
        m.BLD_YRS_FOR_EXISTING_GL, within=NonNegativeReals, default=0
    )
    m.gas_line_new_build_allowed = Param(m.GAS_LINES, within=Boolean, default=True)
    m.NEW_GAS_LINE_BLD_YRS = Set(
        dimen=2,
        initialize=m.GAS_LINES * m.PERIODS,
        filter=lambda m, gl, p: m.gas_line_new_build_allowed[gl],
    )
    m.BLD_YRS_FOR_REMOVED_GL = Set(dimen=2)
    m.BLD_YRS_FOR_GAS_LINE = Set(
        dimen=2,
        initialize=lambda m: m.BLD_YRS_FOR_EXISTING_GL
        | m.BLD_YRS_FOR_REMOVED_GL
        | m.NEW_GAS_LINE_BLD_YRS,
    )
    m.gas_line_removed_cap_general = Param(
        m.BLD_YRS_FOR_GAS_LINE, within=NonNegativeReals, default=0
    )

    m.min_data_check("gas_line_gz1", "gas_line_gz2", "gas_line_length")
    """
    DIRECTIONAL_GL is a derived set representing
    (all gas lines) x (two directions of flow possible for each gas line
    (toward gz1 or toward gz2))
    Every gas line will generate two entries in this set. Members of
    this set are abbreviated as gas_d where possible, but may be
    abbreviated as gl in situations where brevity is important and it is
    unlikely to be confused with the overall gas line.
    """

    def init_DIRECTIONAL_GL(model):
        gl_dir = set()
        for gl in model.GAS_LINES:
            gl_dir.add((model.gas_line_gz1[gl], model.gas_line_gz2[gl]))
            gl_dir.add((model.gas_line_gz2[gl], model.gas_line_gz1[gl]))
        return list(gl_dir)

    m.DIRECTIONAL_GL = Set(dimen=2, ordered=True, initialize=init_DIRECTIONAL_GL)
    m.GL_CONNECTIONS_TO_ZONE = Set(
        m.GAS_ZONES,
        initialize=lambda m, gz: [
            z for z in m.GAS_ZONES if (z, gz) in m.DIRECTIONAL_GL
        ],
    )

    def init_gas_d_line(m, zone_from, zone_to):
        for gl in m.GAS_LINES:
            if (m.gas_line_gz1[gl] == zone_from and m.gas_line_gz2[gl] == zone_to) or (
                m.gas_line_gz2[gl] == zone_from and m.gas_line_gz1[gl] == zone_to
            ):
                return gl

    m.gas_d_line = Param(
        m.DIRECTIONAL_GL, within=m.GAS_LINES, initialize=init_gas_d_line
    )
    ## Gas_line capital cost 
    # (example: OVERALL cost = $1.75/mmbtu/km new build twoways- $0.75/mmbtu/km reversal = $1/mmbtu/km)
    m.general_gas_line_capital_cost = Param(
        m.GAS_LINES, within=NonNegativeReals,
        default=1.76
    )  
    ## Gas_line investment cost for each flow direction ($0.75/mmbtu reversal)
    m.directional_gas_line_capital_cost = Param(
        m.GAS_LINES, within=NonNegativeReals,
        default=1.17
    )  
    m.gas_line_life = Param(within=NonNegativeReals, default=50)

    # Fixed Operation and Maintenance Cost:
    # for now using 2.6% of total capital cost 
    # source: https://transitionaccelerator.ca/wp-content/uploads/2023/06/The-Techno-Economics-of-Hydrogen-Pipelines-v2.pdf
    m.gas_line_fixed_om_fraction = Param(within=NonNegativeReals, default=0.026)

    ## m.BuildGl: how much gas line GENERAL capacity (MMBtu) installed on a corridor in a given build year.
    ## For existing builds, this variable is locked to the existing capacity.
    def bounds_BuildGl(model, gl, bld_yr):
        if (gl, bld_yr) in model.BLD_YRS_FOR_EXISTING_GL:
            return (
                model.gas_line_predet_cap_general[gl, bld_yr],
                model.gas_line_predet_cap_general[gl, bld_yr],
            )
        else:
            return (0, None)

    m.BuildGl = Var(
        m.BLD_YRS_FOR_GAS_LINE, within=NonNegativeReals, bounds=bounds_BuildGl
    )

    ## m.BuildDirectionalGl: how much gas line capacity in EACH DIRECTION (MMBtu) installed on a corridor in a given build year.
    m.BLD_YRS_FOR_EXISTING_D_GL = Set(dimen=3)
    m.gas_line_predet_cap_directional = Param(
        m.BLD_YRS_FOR_EXISTING_D_GL, within=NonNegativeReals, default=0
    )

    m.NEW_GAS_D_LINE_BLD_YRS = Set(
        dimen=3,
        initialize=m.DIRECTIONAL_GL * m.PERIODS,
        filter=lambda m, zone_from, zone_to, p: m.gas_line_new_build_allowed[
            m.gas_d_line[zone_from, zone_to]
        ],
    )
    m.BLD_YRS_FOR_REMOVED_D_GL = Set(dimen=3)
    m.BLD_YRS_FOR_GAS_D_LINE = Set(
        dimen=3,
        initialize=lambda m: m.BLD_YRS_FOR_EXISTING_D_GL
        | m.BLD_YRS_FOR_REMOVED_D_GL
        | m.NEW_GAS_D_LINE_BLD_YRS,
    )
    m.gas_line_removed_cap_directional = Param(
        m.BLD_YRS_FOR_GAS_D_LINE, within=NonNegativeReals, default=0
    )

    def bounds_BuildDirectionalGl(model, zone_from, zone_to, bld_yr):
        if (zone_from, zone_to, bld_yr) in model.BLD_YRS_FOR_EXISTING_D_GL:
            return (
                model.gas_line_predet_cap_directional[zone_from, zone_to, bld_yr],
                model.gas_line_predet_cap_directional[zone_from, zone_to, bld_yr],
            )
        else:
            return (0, None)

    m.BuildDirectionalGl = Var(
        m.BLD_YRS_FOR_GAS_D_LINE,
        within=NonNegativeReals,
        bounds=bounds_BuildDirectionalGl,
    )

    ##################
    # Exogenously decisions to build a gas line in a given period
    # Collect data and capacity for exogenously added pipeline
    # and assign that gas line average cost per MMBtu of gas as 
    # a cost adder on top of marginal cost for the residential sector  
    ## Eg. Mountain Valley Pipeline: 2.0 billion cubic feet per day (Bcf/d) of natural gas
    ## equivalently 2.0*10^9*1.037 = 2.074*10^9 MMBtu/day
    ##################
    m.GAS_ZONE_COST_ADDER = Set(dimen=1, 
                                ordered=True)
    
    m.build_general_gl_exo = Param(
        m.BLD_YRS_FOR_GAS_LINE,
        within=NonNegativeReals,
        default=0,
    )
    m.build_directional_gl_exogenous = Param(
        m.BLD_YRS_FOR_GAS_D_LINE,
        within=NonNegativeReals,
        default=0,
    )
    m.directional_gl_exogenous_cost = Param(
        m.BLD_YRS_FOR_GAS_D_LINE,
        within=NonNegativeReals,
        default=0,
    )
    # The exogenous pipeline may be planned to be in operation less than its technical lifespan (50 years)
    m.gas_line_operating_life = Param(
        m.BLD_YRS_FOR_GAS_D_LINE,
        within=Integers,
        default=50,
    )
    # Sum up the annual cost of exogenously built gas lines in a given period
    m.gl_cost_adder = Param(
        m.PERIODS,
        initialize=lambda m, p: sum(
            m.directional_gl_exogenous_cost[gz1, gz2, bldyr]
            * crf(m.interest_rate, m.gas_line_operating_life[gz1, gz2, bldyr]) 
            for (gz1, gz2, bldyr) in m.BLD_YRS_FOR_GAS_D_LINE 
            if bldyr == p),
    )

    ## total nameplate transfer capacity of a gas line in a given period.
    ## This is the sum of existing gas line GENERAL capacity.
    m.GlCapacityNameplate = Expression(
        m.GAS_LINES,
        m.PERIODS,
        rule=lambda m, gl, period: sum(
            m.BuildGl[gl2, bld_yr] +  m.build_general_gl_exo[gl2, bld_yr]- m.gas_line_removed_cap_general[gl2, bld_yr]
            for (gl2, bld_yr) in m.BLD_YRS_FOR_GAS_LINE
            if gl2 == gl and bld_yr <= period
        ),
    )
    ## This is the sum of existing gas line DIRECTIONAL capacity.
    m.DirectionalGlCapacityNameplate = Expression(
        m.DIRECTIONAL_GL,
        m.PERIODS,
        rule=lambda m, zone_from, zone_to, period: sum(
            m.BuildDirectionalGl[zone_from2, zone_to2, bld_yr]
            + m.build_directional_gl_exogenous[zone_from2, zone_to2, bld_yr]
            - m.gas_line_removed_cap_directional[zone_from2, zone_to2, bld_yr]
            for (zone_from2, zone_to2, bld_yr) in m.BLD_YRS_FOR_GAS_D_LINE
            if zone_from2 == zone_from and zone_to2 == zone_to and bld_yr <= period
        ),
    )

    m.Maximum_DirectionalGlCapacity = Constraint(
        m.DIRECTIONAL_GL,
        m.PERIODS,
        rule=lambda m, zone_from, zone_to, period: (
            m.DirectionalGlCapacityNameplate[zone_from, zone_to, period]
            <= m.GlCapacityNameplate[m.gas_d_line[zone_from, zone_to], period]
        ),
    )

    ### Summarize annual costs for the objective function.
    ### Total annual fixed costs of gas lines
    ### Don't add OM cost on general gas line (on directional gas lines only)
    m.GeneralGlFixedCosts = Expression(
        m.PERIODS,
        rule=lambda m, p: sum(
            m.BuildGl[gl, bld_yr]
            * m.gas_line_length[gl]
            * m.general_gas_line_capital_cost[gl]
            * crf(m.interest_rate, m.gas_line_life)
            for (gl, bld_yr) in m.BLD_YRS_FOR_GAS_LINE
            if bld_yr == p
        ),
    )

    m.DirectionalGlFixedCosts = Expression(
        m.PERIODS,
        rule=lambda m, p: sum(
            m.BuildDirectionalGl[zone_from, zone_to, bld_yr]
            * m.gas_line_length[m.gas_d_line[zone_from, zone_to]]
            * (
                m.directional_gas_line_capital_cost[m.gas_d_line[zone_from, zone_to]]
                * (1 + m.gas_line_fixed_om_fraction)
            )
            * crf(m.interest_rate, m.gas_line_life)
            for (zone_from, zone_to, bld_yr) in m.BLD_YRS_FOR_GAS_D_LINE
            if bld_yr == p
        ),
    )

    m.Cost_Components_Per_Period.append("GeneralGlFixedCosts")
    m.Cost_Components_Per_Period.append("DirectionalGlFixedCosts")

    #### GAS STORAGE
    m.GAS_STORAGE_TYPES = Set(dimen=1)
    m.GZ_STORAGE_TYPES = Set(
        dimen=2, ordered=True, initialize=lambda m: m.GAS_ZONES * m.GAS_STORAGE_TYPES
    )
    m.BLD_YRS_FOR_EXISTING_GAS_STORAGE_TYPE = Set(dimen=3)
    m.gas_storage_predet_cap = Param(
        m.BLD_YRS_FOR_EXISTING_GAS_STORAGE_TYPE, within=NonNegativeReals, default=0
    )
    # for states that have no underground storage during 2002-2019,
    #  presume that the ecology characteristics do not allow to build underground storage there.
    m.gas_storage_new_build_allowed = Param(m.GZ_STORAGE_TYPES, within=Boolean)
    m.NEW_GAS_STORAGE_TYPE_BLD_YRS = Set(
        dimen=3,
        initialize=m.GAS_ZONES * m.GAS_STORAGE_TYPES * m.PERIODS,
        filter=lambda m, z, ty, p: m.gas_storage_new_build_allowed[z, ty],
    )
    m.BLD_YRS_FOR_REMOVED_GAS_STORAGE_TYPE = Set(dimen=3)
    m.BLD_YRS_FOR_GAS_STORAGE_TYPE = Set(
        dimen=3,
        ordered=True,
        initialize=lambda m: m.BLD_YRS_FOR_EXISTING_GAS_STORAGE_TYPE
        | m.NEW_GAS_STORAGE_TYPE_BLD_YRS,
    )
    m.gas_storage_removed_cap = Param(
        m.BLD_YRS_FOR_GAS_STORAGE_TYPE, within=NonNegativeReals, default=0
    )

    m.gas_storage_capital_cost = Param(
        m.GZ_STORAGE_TYPES, within=NonNegativeReals, default=39.76
    )
    # working capacity/total capacity: set this to 1 and use working capacity as storage capacity for simplicity
    m.gas_storage_efficiency = Param(
        m.GZ_STORAGE_TYPES, within=PercentFraction, default=1.0
    )
    #  Should be 0.96, but storage fuel loss ratio account for it (0.04).
    m.gas_store_to_release_ratio = Param(
        m.GZ_STORAGE_TYPES, within=PercentFraction, default=1
    )  
    # If don't constraint max number of cycle then set: 
    m.gas_storage_life = Param(m.GAS_STORAGE_TYPES, within=NonNegativeReals, default=50)
    m.gas_storage_max_cycles_per_year = Param(
        m.GAS_STORAGE_TYPES, within=NonNegativeReals, default=float('inf')
    )
    # Valid locations and times for gas infrastructure
    m.GZ_STORAGE_TYPE_PERIODS = Set(
        dimen=3,
        ordered=True,
        initialize=lambda m: m.GAS_ZONES * m.GAS_STORAGE_TYPES * m.PERIODS,
    )

    # how much storage capacity to build
    def bounds_BuildStorage(model, z, ty, bld_yr):
        if (z, ty, bld_yr) in model.BLD_YRS_FOR_EXISTING_GAS_STORAGE_TYPE:
            return (
                model.gas_storage_predet_cap[z, ty, bld_yr],
                model.gas_storage_predet_cap[z, ty, bld_yr],
            )
        else:
            return (0, None)

    m.BuildStorageCap = Var(
        m.BLD_YRS_FOR_GAS_STORAGE_TYPE,
        within=NonNegativeReals,
        bounds=bounds_BuildStorage,
    )

    # Cumulate capacity
    m.GasStorageCapacity = Expression(
        m.GZ_STORAGE_TYPE_PERIODS,
        rule=lambda m, z, ty, period: sum(
            m.BuildStorageCap[z2, ty2, bld_yr]
            - m.gas_storage_removed_cap[z2, ty2, bld_yr]
            for (z2, ty2, bld_yr) in m.BLD_YRS_FOR_GAS_STORAGE_TYPE
            if z2 == z and ty2 == ty and bld_yr <= period
        ),
    )

    # Summarize capital costs of storage for the objective function. (real $ per MMBtu)
    # Calculate fixed costs for all storage capacity come to service in period p
    m.gas_storage_fixed_om_fraction = Param(within=NonNegativeReals, default=0)

    m.GAS_STORAGE_TYPE_BUILDS = Set(
        dimen=2,
        initialize=m.GZ_STORAGE_TYPES,
        filter=lambda m, z, ty: m.gas_storage_new_build_allowed[z, ty],
    )

    m.GasStorageFixedCosts = Expression(
        m.PERIODS,
        rule=lambda m, p: sum(
            m.BuildStorageCap[z, ty, p] 
            * (m.gas_storage_capital_cost[z, ty] * (1 + m.gas_storage_fixed_om_fraction)) 
            * crf(m.interest_rate, m.gas_storage_life[ty])
            for (z, ty) in m.GAS_STORAGE_TYPE_BUILDS
        ),
    )

    m.Cost_Components_Per_Period.append("GasStorageFixedCosts")


def load_inputs(m, gas_switch_data, inputs_dir):
    gas_switch_data.load_aug(
        filename=os.path.join(inputs_dir, 'gas_zones.csv'),
        select=('GAS_ZONES','gas_well_new_build_allowed',),
        index=m.GAS_ZONES,
        param=(
        m.gas_well_new_build_allowed
        )
    )
    gas_switch_data.load_aug(
        filename=os.path.join(inputs_dir, "gas_lines_capital_cost.csv"),
        select=(
            "GAS_LINES",
            "gas_line_gz1",
            "gas_line_gz2",
            "gas_line_length",
            "gas_line_new_build_allowed",
            "general_gas_line_capital_cost_dmmbukm",
            "directional_gas_line_capital_cost_dmmbukm",
        ),
        index=m.GAS_LINES,
        param=(
            m.gas_line_gz1,
            m.gas_line_gz2,
            m.gas_line_length,
            m.gas_line_new_build_allowed,
            m.general_gas_line_capital_cost,
            m.directional_gas_line_capital_cost,
        ),
    )
    gas_switch_data.load_aug(
        filename=os.path.join(inputs_dir, 'gas_line_parameters.csv'),
        select=("gas_line_life","gas_transmission_fuel_cost", "gas_line_fixed_om_fraction"),
        param=(
            m.gas_line_life,
            m.gas_transmission_fuel_cost,
            m.gas_line_fixed_om_fraction
        )
    )
    gas_switch_data.load_aug(
        filename=os.path.join(inputs_dir, "gas_lines_predetermined_general.csv"),
        select=(
            "GAS_LINES",
            "gas_line_predet_build_year",
            "gas_line_predet_cap",
            "gas_line_removed_cap",
        ),
        index=m.BLD_YRS_FOR_EXISTING_GL,
        param=(m.gas_line_predet_cap_general, m.gas_line_removed_cap_general),
    )
    gas_switch_data.load_aug(
        filename=os.path.join(inputs_dir, "gas_lines_predetermined_directional.csv"),
        select=(
            "gas_line_gz1",
            "gas_line_gz2",
            "gas_line_predet_build_year",
            "gas_line_predet_cap",
            "gas_line_removed_cap",
        ),
        index=m.BLD_YRS_FOR_EXISTING_D_GL,
        param=(m.gas_line_predet_cap_directional, m.gas_line_removed_cap_directional),
    )
    gas_switch_data.load_aug(
        filename=os.path.join(inputs_dir, "gas_storage_predetermined.csv"),
        select=(
            "GAS_ZONES",
            "gas_storage_type",
            "gas_storage_predet_build_year",
            "gas_storage_predet_cap",
            "gas_storage_removed_cap",
        ),
        index=m.BLD_YRS_FOR_EXISTING_GAS_STORAGE_TYPE,
        param=(m.gas_storage_predet_cap, m.gas_storage_removed_cap),
    )

    gas_switch_data.load_aug(
        filename=os.path.join(inputs_dir, "gas_storage_capital_cost.csv"),
        select=(
            "GAS_ZONES",
            "gas_storage_type",
            "gas_storage_new_build_allowed",
            "gas_storage_unit_cost_dmmbtu",
            "gas_storage_efficiency",
            "gas_store_to_release_ratio",
        ),
        index=m.GZ_STORAGE_TYPES,
        param=(
            m.gas_storage_new_build_allowed,
            m.gas_storage_capital_cost,
            m.gas_storage_efficiency,
            m.gas_store_to_release_ratio,
        ),
    )
    gas_switch_data.load_aug(
        filename=os.path.join(inputs_dir, "gas_storage_types.csv"),
        select=(
            "gas_storage_type",
            "gas_storage_max_cycles_per_year",
            "gas_storage_life",
            "gas_storage_fuel_cost",
        ),
        index=m.GAS_STORAGE_TYPES,
        param=(
            m.gas_storage_max_cycles_per_year,
            m.gas_storage_life,
            m.gas_storage_fuel_cost,
        ),
    )

    ## INPUTS FOR NETWORK FLOW AND BALANCE
    gas_switch_data.load_aug(
        filename=os.path.join(inputs_dir, "gas_demand.csv"),
        select=(
            "GAS_ZONES",
            "TIMESERIES",
            "DEMAND_SECTORS",
            "gas_ref_price",
            "gas_demand_ref_quantity",
        ),
        param=(m.gas_ref_price, m.gas_demand_ref_quantity),
    )
    
    gas_switch_data.load_aug(
        filename=os.path.join(inputs_dir, "gas_trade.csv"),
        # auto_select=True,
        select=(
            "GAS_ZONES",
            "TIMESERIES",
            "gas_import_ref_quantity",
            "gas_export_ref_quantity",
        ),
        param=(m.gas_import_ref_quantity, m.gas_export_ref_quantity),
    )

    # INPUTS FOR CASE STUDY IF NEEDED
    # Exogenous decisions to build new gas lines in a given period
    ## The capacity of the exogenous gas line build will be integrated into the pipeline network 
    ## for gas flow and balance.
    ## However, the capital cost to build those gas lines will be paid by the RC sector 
    ## in gas zones that are listed in the m.GAS_ZONE_COST_ADDER.
    general_build_file = os.path.join(inputs_dir, "gas_lines_general_build_exogenous.csv")
    if os.path.exists(general_build_file):
        gas_switch_data.load_aug(
            filename=general_build_file,
            select=(
                "GAS_LINES",
                "gas_line_build_year",
                "gas_line_build_cap",
            ),
            param=(m.build_general_gl_exo),
        )

    directional_build_file = os.path.join(inputs_dir, "gas_lines_directional_build_exogenous.csv")
    if os.path.exists(directional_build_file):
        gas_switch_data.load_aug(
            filename=directional_build_file,
            select=(
                "gas_line_gz1",
                "gas_line_gz2",
                "gas_line_build_year",
                "gas_line_build_cap",
                "gas_line_build_cost", 
                "gas_line_operating_life",
            ),
            param=(m.build_directional_gl_exogenous, m.directional_gl_exogenous_cost, m.gas_line_operating_life),
        )

    # Gas zones that have to pay for exogenous gas line build
    zone_cost_adder_file = os.path.join(inputs_dir, "gas_zone_cost_adder.csv")
    if os.path.exists(zone_cost_adder_file):
        gas_switch_data.load_aug(
            filename=zone_cost_adder_file,
            index=m.GAS_ZONE_COST_ADDER,
            param=tuple(),
        )
