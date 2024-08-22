"""
This module calibrates demand data and iterate over the calibration process with two demand sectors
1. Electricity and Industrial (EI) sector: price is defined as marginal cost and variable across timeseries-gaszones
2. Residential and Commercail (RC) sector: flat pricing that make sure to recover all the costs, 
To assess the impact of additional pipeline capacity that is exogenously decided to be built
 (outside the optimal decisions made in the model):
RC price is the average of total marginal cost and 'exogenous pipeline cost' over RC demand in the period
The RC price will vary across gaszones but fixed across timeseries within each period, 
reflecting the flat pricing model that LDCs often use for residential and commercial customers.

Pricing aims to achieve revenue neutrality over the whole system (two sectors) in each period 
(this would leave out the stranded costs of capacity built in the past periods)
"""

from __future__ import print_function
from __future__ import division
import os, sys, time
from pprint import pprint
from pyomo.environ import *
from pyomo.util.infeasible import log_infeasible_constraints

try:
    from pyomo.repn import generate_standard_repn
except ImportError:
    # this was called generate_canonical_repn before Pyomo 5.6
    from pyomo.repn import generate_canonical_repn as generate_standard_repn

import switch_model.utilities as utilities

import util

demand_module = None  # will be set via command-line options

def define_arguments(argparser):
    argparser.add_argument(
        "--dr-flat-pricing",
        action="store_true",
        default=False,
        help="Charge a constant (average) price for Residential and Commercial (RC) sector, "
        "rather than varying day by day as for Electricity and Industry (EI) sector",
    )
    argparser.add_argument(
        "--dr-demand-module",
        default=None,
        help="Name of module to use for demand-response bids. This should also be "
        "specified in the modules list, and should provide calibrate() and bid() functions. "
        "Pre-written options include constant_elasticity_demand_system or r_demand_system. "
        "Specify one of these in the modules list and use --help again to see module-specific options.",
    )

def define_components(m):
    # load scipy.optimize; this is done here to avoid loading it during unit tests
    try:
        global scipy
        import scipy.optimize
    except ImportError:
        print("=" * 80)
        print(
            "Unable to load scipy package, which is used by the demand response system."
        )
        print("Please install this via 'conda install scipy' or 'pip install scipy'.")
        print("=" * 80)
        raise

    ###################
    # Choose the right demand module.
    # NOTE: we assume only one model will be run at a time, so it's safe to store
    # the setting in this module instead of in the model.
    ##################

    global demand_module
    if m.options.dr_demand_module is None:
        raise RuntimeError(
            "No demand module was specified for the demand_response system; unable to continue. "
            "Please use --dr-demand-module <module_name> in options.txt, scenarios.txt or on "
            "the command line. "
            "You should also add this module to the list of modules to load "
            " via modules.txt or --include-module <module_name>."
        )
    if m.options.dr_demand_module not in sys.modules:
        raise RuntimeError(
            "Demand module {mod} cannot be used because it has not been loaded. "
            "Please add this module to the modules list (usually modules.txt) "
            "or specify --include-module {mod} in options.txt, scenarios.txt or "
            "on the command line.".format(mod=m.options.dr_demand_module)
        )
    demand_module = sys.modules[m.options.dr_demand_module]

    # Make sure the model has dual and rc suffixes
    if not hasattr(m, "dual"):
        m.dual = Suffix(direction=Suffix.IMPORT)
    if not hasattr(m, "rc"):
        m.rc = Suffix(direction=Suffix.IMPORT)

    
    ###################
    # RC price markup
    ##################
    m.rc_markup = Param(m.GAS_ZONES, within=NonNegativeReals, default=0.0)

    ###################
    # Price Responsive Demand bids
    ##################

    # List of all bids received from the demand system
    m.DR_BID_LIST = Set(dimen=1, initialize=[], ordered=True)

    # Data for the individual bids; each load_zone gets one bid for each timeseries,
    # So we just record the bid for each timeseries for each gas_zone and demand_sector.
    m.dr_bid = Param(
        m.DR_BID_LIST,
        m.GAS_ZONES,
        m.TIMESERIES,
        m.DEMAND_SECTORS,
        mutable=True,
        within=NonNegativeReals,
    )

    # Price used to get this bid (only kept for reference)
    m.dr_price = Param(
        m.DR_BID_LIST,
        m.GAS_ZONES,
        m.TIMESERIES,
        m.DEMAND_SECTORS,
        mutable=True,
        # in reality, wholesale prices may go negative, so we allow negative prices here
        # for example: https://www.nytimes.com/2024/08/08/business/energy-environment/natural-gas-negative-prices-texas.html
        # If don't want to allow negative prices, one can change the domain to NonNegativeReals
        within=Reals, 
    )

    # The private benefit of serving each bid
    m.dr_bid_benefit = Param(
        m.DR_BID_LIST, m.GAS_ZONES, m.TIMESERIES, m.DEMAND_SECTORS, mutable=True, within=Reals
    )

    # Weights to assign to the bids for each timeseries when constructing an optimal demand profile
    m.DRBidWeight = Var(
        m.DR_BID_LIST, m.GAS_ZONES, m.TIMESERIES, m.DEMAND_SECTORS, within=NonNegativeReals
    )

    # Choose a convex combination of bids for each zone, timeseries, and demand sector
    m.DR_Convex_Bid_Weight = Constraint(
        m.GAS_ZONES,
        m.TIMESERIES,
        m.DEMAND_SECTORS,
        rule=lambda m, z, ts, ds: Constraint.Skip
        if len(m.DR_BID_LIST) == 0
        else (sum(m.DRBidWeight[b, z, ts, ds] for b in m.DR_BID_LIST) == 1),
    )

    # For RC flat-pricing model: flat price for RC sector, i.e. same price for all timeseries within the same period
    # the bid weight needs to be the same for all timeseries within the same year (period)
    # because there is only one price for the whole period, so it can't
    # induce different adjustments in individual timeseries.

    if m.options.dr_flat_pricing:
        m.DR_Flat_Bid_Weight = Constraint(
        m.DR_BID_LIST,
        m.GAS_ZONES,
        m.TIMESERIES,
        m.DEMAND_SECTORS,
        rule=lambda m, b, z, ts, ds: Constraint.Skip
        if ds == 'EI' 
        else m.DRBidWeight[b, z, ts, ds]
        == m.DRBidWeight[b, z, m.tp_ts[m.TPS_IN_PERIOD[m.ts_period[ts]].first()], ds],
    ) 

    # Optimal level of demand, calculated from available bids (negative, indicating consumption)
    m.FlexibleDemand = Expression(
        m.GAS_ZONES,
        m.TIMESERIES,
        m.DEMAND_SECTORS,
        rule=lambda m, z, ts, ds: sum(
            m.DRBidWeight[b, z, ts, ds] * m.dr_bid[b, z, ts, ds] 
            for b in m.DR_BID_LIST 
        ),
    )

    m.FlexibleDemandTotal = Expression(
        m.GAS_ZONES,
        m.TIMESERIES,
        rule=lambda m, z, ts: sum(
            m.FlexibleDemand[z, ts, ds]
            for ds in m.DEMAND_SECTORS
        ),
    )

    # Replace gas_demand_total with FlexibleDemand in the GAS balance constraint
    idx = m.Zone_Gas_Withdrawals.index("gas_demand_total")
    m.Zone_Gas_Withdrawals[idx] = "FlexibleDemandTotal"

    # private benefit of the gas consumption
    # (i.e., willingness to pay for the current gas supply)
    # reported as negative cost, i.e., positive benefit
    # also divide by duration of the timeseries
    # to convert from a cost per timeseries to a cost per timepoint.
    m.DR_Welfare_Cost = Expression(
        m.TIMEPOINTS,
        rule=lambda m, tp: (-1.0)
        * sum(
            m.DRBidWeight[b, z, m.tp_ts[tp], ds] * m.dr_bid_benefit[b, z, m.tp_ts[tp], ds]
            for b in m.DR_BID_LIST
            for z in m.GAS_ZONES
            for ds in m.DEMAND_SECTORS
        )
        / m.ts_duration_hrs[m.tp_ts[tp]],
    )

    # add the private benefit to the model's objective function
    m.Cost_Components_Per_TP.append("DR_Welfare_Cost")

    # variable to store the baseline data
    m.base_data = None


