# Model Documentation: Switch-USA-gasnetwork3.0
**Thuy Doan** - [thuydoan206 at gmail dot com](mailto:thuydoan206@gmail.com)

## Introduction

Switch-USA natural gas model is a free-standing model that optimizes natural gas facility and network usage and expansion with elastic demand, including all consumption sectors. The Switch-USA natural gas model minimizes the discounted total capital and operational cost of natural gas infrastructures to meet the natural gas demand at each state in the 48 U.S. contiguous states and the District of Columbia.
Switch-USA natural gas model 3.0 will minimize the net total cost minus consumer welfares. The main decision variables are necessary additional capacity of underground storage, LNG facilities, gas well, and state-to-state pipelines to accommodate the gas flow between supply and demand regions over the study period. In addition, the model computes optimal daily volume of natural gas injections into and withdrawals from underground storage, LNG facilities, as well as pipeline deliveries and receipts to meet the daily demand at each state. Constraints require that the total volume of natural gas from local production, net imports, net storage withdrawals, LNG regasification, and net pipeline receipts provides adequate natural gas for local consumption during on the daily basis. The amount of natural gas in underground storage, regasified from LNG, and transmitted through interstate pipeline are constrained by the capacity of underground storage, LNG facilities, and pipeline in each time period, respectively. Imports from and exports to other countries are taken as exogenous.
Also, pricing mechanism aims to achieve revenue neutrality over the whole system (two consumption sectors) in each period. This would leave out the stranded costs of capacity built in the past periods.

## Installation and Run the Model

This model will use the SWITCH 2.0 modeling framework for optimization. The model also depends on the SWITCH2.0 ***timescales***, ***financials***, and ***reporting*** modules from the switch_model package.

