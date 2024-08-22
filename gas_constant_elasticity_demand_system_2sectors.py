from __future__ import division


def calibrate(m, base_data, dr_elasticity_scenario=3):
    """Accept a list of tuples showing [base hourly loads], and [base hourly prices] for each
    location (load_zone) and date (time_series). Store these for later reference by bid().
    """
    # import numpy; we delay till here to avoid interfering with unit tests
    global np
    import numpy as np

    global base_load_dict, base_price_dict, elasticity_scenario
    # build dictionaries (indexed lists) of base loads (quantities) and prices
    # store the load and price vectors as numpy arrays (vectors) for faste calculation later
    base_load_dict = {
        (z, ts, ds): np.array(base_loads, float)
        for (z, ts, ds, base_loads, base_prices) in base_data
    }
    base_price_dict = {
        (z, ts, ds): np.array(base_prices, float)
        for (z, ts, ds, base_loads, base_prices) in base_data
    }
    elasticity_scenario = dr_elasticity_scenario

def bid(m, gas_zone, time_series, sector_price, sector):
    """Accept a vector of current prices for a particular location (gas_zone) and day (timeseries).
    Return a tuple showing total demand quantity levels and willingness to pay for those quantities 
    (relative to the quantities achieved at the base_price) for both residential (RC) and industrial (EI) sectors.
    """
    
    # Elasticities for sectors
    elasticities = {
        'EI': 0.05,  # Industrial sector elasticity
        'RC': 0.01   # Residential sector elasticity
    }

    sector_elasticity = elasticities[sector]

    # Convert prices to numpy array, ensuring no zero values
    p = np.maximum(1.0, np.array(sector_price, float))

    # Base loads and prices for the specified location, date, and sector
    bl = base_load_dict[gas_zone, time_series, sector]
    bp = base_price_dict[gas_zone, time_series, sector]

    # Calculate elastic load based on elasticity
    elastic_load = bl * (p / bp) ** (-sector_elasticity)

    # Calculate consumer surplus and expenditure differences
    elastic_load_cs_diff = np.sum(
        (1 - (p / bp) ** (1 - sector_elasticity)) * bp * bl / (1 - sector_elasticity)
    )
    base_elastic_load_paid = np.sum(bp * bl)
    elastic_load_paid = np.sum(p * elastic_load)
    elastic_load_paid_diff = elastic_load_paid - base_elastic_load_paid

    # Aggregate demand
    demand = elastic_load
    # Aggregate willingness to pay into a scalar
    wtp = elastic_load_cs_diff + elastic_load_paid_diff

    # Return a tuple with the aggregated demand and willingness to pay
    return (demand, wtp)