def pre_iterate(m):
    if m.iteration_number == 0:
        m.prev_recoverable_cost = {
            (z, ts, ds): None for z in m.GAS_ZONES for ts in m.TIMESERIES for ds in m.DEMAND_SECTORS
        }
        m.prev_demand = {
            (z, ts, ds): None for z in m.GAS_ZONES for ts in m.TIMESERIES for ds in m.DEMAND_SECTORS
        }
        m.prev_SystemCost = None

    else:
        m.prev_recoverable_cost = {
            (z, ts, ds): gas_marginal_cost(m, z, ts) + 
            ( m.rc_markup[z] if ds == 'RC' else 0.0) +
            (
                # average of the exogenously-built pipeline capacity cost per each MMBtu of RC gas demand occured in the period
                m.gl_cost_adder[m.ts_period[ts]] / total_gas_demand_adder if ds == 'RC' and total_gas_demand_adder != 0 else 0.0
            )
            for z in m.GAS_ZONES
            for ts in m.TIMESERIES
            for ds in m.DEMAND_SECTORS
            for total_gas_demand_adder in [sum((gas_demand(m, z, ts, ds) * m.ts_scale_to_year[ts]) for z in m.GAS_ZONE_COST_ADDER)]
        }
 
        m.prev_demand = {
            (z, ts, ds): gas_demand(m, z, ts, ds)
            for z in m.GAS_ZONES
            for ts in m.TIMESERIES
            for ds in m.DEMAND_SECTORS
        }
        m.prev_SystemCost = value(m.SystemCost)

        # print("=======================================================")
        # print("Gas marginal costs and recoverable costs")
        # print("Gas marginal cost: $ {c}".format(c=gas_marginal_cost(m, 'MD', 20250101)))
        # print("recoverable cost, i.e. prev_recoverable_cost: {c}".format(c=m.prev_recoverable_cost['MD', 20250101, 'RC']))
        # print("prev_demand: {d}".format(d=m.prev_demand['MD', 20250101, 'RC']))
        # print("=======================================================")

    if m.iteration_number > 0:

        prev_direct_cost = sum(
            m.prev_recoverable_cost[z, ts, ds] * m.prev_demand[z, ts, ds]
            * m.ts_scale_to_year[ts]
            * m.bring_annual_costs_to_base_year[m.ts_period[ts]] 
            for z in m.GAS_ZONES
            for ts in m.TIMESERIES
            for ds in m.DEMAND_SECTORS
        )

        prev_direct_cost = value(prev_direct_cost)

        prev_welfare_cost = value(
            sum(
                m.DR_Welfare_Cost[tp] * m.bring_timepoint_costs_to_base_year[tp]
                for tp in m.TIMEPOINTS
            )
        )
        prev_cost = prev_direct_cost + prev_welfare_cost 

        print("")
        print("previous direct cost: ${:,.0f}".format(prev_direct_cost))
        print("previous welfare cost: ${:,.0f}".format(prev_welfare_cost))
        print("")

    update_demand(m)

    if m.iteration_number > 0:
        b = m.DR_BID_LIST.last()

        best_direct_cost = sum(
            (m.prev_recoverable_cost[z, ts, ds] * m.dr_bid[b, z, ts, ds]
             * m.ts_scale_to_year[ts]
             * m.bring_annual_costs_to_base_year[m.ts_period[ts]]
             for z in m.GAS_ZONES
            for ts in m.TIMESERIES
            for ds in m.DEMAND_SECTORS
            )
        )
        best_direct_cost = value(best_direct_cost)

        best_bid_benefit = value(
            sum(
                -sum(m.dr_bid_benefit[b, z, ts, ds] for ds in m.DEMAND_SECTORS for z in m.GAS_ZONES)
                * m.ts_scale_to_year[ts]
                * m.bring_annual_costs_to_base_year[m.ts_period[ts]]
                for ts in m.TIMESERIES
            )
        )
        best_cost = best_direct_cost + best_bid_benefit 

        print("")
        print("best direct cost: ${:,.0f}".format(best_direct_cost))
        print("best bid benefit: ${:,.0f}".format(best_bid_benefit))
        print("")

        print(
            "lower bound=${:,.0f}, previous cost=${:,.0f}, optimality gap (vs direct cost)={}".format(
                best_cost, prev_cost, (prev_cost - best_cost) / abs(prev_direct_cost)
            )
        )
        if prev_cost < best_cost:
            print(
                "WARNING: final cost is below reported lower bound; "
                "there is probably a problem with the demand system."
            )

    converged = (
        m.iteration_number > 0
        and abs(prev_cost - best_cost) / abs(prev_direct_cost) <= 0.0001
    )

    return converged