You can find hands-on introduction, tutorials, and links to download for SWITCH2.0 at [https://switch-model.org/](https://switch-model.org/)

## Model Configuration Files

Besides ***timescales***, ***financials***, and ***reporting*** modules from the SWITCH2.0 package, the Switch-USA natural gas model includes other modules as follow. 

*switch_model.timescales
switch_model.financials
switch_model.reporting
gas_network_build_2sectors
gas_wells_build
LNG_build_balance
gas_network_balance_2sectors
gas_iterative_demand_response_2sectors
gas_constant_elasticity_demand_system_2sectors
gas_balance_constraint*

For a free-standing natural gas model with **endogenous elastic demand**, create a ***modules.txt*** file in your working directory with the above lines in an exact order. Also, create a ***iterate.txt*** file in your working directory with this one line:
*gas_iterative_demand_response_2sectors*

In case you want the model with **exogenously specified demand**: 

* remove the ***iterate.txt*** file, and
* in the ***modules.txt*** file, *comment out* these two lines:
  * *gas_iterative_demand_response_2sectors*
  * *gas_constant_elasticity_demand_system_2sectors*

### Module 1: gas_network_build_2sectors.py

* Defines the structure and parameters for modeling the gas network, including pipelines and storage facilities.
* Sets up necessary sets and parameters to represent gas zones, pipelines, and their characteristics.
* Includes logic to handle existing and new gas lines.

### Module 2: gas_wells_build.py

* Defines the structure and parameters for modeling gas wells by drill type and gas zone.
* Sets up necessary sets and parameters to represent gas wells, their production rates, and associated costs.
* Includes logic to handle existing and new gas wells, including their build years and maximum age.

### Module 3: LNG_build_balance.py

* Defines the structure and parameters for modeling the additional capacity of LNG storage to be built.
* Sets up necessary sets and parameters to represent LNG storage, liquefaction, and vaporization costs.
* Includes logic to handle existing and new LNG storage facilities, including their build years and whether new builds are allowed in specific gas zones.

### Module 4: gas_network_balance_2sectors.py

* Defines the structure and parameters for balancing gas flows within the network.
* Sets up necessary sets, variables, and constraints to ensure gas injections and withdrawals are balanced across different zones and timeseries.
* Includes logic to handle gas line capacities, dispatch, and efficiency, ensuring gas flow on each line does not exceed its installed capacity and accounting for fuel costs.

### Module 5: gas_iterative_demand_response_2sectors.py

* Calibrates demand data and iterates over the calibration process for two demand sectors: Electricity and Industrial (EI) sector, and Residential and Commercial (RC) sector.
* Sets up the framework for handling demand response calibration and pricing strategies for different sectors.
* Ensures that the system remains revenue-neutral in each period.
* Assesses the impact of additional pipeline capacity.

When including this module, users need to indicate the following options:

* `--dr-flat-pricing`: A boolean flag to charge a constant (average) price for the Residential and Commercial (RC) sector, rather than varying day by day as for the Electricity and Industry (EI) sector.
* `--dr-demand-module`: Name of module to use for demand-response bids (in this model, we use `gas_constant_elasticity_demand_system_2sectors.py`).

### Module 6: gas_constant_elasticity_demand_system_2sectors.py

* This module is essential for modeling demand response by adjusting demand based on price changes using constant elasticity for different sectors.
* Calibrates the model with base demand quantity and prices for each gas zone, sector, and timeseries.
* Calculates the demand quantity levels and willingness to pay for those quantities based on current prices.

## Input Tables

As default, all data inputs should be stored in a folder named "inputs". The following files are neccessary.

### switch_inputs_version.txt

This file tell SWITCH2.0 which version of model to be called. For example: **2.0.7** - the natural gas model is developed using SWITCH2.0.7.

### Table 1: gas_zones.csv

| Column Name                    | Data Type | Description                                                                             |
| ------------------------------ | --------- | --------------------------------------------------------------------------------------- |
| `GAS_ZONES`                  | TEXT      | Name of gas distribution zone, eg. 'DE'.                                                       |
| `gas_zone_lon`               | FLOAT     | The centroid longitude of the gas zone.                                                          |
| `gas_zone_lat`               | FLOAT     | The centroid latitude of the gas zone.                                                           |
| `gas_well_new_build_allowed` | BOOLEAN   | Indicates whether new gas wells are allowed to be built in the specified gas zone.      |
| `LNG_new_build_allowed`      | BOOLEAN   | Indicates whether new LNG facilities are allowed to be built in the specified gas zone. |

### Table 2: gas_line_capital_cost.csv

| Column Name                                   | Data Type | Description                                                                                                     |
| --------------------------------------------- | --------- | --------------------------------------------------------------------------------------------------------------- |
| `GAS_LINES`                                 | TEXT      | The identifier for the gas pipeline corridor, typically indicating the states it connect. Eg. 'DE_MD'.   |
| `gas_line_gz1`                              | TEXT      | The starting zone of this pipeline corridor.  |
| `gas_line_gz2`                              | TEXT      | The ending zone of this pipeline corridor.   |
| `gas_line_length`                           | FLOAT     | The length of the gas pipeline in kilometers (measured between centers of zones). |
| `gas_line_new_build_allowed`                | BOOLEAN   | 1 if new gas pipelines are allowed to be built on this corridor.  |
| `directional_gas_line_capital_cost_dmmbukm` | FLOAT     | The capital cost of the directional pipeline, mainly for compressor stations which help gas movement in one specific direction, in dollars per million British thermal units per kilometer (`$/MMBTU/km`). |
| `general_gas_line_capital_cost_dmmbukm`     | FLOAT     | The general capital cost of building the gas pipeline in `$/MMBTU/km`.     |

### Table 3: gas_line_parameters.csv

| Column Name       | Data Type | Description                             |
| ----------------- | --------- | --------------------------------------- |
| `gas_line_life` | INTEGER   | The lifespan of gas pipelines in years, default value is 50. |
| `gas_transmission_fuel_cost` | FLOAT  | The fraction of gas movement volume used by gas pipeline during transmisson. |

### Table 4: gas_lines_predetermined_directional.csv

| Column Name                    | Data Type | Description                                                                    |
| ------------------------------ | --------- | ------------------------------------------------------------------------------ |
| `gas_line_gz1`               | TEXT      | The starting zone of the gas pipeline.                   |
| `gas_line_gz2`               | TEXT      | The ending zone of the gas pipeline.                     |
| `gas_line_predet_build_year` | INTEGER   | The year when the gas pipeline was built/expanded.                                      |
| `gas_line_predet_cap`        | FLOAT     | The predetermined additional capacity of the gas pipeline in million BTU per day (MMBtud) in this build-year.         |
| `gas_line_removed_cap`       | FLOAT     | The capacity of the gas pipeline corridor that has been removed in million BTU per day (MMBtud). |
| `gas_line_total_cap`         | FLOAT     | The total capacity of the gas pipeline corridor in million BTU per day (MMBtud).                 |

### Table 5: gas_lines_predetermined_general.csv

| Column Name                    | Data Type | Description                                                                       |
| ------------------------------ | --------- | --------------------------------------------------------------------------------- |
| `GAS_LINES`                  | TEXT      | The identifier for the gas pipeline corridor.                                             |
| `gas_line_predet_build_year` | INTEGER   | The year when the gas pipeline was built/expanded.                                         |
| `gas_line_predet_cap`        | FLOAT     | The additional general capacity of the gas pipeline in million BTU per day (MMBtud).   |
| `gas_line_removed_cap`       | FLOAT     | The capacity of the gas pipeline that has been removed in million BTU per day (MMBtud).    |
| `gas_line_total_cap_general` | FLOAT     | The total general capacity of the gas pipeline in million BTU per day (MMBtud). General capacity is defined as the maximum capacity among two directional pipelines. |

### Table 6: gas_storage_types.csv

| Column Name                         | Data Type | Description                                                                                                  |
| ----------------------------------- | --------- | ------------------------------------------------------------------------------------------------------------ |
| `gas_storage_type`                | TEXT      | The type of gas underground storage facility.                                                                            |
| `gas_storage_max_cycles_per_year` | INTEGER   | The maximum number of storage cycles that can be performed per year.                                         |
| `gas_storage_life`                | INTEGER   | The expected operational life of the gas storage facility in years.                                          |
| `gas_storage_fuel_cost`           | RATIO    | The fuel cost associated with the gas storage facility, defined as a fraction of gross storage injections and withdrawals. |

### Table 7: gas_storage_capital_cost.csv

| Column Name                       | Data Type | Description                                                                                                  |
| --------------------------------- | --------- | ------------------------------------------------------------------------------------------------------------ |
| `GAS_ZONES`                     | TEXT      | The gas zones where the gas storage facilities are located.                               |
| `gas_storage_type`              | TEXT      | The type of underground storage facility.                                                                            |
| `gas_storage_new_build_allowed` | BOOLEAN   | 1 if new underground storage facilities of this type are allowed to be built in the specified gas zone. |
| `gas_storage_unit_cost_dmmbtu`  | FLOAT     | The unit cost of gas storage in dollars per million BTU (DMMBTU).                          |
| `gas_storage_efficiency`        | FLOAT     | The efficiency of the gas storage facility, defined as the ratio between working capacity and total storage capacity |
| `gas_store_to_release_ratio`    | FLOAT     | The ratio of gas stored to gas released.                                                                     |

### Table 8: gas_storage_predetermined.csv

| Column Name                       | Data Type | Description                                                                            |
| --------------------------------- | --------- | -------------------------------------------------------------------------------------- |
| `GAS_ZONES`                     | TEXT      | The gas zones where the gas storage facilities are located.         |
| `gas_storage_type`              | TEXT      | The type of underground gas storage.                                                      |
| `gas_storage_predet_build_year` | INTEGER   | The year when the gas storage facility was built.                                      |
| `gas_storage_predet_cap`        | FLOAT     | The additional capacity of the gas storage facility that has been built in this year, in MMBtu.         |
| `gas_storage_removed_cap`       | FLOAT     | The capacity of the gas storage facility that has been removed  in this year in MMBtu. |
| `gas_storage_total_cap`         | FLOAT     | The total capacity of the gas storage facility in MMBtu.                 |

### Table 9: drill_type.csv

| Column Name          | Data Type | Description                                                                                                 |
| -------------------- | --------- | ----------------------------------------------------------------------------------------------------------- |
| `DRILL_TYPE`       | TEXT      | The type of drilling method used for gas wells (e.g., D for directional, H for horizontal, V for vertical). |
| `gas_well_max_age` | INTEGER   | The maximum age of gas wells in years for the specified drilling type.                                      |

### Table 10: gas_well_capital_cost.csv

| Column Name               | Data Type | Description                                                                                          |
| ------------------------- | --------- | ---------------------------------------------------------------------------------------------------- |
| `GAS_ZONES`             | TEXT      | The gas zones where the gas wells are located.                                    |
| `DRILL_TYPE`            | TEXT      | The type of drilling used for the gas well.                                                          |
| `well_capital_cost`     | FLOAT     | The capital cost of drilling the gas well of this drilling type in dollars per well                  |
| `percentage_drill_type` | FLOAT     | The percentage of each drilling type in the given gas zone, reflecting the geological characteristics of this gas zone. This is estimated based on distribution of pre-existing wells over three main drilling types in each gas zone.     |

### Table 11: gas_well_predetermined.csv

| Column Name                    | Data Type | Description                                                                                        |
| ------------------------------ | --------- | -------------------------------------------------------------------------------------------------- |
| `GAS_ZONES`                  | TEXT      | The gas zones where the gas wells are located.                                  |
| `DRILL_TYPE`                 | TEXT      | The type of drilling used for the gas well.                                                        |
| `gas_well_predet_build_year` | INTEGER   | The year when the gas well was built.                                                              |
| `gas_well_predet_num`        | INTEGER   | The number of new gas wells that have been built in this year                                      |
| `gas_well_total_num`         | INTEGER   | The total number of gas wells available.                                             |

### Table 12: max_gas_well_build_year.csv

| Column Name                 | Data Type | Description                                                                    |
| --------------------------- | --------- | ------------------------------------------------------------------------------ |
| `GAS_ZONES`               | TEXT      | The gas zones where the gas wells are located.              |
| `max_gas_well_build_year` | INTEGER   | The maximum number of gas wells can be built in one year the specified gas zone. |

### Table 13: prod_year.csv

| Column Name   | Data Type | Description                     |
| ------------- | --------- | ------------------------------- |
| `PROD_YEAR` | INTEGER   | The production year identifier, indicate how many years that a well has been in production, ordered from 1 to 30. |

### Table 14: gas_well_production_curve_annual.csv

| Column Name                    | Data Type | Description                                                                                          |
| ------------------------------ | --------- | ---------------------------------------------------------------------------------------------------- |
| `GAS_ZONES`                  | TEXT      | The gas zones where the gas wells are located.                                    |
| `DRILL_TYPE`                 | TEXT      | The type of drilling used for the gas well.  |
| `PROD_YEAR`                  | INTEGER   | The year of production.                                                                     |
| `gas_production_rate_mmbtud` | FLOAT     | The gas production rate in million BTU per day (MMBTU/day).                        |

### Table 15: LNG_capital_costs.csv

| Column Name                       | Data Type | Description                                                                                |
| --------------------------------- | --------- | ------------------------------------------------------------------------------------------ |
| `LNG_storage_capital_cost`      | FLOAT     | The capital cost of LNG storage in dollars per million Btu (`$/MMBTU`).      |
| `LNG_liquefaction_capital_cost` | FLOAT     | The capital cost of LNG liquefaction in `$/MMBTU`. |
| `LNG_vaporization_capital_cost` | FLOAT     | The capital cost of LNG vaporization in `$/MMBTU`. |

### Table 16: LNG_liquefaction_predetermined.csv

| Column Name                            | Data Type | Description                                                                                 |
| -------------------------------------- | --------- | ------------------------------------------------------------------------------------------- |
| `GAS_ZONES`                          | TEXT      | The gas zones where the LNG liquefaction facilities are located.         |
| `LNG_liquefaction_predet_build_year` | INTEGER   | The year when the LNG liquefaction facility was built.                                      |
| `LNG_liquefaction_predet_cap`        | FLOAT     | The additional capacity of the LNG liquefaction facility that has been built, in million BTU (MMBtu).         |
| `LNG_liquefaction_removed_cap`       | FLOAT     | The capacity of the LNG liquefaction facility that has been removed in million BTU (MMBtu). |
| `LNG_liquefaction_total_cap`         | FLOAT     | The total capacity of the LNG liquefaction facility in million BTU (MMBtu).                 |

### Table 17: LNG_storage_predetermined.csv

| Column Name                       | Data Type | Description                                                                            |
| --------------------------------- | --------- | -------------------------------------------------------------------------------------- |
| `GAS_ZONES`                     | TEXT      | The gas zones where the LNG storage facilities are located.         |
| `LNG_storage_predet_build_year` | INTEGER   | The year when the LNG storage facility was built.                                      |
| `LNG_storage_predet_cap`        | FLOAT     | The new build capacity of the LNG storage facility in million BTU (MMBtu).         |
| `LNG_storage_removed_cap`       | FLOAT     | The capacity of the LNG storage facility that has been removed in million BTU (MMBtu). |
| `LNG_storage_total_cap`         | FLOAT     | The total capacity of the LNG storage facility in million BTU (MMBtu).                 |

### Table 18: LNG_vaporization_predetermined.csv

| Column Name                            | Data Type | Description                                                                                 |
| -------------------------------------- | --------- | ------------------------------------------------------------------------------------------- |
| `GAS_ZONES`                          | TEXT      | The gas zones where the LNG vaporization facilities are located.         |
| `LNG_vaporization_predet_build_year` | INTEGER   | The year when the LNG vaporization facility was built.                                      |
| `LNG_vaporization_predet_cap`        | FLOAT     | The new build capacity of the LNG vaporization facility in million BTU (MMBtu).         |
| `LNG_vaporization_removed_cap`       | FLOAT     | The capacity of the LNG vaporization facility that has been removed in million BTU (MMBtu). |
| `LNG_vaporization_total_cap`         | FLOAT     | The total capacity of the LNG vaporization facility in million BTU (MMBtu).                 |

### Table 19: LNG_routes.csv

| Column Name            | Data Type | Description                                                                              |
| ---------------------- | --------- | ---------------------------------------------------------------------------------------- |
| `LNG_ROUTE`          | TEXT      | The identifier for the LNG route, typically combining the starting and ending gas zones. |
| `LNG_route_gz1`      | TEXT      | The starting gas zone for the LNG route.                               |
| `LNG_route_gz2`      | TEXT      | The ending gas zone for the LNG route.                                 |
| `LNG_route_distance` | FLOAT     | The distance of the LNG route in kilometers.                                                  |
| `LNG_flow_allowed`   | BOOLEAN   | Indicates whether LNG transportation is allowed on this route.                                     |

### Table 20: gas_demand.csv

| Column Name                 | Data Type | Description                                                                              |
| --------------------------- | --------- | ---------------------------------------------------------------------------------------- |
| `GAS_ZONES`               | TEXT      | The gas zones where the gas demand is measured.                       |
| `TIMESERIES`              | DATE/TEXT | The date of the demand measurement in the format `YYYYMMDD`.                           |
| `DEMAND_SECTORS`          | TEXT      | The gas consumption sector. 'RC' is Residential and Commercial; 'EI' is Electricity and Industrial. |
| `gas_ref_price`           | FLOAT     | The reference price of natural gas in dollars per million British thermal units (MMBTU). |
| `gas_demand_ref_quantity` | FLOAT     | The reference quantity of natural gas demand in million BTU (MMBtu).                     |

### Table 21: RC_price_markup.csv

| Column Name         | Data Type | Description                                                         |
| ------------------- | --------- | ------------------------------------------------------------------- |
| `GAS_ZONES`       | TEXT      | The gas zones where the price markup is applied. |
| `RC_price_markup` | FLOAT     | The price markup applied to the Residential and Commercial to account for distribution cost, in $/MMBtu. |

### Table 22: gas_trade.csv

| Column Name                 | Data Type | Description                                                                   |
| --------------------------- | --------- | ----------------------------------------------------------------------------- |
| `GAS_ZONES`               | TEXT      | The gas zones identified as point of entry/exit of import/export activities. |
| `TIMESERIES`              | DATE/TEXT | The date of the gas trade measurement in the format `YYYYMMDD`.             |
| `gas_import_ref_quantity` | FLOAT     | The quantity of natural gas imported in million BTU (MMBtu).        |
| `gas_export_ref_quantity` | FLOAT     | The quantity of natural gas exported in million BTU (MMBtu).        |

### Table 23: LNG_imports.csv

| Column Name                 | Data Type | Description                                                                           |
| --------------------------- | --------- | ------------------------------------------------------------------------------------- |
| `GAS_ZONES`               | TEXT      | The gas zones where the LNG import terminals are located. |
| `TIMESERIES`              | DATE/TEXT | The date of the LNG import measurement in the format `YYYYMMDD`.             |
| `LNG_import_ref_quantity` | FLOAT     | The reference quantity of LNG imported in million BTU (MMBtu).                        |

### Table 24: gas_disposing_cost.csv

| Column Name            | Data Type | Description                                                               |
| ---------------------- | --------- | ------------------------------------------------------------------------- |
| `gas_disposing_cost` | FLOAT     | The cost associated with gas disposing/flaring, in dollars per MMBtu. |

To consider impacts on equilibrium quantity and price for the Residential and Commercial (RC) sector from exogenously adding a new pipeline, add the following input files. The model will then take this additional pipeline as given when optimizing other investment decisions.

### Table 25: gas_zone_cost_adder.csv

| Column Name             | Data Type | Description                                                                                       |
| ----------------------- | --------- | ------------------------------------------------------------------------------------------------- |
| `GAS_ZONE_COST_ADDER` | TEXT      | The gas zones that are served by the exogenously built pipeline, where the cost adder is applied. |

### Table 26: gas_lines_general_build_exogenous.csv

| Column Name             | Data Type | Description                                                                                                      |
| ----------------------- | --------- | ---------------------------------------------------------------------------------------------------------------- |
| `GAS_LINES`           | TEXT      | The identifier for the gas line, typically representing the connection between two gas zones. |
| `gas_line_build_year` | INTEGER   | The year in which the gas line is built.                                                                         |
| `gas_line_build_cap`  | FLOAT     | The capacity of the gas line in cubic meters per year.                                                           |

### Table 27: gas_lines_directional_build_exogenous.csv

| Column Name                 | Data Type | Description                                               |
| --------------------------- | --------- | --------------------------------------------------------- |
| `gas_line_gz1`            | TEXT      | The geographical zone or state where the gas line starts. |
| `gas_line_gz2`            | TEXT      | The geographical zone or state where the gas line ends.   |
| `gas_line_build_year`     | INTEGER   | The year in which the gas line is built.                  |
| `gas_line_build_cap`      | FLOAT     | The capacity of the gas line in cubic meters per year.    |
| `gas_line_build_cost`     | FLOAT     | The cost to build the gas line in dollars.                |
| `gas_line_operating_life` | INTEGER   | The operating life of the gas line in years.              |

The four tables below should follow standard inputs in Switch model packages.

### Table 28: periods.csv

| Column Name           | Data Type | Description                              |
| --------------------- | --------- | ---------------------------------------- |
| `INVESTMENT_PERIOD` | INTEGER   | The investment period identifier.        |
| `period_start`      | INTEGER   | The start year of the investment period. |
| `period_end`        | INTEGER   | The end year of the investment period.   |

### Table 29: timeseries.csv

| Column Name            | Data Type | Description                                                      |
| ---------------------- | --------- | ---------------------------------------------------------------- |
| `TIMESERIES`         | DATE/TEXT | The date of the timeseries entry in the format `YYYYMMDD`.     |
| `ts_period`          | INTEGER   | The period associated with the timeseries entry.                 |
| `ts_duration_of_tp`  | INTEGER   | The duration in hours of each timepoint within this timeseries entry. |
| `ts_num_tps`         | INTEGER   | The number of timepoints in the timeseries entry.              |
| `ts_scale_to_period` | FLOAT     | The number of times this representative timeseries entry occurs in a period. |

### Table 30: timepoints.csv

| Column Name      | Data Type     | Description                                                                                |
| ---------------- | ------------- | ------------------------------------------------------------------------------------------ |
| `timepoint_id` | TEXT          | The unique identifier for the timepoint, typically combining the date and hour.            |
| `timestamp`    | DATETIME/TEXT | The timestamp of the timepoint in the format `YYYY-MM-DD-HH:MM`.                         |
| `timeseries`   | DATE/TEXT     | The timeseries entry associated with the timepoint in the format `YYYYMMDD`. |

### Table 31: financials.csv

| Column Name             | Data Type | Description                                          |
| ----------------------- | --------- | ---------------------------------------------------- |
| `base_financial_year` | INTEGER   | The base year for financial calculations.            |
| `interest_rate`       | FLOAT     | The real interest rate paid on a loan from a bank. |
| `discount_rate`       | FLOAT     | The real discount rate applied to convert future dollars into dollar value at base year for comparison purpose. |