def post_iterate(m):
    print("\n\n=======================================================")
    print("Solved model")
    print("=======================================================")
    print("Total cost: ${v:,.0f}".format(v=value(m.SystemCost)))

    SystemCost = value(m.SystemCost)  # calculate once to save time
    if m.prev_SystemCost is None:
        print("prev_SystemCost=<n/a>, SystemCost={:,.0f}, ratio=<n/a>".format(SystemCost))
    else:
        print("prev_SystemCost={:,.0f}, SystemCost={:,.0f}, ratio={}".format(
            m.prev_SystemCost, SystemCost, SystemCost / m.prev_SystemCost
        ))

    tag = filename_tag(m, include_iter_num=False)
    outputs_dir = m.options.outputs_dir

    # Report information on the most recent bid
    if m.iteration_number == 0:
        util.create_table(
            output_file=os.path.join(outputs_dir, f"bid{tag}.csv"),
            headings=(
                "bid_num",
                "gas_zone",
                "timeseries",
                "sector",
                "marginal_cost",
                "price",
                "bid",
                "wtp",
                "base_price",
                "base_load",
            ),
        )
    b = m.DR_BID_LIST.last()  # current bid
    util.append_table(
        m,
        m.GAS_ZONES,
        m.TIMESERIES,
        m.DEMAND_SECTORS,
        output_file=os.path.join(outputs_dir, f"bid{tag}.csv"),
        values=lambda m, z, ts, ds: ( 
            b,
            z,
            ts,
            ds,
            m.prev_recoverable_cost[z, ts, ds],
            m.dr_price[b, z, ts, ds],
            m.dr_bid[b, z, ts, ds],
            m.dr_bid_benefit[b, z, ts, ds],
            m.base_data_dict[z, ts, ds][1],
            m.base_data_dict[z, ts, ds][0],
        ),
    )

    # Store the current bid weights for future reference
    if m.iteration_number == 0:
        util.create_table(
            output_file=os.path.join(outputs_dir, f"bid_weights{tag}.csv"),
            headings=("iteration", "gas_zone", "timeseries", "sector", "bid_num", "weight"),
        )
    util.append_table(
        m,
        m.GAS_ZONES,
        m.TIMESERIES,
        m.DEMAND_SECTORS,
        m.DR_BID_LIST,
        output_file=os.path.join(outputs_dir, f"bid_weights{tag}.csv"),
        values=lambda m, z, ts, ds, b: (
            len(m.DR_BID_LIST),
            z,
            ts,
            ds,
            b,
            m.DRBidWeight[b, z, ts, ds],
        ),
    )

    # Stop if there are no duals. This is an efficient point to check, and
    # otherwise the errors later are pretty cryptic.
    if not m.dual:
        raise RuntimeError(
            "No dual values have been calculated. Check that your solver is "
            "able to provide duals for integer programs. If using cplex, you "
            "may need to specify --retrieve-cplex-mip-duals."
        )

    write_results(m)
    write_batch_results(m)

def update_demand(m):
    """
    This should be called after solving the model, in order to calculate new bids
    to include in future runs. The first time through, it also uses the fixed demand
    and marginal costs to calibrate the demand system, and then replaces the fixed
    demand with the flexible demand system.
    """
    first_run = m.base_data is None

    print("attaching new demand bid to model")
    if first_run:
        calibrate_model(m)
    else:
        if m.options.verbose and len(m.GAS_ZONES) * len(m.TIMESERIES) <= 20:
            print("m.DRBidWeight:")
            pprint(
                [
                    (
                        z,
                        ts,
                        ds,
                        [(b, value(m.DRBidWeight[b, z, ts, ds])) for b in m.DR_BID_LIST],
                    )
                    for z in m.GAS_ZONES
                    for ts in m.TIMESERIES
                    for ds in m.DEMAND_SECTORS
                ]
            )

    # get new bids from the demand system at the current prices
    bids = get_bids(m)

    # add the new bids to the model
    if m.options.verbose:
        print("adding bids to model")
        print("first day (z, ts, ds, prices, demand, wtp) =")
        pprint(bids[0]) #print the first demand sector of first bid
        pprint(bids[1]) # print the second demand sector of first bid as well
    add_bids(m, bids)

    log_infeasible_constraints(m)


def total_direct_costs_per_year(m, period):
    """Return undiscounted total cost per year, during each period, as calculated by Switch,
    including everything except DR_Welfare_Cost.

    This code comes from financials.calc_sys_costs_per_period(), excluding discounting
    and upscaling to the period.
    """
    return value(
        sum(
            getattr(m, annual_cost)[period]
            for annual_cost in m.Cost_Components_Per_Period
        )
        + sum(
            getattr(m, tp_cost)[t] * m.tp_weight_in_year[t]
            for t in m.TPS_IN_PERIOD[period]
            for tp_cost in m.Cost_Components_Per_TP
            if tp_cost != "DR_Welfare_Cost"
        )
    )

def gas_marginal_cost(m, z, ts):
    """Return marginal cost of providing natural gas in gas_zone z during timeseries ts."""
    component = m.Zone_Gas_Balance[z, ts]
    return m.dual[component] / (
            m.bring_annual_costs_to_base_year[m.ts_period[ts]] * m.ts_scale_to_year[ts]
        )

def gas_demand(m, z, ts, ds):
    """Return total consumption of natural gas in gas_zone z during timeseries ts for a specific demand sector ds."""
    if len(m.DR_BID_LIST) == 0:
        # use gas_demand_ref_quantity (base demand) if no bids have been received yet
        # (needed to find flat prices before solving the model the first time)
        demand = m.gas_demand_ref_quantity[z, ts, ds]
    else:
        demand = m.FlexibleDemand[z, ts, ds]
    return value(demand)

def calibrate_model(m):
    """
    Calibrate the demand system and add it to the model.
    """
    # base_data consists of a list of tuples showing (gas_zone, timeseries, demand_sector, base_load (list), and base_price)
    m.base_data = [
        (
            z,
            ts,
            ds,
            [m.gas_demand_ref_quantity[z, ts, ds]],
            [m.gas_ref_price[z, ts, ds]],
        )
        for z in m.GAS_ZONES
        for ts in m.TIMESERIES
        for ds in m.DEMAND_SECTORS
    ]

    # make a dict of base_data, indexed by gas_zone, timeseries, and demand_sector for later reference
    m.base_data_dict = {
        (z, ts, ds): (m.gas_demand_ref_quantity[z, ts, ds], m.gas_ref_price[z, ts, ds])
        for z in m.GAS_ZONES
        for ts in m.TIMESERIES
        for ds in m.DEMAND_SECTORS
    }

    # calibrate the demand module
    demand_module.calibrate(m, m.base_data)


def get_prices(m, revenue_neutral=True):
    """Calculate appropriate prices for each day, based on the current state of the model."""
    cost_adder = dict()
    # Calculate cost-adder for RC sector for each gas zone that served by the exogenously built pipeline
    for z in m.GAS_ZONES:
        for p in m.PERIODS: 
            if z in m.GAS_ZONE_COST_ADDER:
                # Calculate total RC gas demand for the period p
                total_gas_demand_adder = sum(
                    (gas_demand(m, z, ts, 'RC') * m.ts_scale_to_year[ts])
                    for z in m.GAS_ZONE_COST_ADDER 
                    for ts in m.TS_IN_PERIOD[p]
                )
                # Cost-adder is average of the exogenously-built pipeline capacity cost per each MMBtu of RC gas demand occured in the period p
                ## TODO: double check whether need to include conversion from annual costs to base year 
                # (maybe not since the total cost will be converted to base year later):
                # * m.bring_annual_costs_to_base_year[p]
                cost_adder[z, p] = (m.gl_cost_adder[p] / total_gas_demand_adder) if total_gas_demand_adder != 0 else 0.0
            else:
                # No cost adder for those gas zones that are not served by the exogenously built pipeline
                cost_adder[z, p] = 0.0

    if m.iteration_number == 0:
        # Base prices for the first pass
        recoverable_cost = {
            (z, ts, ds): [m.base_data_dict[z, ts, ds][1]]  # one price per timeseries
            for z in m.GAS_ZONES
            for ts in m.TIMESERIES
            for ds in m.DEMAND_SECTORS  
        }
    else:
        # Use marginal costs from the last solution with sector-specific adders
        recoverable_cost = {
            (z, ts, ds): [gas_marginal_cost(m, z, ts) + 
                          (m.rc_markup[z] if ds == 'RC' else 0.0) +
                          (cost_adder[z, m.ts_period[ts]] if ds == 'RC' else 0)]  # # one price per timeseries
            for z in m.GAS_ZONES
            for ts in m.TIMESERIES
            for ds in m.DEMAND_SECTORS
        }

    if m.options.dr_flat_pricing:
        prices = find_flat_prices(m, recoverable_cost, revenue_neutral)
    else:
        prices = recoverable_cost
    return prices

def get_bids(m):
    """Get bids from the demand system showing quantities at the current prices and willingness-to-pay for those quantities.
    Call bid() with dictionary of prices for different products.

    Each bid is a tuple of (load_zone, timeseries, demand_sector, price, demand, wtp).
    Quantity will be positive for consumption, negative if customer will supply product.
    """
    prices = get_prices(m)

    bids = []
    for z in m.GAS_ZONES:
        for ts in m.TIMESERIES:
            for sector in m.DEMAND_SECTORS:
                demand, wtp = demand_module.bid(m, z, ts, prices[z, ts][sector], sector) # demand is a list (array) of daily quantities by sector
                bids.append((z, ts, sector, prices[z, ts][sector], demand[0], wtp))
    return bids

# Revenue neautrality over the whole system (two sectors) in each period
def find_flat_prices(m, recoverable_cost, revenue_neutral):
    flat_prices = dict()
    marginal_prices = dict()
   
    for z in m.GAS_ZONES:
        for p in m.PERIODS:
            # if the marginal cost is negative, the price guess can be negative
            rc_price_guess = value( 
                (
                 sum(
                     recoverable_cost[z, ts, 'RC'][0] * gas_demand(m, z, ts, 'RC') * m.ts_scale_to_year[ts]
                     for ts in m.TS_IN_PERIOD[p]
                )) / sum(
                    gas_demand(m, z, ts, 'RC') * m.ts_scale_to_year[ts]
                    for ts in m.TS_IN_PERIOD[p]
                )
            )
            print(f"rc_price_guess for {z},{p}: {rc_price_guess}")

            if revenue_neutral:
                # Find flat price for residential sector ensuring revenue neutrality
                # using rc_price_guess as initial guess
                flat_prices[z, p] = scipy.optimize.newton(
                    revenue_imbalance, rc_price_guess, args=(m, z, p, recoverable_cost) 
                )
                # # if want to force the price to be non-negative, one may use the following alternative code
                # flat_prices[z, p] = max(
                #     0, scipy.optimize.newton(
                #         revenue_imbalance, rc_price_guess, args=(m, z, p, recoverable_cost)
                #         )
                # )
            else:
                # used in final round, when LSE is considered to have
                # bought the final constructed quantity at the final (recoverable)marginal cost
                flat_prices[z, p] = rc_price_guess
            
            # Calculate variable prices for industrial sector for each timeseries
            # Use the marginal cost as a base (and adjust if necessary)
            for ts in m.TS_IN_PERIOD[p]:
                marginal_prices[z, ts] = recoverable_cost[z, ts, 'EI'][0]
                
    # Construct the final prices dictionary
    final_prices = {
        (z, ts): {
            'RC': flat_prices[z, p],  # Residential-Commercial sector price, same for the period
            'EI': marginal_prices[z, ts]  # Electricity-Industrial sector price, variable
        }
        for z in m.GAS_ZONES
        for p in m.PERIODS
        for ts in m.TS_IN_PERIOD[p]
    }
    return final_prices

def revenue_imbalance(flat_price_rc, m, gas_zone, period, recoverable_cost):
    """
    Calculate the revenue imbalance given a flat residential price and
    variable industrial prices for each timeseries within a period.
    """
    flat_price_revenue_rc = 0.0
    marginal_price_revenue_ei = 0.0
    dynamic_revenue_rc = 0.0
    dynamic_revenue_ei = 0.0
    
    # Iterate over all timeseries in the period
    for ts in m.TS_IN_PERIOD[period]:
        # Residential sector
        price_rc = [flat_price_rc][0] #one price per timeseries
        demand_rc, _ = demand_module.bid(m, gas_zone, ts, price_rc, 'RC')
        
        flat_price_revenue_rc += flat_price_rc * sum(
            d * m.ts_scale_to_year[ts] for d in demand_rc
        )

        # Industrial sector
        prices_ei = [recoverable_cost[gas_zone, ts, 'EI'][0]] #one price per timeseries
        demand_ei, _ = demand_module.bid(m, gas_zone, ts, prices_ei, 'EI')
        
        marginal_price_revenue_ei += sum(p * d * m.ts_scale_to_year[ts] 
                                         for p, d in zip(prices_ei, demand_ei))
       
        # Calculate dynamic total revenue that should recover all costs to be revenue neutral
        dynamic_revenue_rc += sum(
            p_rc * d_rc * m.ts_scale_to_year[ts]
            for p_rc, d_rc in zip(recoverable_cost[gas_zone, ts, 'RC'], demand_rc)
        ) 
        dynamic_revenue_ei += sum(
            p_ei * d_ei * m.ts_scale_to_year[ts]
            for p_ei, d_ei in zip(recoverable_cost[gas_zone, ts, 'EI'], demand_ei)
        )
    
    # Calculate the total revenue and the target revenue
    total_revenue = flat_price_revenue_rc + marginal_price_revenue_ei
    # At equilibrium, the total marginal cost should be equal to the total system cost per period
    ## In case we include the cost adder in the RC price, the dynamic revenue then includes 
    # the fixed costs of exogenous pipeline capacity and the total marginal cost, 
    # which is the total of recoverable cost across all zones and timeseries in the period
    dynamic_total_revenue = dynamic_revenue_rc + dynamic_revenue_ei 

    imbalance = dynamic_total_revenue - total_revenue

    # print(
    #     "{}, {}: flat residential price ${} and variable industrial prices produce revenue imbalance of ${}/year".format(
    #         gas_zone, ts, price_rc, imbalance
    #     )
    # )

    return imbalance

def reconstruct(component):
    # reconstruct component, following advice from pyomo/core/base/component.py:538 in Pyomo 6.4.2
    # (.reconstruct method was removed in Pyomo 6.0)
    component.clear()
    component._constructed = False
    component.construct()


def add_bids(m, bids):
    """
    Accept a list of bids written as tuples like
    (z, ts, sector, prices, demand, wtp)
    where z is the gas zone, ts is the timeseries, sector is either 'RC' or 'EI',
    prices is a list of prices for the sector,
    demand is a scalar value representing total demand for the timepoints during that series,
    and wtp is the net private benefit from consuming/selling the amount of gas in that bid.
    Then add that set of bids to the model.
    """
    # Determine the new bid ID
    if len(m.DR_BID_LIST) == 0:
        b = 1
    else:
        b = max(m.DR_BID_LIST) + 1

    # Check for non-convexity
    non_convex_pairs = []
    for z, ts, sector, prices, demand, wtp in bids:
        for prior_b in m.DR_BID_LIST:
            prior_wtp = value(m.dr_bid_benefit[prior_b, z, ts, sector])
            prior_demand = value(m.dr_bid[prior_b, z, ts, sector])
            prior_price = value(m.dr_price[prior_b, z, ts, sector])
            if (
                prior_wtp - prior_demand * prices
                > wtp - demand * prices + 0.000001
            ):
                non_convex_pairs.append(
                    f"zone {z}, timeseries {ts}, sector {sector}: "
                    f"bid #{prior_b} (made for price {prior_price}) gives more "
                    f"net benefit than bid #{b} at price {prices}: "
                    f"{prior_wtp} - {prior_demand} * {prices} > {wtp} - {demand} * {prices}"
                )

    if non_convex_pairs:
        raise ValueError(
            f'Non-convex bid{"s" if len(non_convex_pairs) > 1 else ""} received:\n'
            + "\n".join(non_convex_pairs)
            + "\n\nThese indicate non-convexity in the demand bidding function that "
            + "will prevent the model from converging."
        )

    # Extend the list of bids
    m.DR_BID_LIST.add(b)

    # Add the bids for each gas zone, timeseries, and sector to the dr_bid list
    for z, ts, sector, prices, demand, wtp in bids:
        m.dr_bid_benefit[b, z, ts, sector] = wtp
        m.dr_bid[b, z, ts, sector] = demand
        m.dr_price[b, z, ts, sector] = prices 

    print("len(m.DR_BID_LIST): {l}".format(l=len(m.DR_BID_LIST)))
    print("m.DR_BID_LIST: {b}".format(b=[x for x in m.DR_BID_LIST]))

    # Reconstruct or update components that depend on DR_BID_LIST
    reconstruct(m.DRBidWeight)
    reconstruct(m.DR_Convex_Bid_Weight)
    if hasattr(m, "DR_Flat_Bid_Weight"):
        reconstruct(m.DR_Flat_Bid_Weight)
    reconstruct(m.FlexibleDemand)
    reconstruct(m.FlexibleDemandTotal)
    reconstruct(m.DR_Welfare_Cost)
    reconstruct(m.Zone_Gas_Balance)
    if hasattr(m, "Aggregate_Spinning_Reserve_Details"):
        reconstruct(m.Aggregate_Spinning_Reserve_Details)
    if hasattr(m, "Satisfy_Spinning_Reserve_Up_Requirement"):
        reconstruct(m.Satisfy_Spinning_Reserve_Up_Requirement)
        reconstruct(m.Satisfy_Spinning_Reserve_Down_Requirement)
    reconstruct(m.SystemCostPerPeriod)
    reconstruct(m.SystemCost)

def reconstruct_gas_balance(m):
    """Reconstruct Energy_Balance constraint, preserving dual values (if present)."""
    # copy the existing Energy_Balance object
    old_Gas_Balance = dict(m.Zone_Gas_Balance)
    reconstruct(m.Zone_Gas_Balance)
    # TODO: now that this happens just before a solve, there may be no need to
    # preserve duals across the reconstruct().
    if m.iteration_number > 0:
        for k in old_Gas_Balance:
            # change dual entries to match new Gas_Balance objects
            m.dual[m.Zone_Gas_Balance[k]] = m.dual.pop(old_Gas_Balance[k])

def write_batch_results(m):
    # append results to the batch results file, creating it if needed
    output_file = os.path.join(m.options.outputs_dir, "demand_response_summary.csv")

    # create a file to hold batch results if it doesn't already exist
    # note: we retain this file across scenarios so it can summarize all results,
    # but this means it needs to be manually cleared before launching a new
    # batch of scenarios (e.g., when running get_scenario_data or clearing the
    # scenario_queue directory)
    if not os.path.isfile(output_file):
        util.create_table(output_file=output_file, headings=summary_headers(m))

    util.append_table(m, output_file=output_file, values=lambda m: summary_values(m))


def summary_headers(m):
    return (
        ("tag", "iteration", "total_cost")
        + tuple("total_direct_costs_per_year_" + str(p) for p in m.PERIODS)
        + tuple("DR_Welfare_Cost_" + str(p) for p in m.PERIODS)
        + tuple("payment " + str(ds) + str(p) for ds in m.DEMAND_SECTORS for p in m.PERIODS)
        + tuple("gas sold " + str(ds) + str(p) for ds in m.DEMAND_SECTORS for p in m.PERIODS)
    )

def summary_values(m):
    demand_components = [
        c for c in ("gas_demand_total", "FlexibleDemandTotal") if hasattr(m, c) #consider separating RC and EI demand
    ]
    values = []

    # Tag (configuration)
    values.extend(
        [
            m.options.scenario_name,
            m.iteration_number,
            # total cost (all periods) at base-year dollar value
            m.SystemCost + sum(m.gl_cost_adder[p] * m.bring_annual_costs_to_base_year[p] for p in m.PERIODS),  
        ]
    )

    # Direct costs (including "other") (excluding discounting and upscaling to the period)
    values.extend([(total_direct_costs_per_year(m, p) + m.gl_cost_adder[p]) for p in m.PERIODS])

    # DR_Welfare_Cost
    values.extend(
        [
            sum(
                m.DR_Welfare_Cost[tp] * m.ts_scale_to_year[m.tp_ts[tp]]
                for tp in m.TPS_IN_PERIOD[p]
            )
            for p in m.PERIODS
        ]
    )

    # Payments by customers (RC and EI sectors separately)
    b = m.DR_BID_LIST.last()
    for sector in m.DEMAND_SECTORS:
        values.extend(
            [
                sum(
                    # gas_demand(m, z, ts, sector)
                    m.dr_bid[b, z, ts, sector]
                    * m.dr_price[b, z, ts, sector]
                    * m.ts_scale_to_year[ts]
                    for z in m.GAS_ZONES
                    for ts in m.TS_IN_PERIOD[p]
                )
                for p in m.PERIODS
            ]
        )

    # Total quantities bought (or sold) by customers each year (RC and EI sectors separately)
    for sector in m.DEMAND_SECTORS:
        values.extend(
            [
                sum(
                    gas_demand(m, z, ts, sector) * m.ts_scale_to_year[ts]
                    for z in m.GAS_ZONES
                    for ts in m.TS_IN_PERIOD[p]
                )
                for p in m.PERIODS
            ]
        )

    return values

def get(component, idx, default):
    try:
        return component[idx]
    except KeyError:
        return default

# def future_to_present_value(dr, t):
#     """
#     Returns a coefficient to convert money from some future value to
#     t-years previously, with an annual discount rate of dr.
#     Example:
#     >>> round(future_to_present_value(.07,10),7)
#     0.5083493
#     """
#     return (1 + dr) ** -t

def write_results(m, include_iter_num=True):
    outputs_dir = m.options.outputs_dir
    tag = filename_tag(m, include_iter_num)

    # avg_ts_scale = float(sum(m.ts_scale_to_year[ts] for ts in m.TIMESERIES)) / len(
    #     m.TIMESERIES
    # )
    last_bid = m.DR_BID_LIST.last()

    # Store value of cost_adder for each gas zone and period
    cost_adder= {
        (z, p): value(
            #if want to get real-dollar value: (m.gl_cost_adder[p] * m.bring_annual_costs_to_base_year[p])
            (m.gl_cost_adder[p]) / total_dr_bid_adder 
            if z in m.GAS_ZONE_COST_ADDER and total_dr_bid_adder != 0 else 0.0
        )
        for z in m.GAS_ZONES
        for p in m.PERIODS
        for total_dr_bid_adder in [value(sum(
            m.dr_bid[last_bid, z, ts, 'RC'] * m.ts_scale_to_year[ts] 
            for z in m.GAS_ZONE_COST_ADDER 
            for ts in m.TS_IN_PERIOD[p])
        )]
    }

    # Get final prices that will be charged to customers (not necessarily
    # the same as the final prices they were offered, if iteration was
    # stopped before complete convergence)
    final_prices_by_timeseries = get_prices(m, revenue_neutral=True)
    final_prices = {
        (z, ts): final_prices_by_timeseries[z, ts]
        for z in m.GAS_ZONES
        for ts in m.TIMESERIES
    }
    final_quantities = {
        (z, ts): {
            sector: value(
                sum(m.DRBidWeight[b, z, ts, sector] * m.dr_bid[b, z, ts, sector] for b in m.DR_BID_LIST)
            )
            for sector in m.DEMAND_SECTORS
        }
        for z in m.GAS_ZONES
        for ts in m.TIMESERIES
    }
    # for z in m.GAS_ZONES:
    #     for t in m.TIMESERIES:
    #         print("Debugging: verify the types and values of final prices and quantities")
    #         print(final_prices[z, t])
    #         print(type(final_prices[z, t]['RC'])) 
    #         print(type(final_quantities[z, t]['RC'])) 

    util.write_table(
        m,
        m.GAS_ZONES,
        m.TIMESERIES,
        output_file=os.path.join(outputs_dir, f"gas_sources{tag}.csv"),
        headings=("gas_zone", "period", "timeseries")
        + tuple(m.Zone_Gas_Injections)
        + tuple(m.Zone_Gas_Withdrawals)
        + tuple("offered price " + str(ds) for ds in m.DEMAND_SECTORS)
        + tuple("bid q " + str(ds) for ds in m.DEMAND_SECTORS)
        + ("final mc", "cost_adder")
        + tuple("final price " + str(ds) for ds in m.DEMAND_SECTORS)
        + tuple("final q " + str(ds) for ds in m.DEMAND_SECTORS)
        # + ("peak_day")
        + tuple("base_load " + str(ds) for ds in m.DEMAND_SECTORS)
        + tuple("base_price " + str(ds) for ds in m.DEMAND_SECTORS),
        values=lambda m, z, t: (z, m.ts_period[t], t)
        + tuple(getattr(m, component)[z, t] for component in m.Zone_Gas_Injections)
        + tuple(getattr(m, component)[z, t] for component in m.Zone_Gas_Withdrawals)
        + tuple(m.dr_price[last_bid, z, t, ds] for ds in m.DEMAND_SECTORS)
        + tuple(m.dr_bid[last_bid, z, t, ds] for ds in m.DEMAND_SECTORS)
        +(gas_marginal_cost(m, z, t), #should also record the fixed cost adder and average fixed cost by period
          cost_adder[z, m.ts_period[t]],)
        + tuple(final_prices[z, t][ds] for ds in m.DEMAND_SECTORS)
        + tuple(final_quantities[z, t][ds] for ds in m.DEMAND_SECTORS)
        # + ("peak" if m.ts_scale_to_year[t] < 0.5 * avg_ts_scale else "typical")
        + tuple(m.base_data_dict[z, t, ds][0] for ds in m.DEMAND_SECTORS)
        + tuple(m.base_data_dict[z, t, ds][1] for ds in m.DEMAND_SECTORS),
    )
    # util.write_table(
    #     m,
    #     m.GAS_ZONES,
    #     m.TIMESERIES,
    #     output_file=os.path.join(outputs_dir, f"gas_sources{tag}.csv"),
    #     headings=("gas_zone", "period", "timeseries")
    #     + tuple(m.Zone_Gas_Injections)
    #     + tuple(m.Zone_Gas_Withdrawals)
    #     + ("offered price (RC)", "bid q (RC)", "offered price (EI)", "bid q (EI)", 
    #        "final mc", "cost_adder", 
    #        "final price (RC)", "final q (RC)", "final price (EI)", "final q (EI)")
    #     + (
    #         # "peak_day", 
    #         "base_load (RC)", "base_price (RC)", "base_load (EI)", "base_price (EI)"),
    #     values=lambda m, z, t: (z, m.ts_period[t], t)
    #     + tuple(getattr(m, component)[z, t] for component in m.Zone_Gas_Injections)
    #     + tuple(getattr(m, component)[z, t] for component in m.Zone_Gas_Withdrawals)
    #     + (
    #         m.dr_price[last_bid, z, t, 'RC'],
    #         m.dr_bid[last_bid, z, t, 'RC'],
    #         m.dr_price[last_bid, z, t, 'EI'],
    #         m.dr_bid[last_bid, z, t, 'EI'],
    #         gas_marginal_cost(m, z, t), #should also record the fixed cost adder and average fixed cost by period
    #         cost_adder_real[z, m.ts_period[t]],
    #         final_prices[z, t]['RC'], #extract the scalar value from the list
    #         final_quantities[z, t]['RC'],
    #         final_prices[z, t]['EI'], #extract the scalar value from the list
    #         final_quantities[z, t]['EI'],
    #     )
    #     + (
    #         # "peak" if m.ts_scale_to_year[t] < 0.5 * avg_ts_scale else "typical",
    #         m.base_data_dict[z, t, 'RC'][0],
    #         m.base_data_dict[z, t, 'RC'][1],
    #         m.base_data_dict[z, t, 'EI'][0],
    #         m.base_data_dict[z, t, 'EI'][1],
    #     ),
    # )

def write_dual_costs(m, include_iter_num=True):
    outputs_dir = m.options.outputs_dir
    tag = filename_tag(m, include_iter_num)

    outfile = os.path.join(outputs_dir, "dual_costs{t}.csv".format(t=tag))
    dual_data = []
    start_time = time.time()
    print("Writing {} ... ".format(outfile), end=" ")

    def add_dual(const, lbound, ubound, duals, prefix="", offset=0.0):
        if const in duals:
            dual = duals[const]
            if dual >= 0.0:
                direction = ">="
                bound = lbound
            else:
                direction = "<="
                bound = ubound
            if bound is None:
                # Variable is unbounded; dual should be 0.0 or possibly a tiny non-zero value.
                if not (-1e-5 < dual < 1e-5):
                    raise ValueError(
                        "{} has no {} bound but has a non-zero dual value {}.".format(
                            const.name, "lower" if dual > 0 else "upper", dual
                        )
                    )
            else:
                total_cost = dual * (bound + offset)
                if total_cost != 0.0:
                    dual_data.append(
                        (
                            prefix + const.name,
                            direction,
                            (bound + offset),
                            dual,
                            total_cost,
                        )
                    )

    for comp in m.component_objects(ctype=Var):
        for idx in comp:
            var = comp[idx]
            if var.value is not None:  # ignore vars that weren't used in the model
                if var.is_integer() or var.is_binary():
                    # integrality constraint sets upper and lower bounds
                    add_dual(var, value(var), value(var), m.rc, prefix="integer: ")
                else:
                    add_dual(var, var.lb, var.ub, m.rc)
    for comp in m.component_objects(ctype=Constraint):
        for idx in comp:
            constr = comp[idx]
            if constr.active:
                offset = 0.0
                # cancel out any constants that were stored in the body instead of the bounds
                # (see https://groups.google.com/d/msg/pyomo-forum/-loinAh0Wx4/IIkxdfqxAQAJ)
                standard_constraint = generate_standard_repn(constr.body)
                if standard_constraint.constant is not None:
                    offset = -standard_constraint.constant
                add_dual(
                    constr,
                    value(constr.lower),
                    value(constr.upper),
                    m.dual,
                    offset=offset,
                )

    dual_data.sort(key=lambda r: (not r[0].startswith("DR_Convex_"), r[3] >= 0) + r)

    with open(outfile, "w") as f:
        f.write(
            ",".join(["constraint", "direction", "bound", "dual", "total_cost"]) + "\n"
        )
        f.writelines(",".join(map(str, r)) + "\n" for r in dual_data)
    print("time taken: {dur:.2f}s".format(dur=time.time() - start_time))


def filename_tag(m, include_iter_num=True):
    tag = ""
    if m.options.scenario_name:
        tag += "_" + m.options.scenario_name
    if include_iter_num:
        if m.options.max_iter is None:
            n_digits = 4
        else:
            n_digits = len(str(m.options.max_iter))
        tag += "".join(f"_{t:0{n_digits}d}" for t in m.iteration_node)
    return tag


def post_solve(m, outputs_dir):
    # report final results, possibly after smoothing,
    # and without the iteration number
    write_dual_costs(m, include_iter_num=False)
    write_results(m, include_iter_num=False)

def load_inputs(m, gas_switch_data, inputs_dir):
    gas_switch_data.load_aug(
        filename=os.path.join(inputs_dir, 'RC_price_markup.csv'),
        select=('GAS_ZONES','RC_price_markup',),
        index=m.GAS_ZONES,
        param=(
        m.rc_markup,
        )
    )