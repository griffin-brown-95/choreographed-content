-- The fact must carry every mapped dollar and unit, and nothing else.
with mapped as (

    select
        sum(gross_amount_usd) as revenue_usd,
        sum(units) as units
    from {{ ref('int_partner_sales_mapped') }}
    where is_mapped

),

fact as (

    select
        sum(revenue_usd) as revenue_usd,
        sum(units) as units
    from {{ ref('fct_merch_sales_daily') }}

)

select
    mapped.revenue_usd as mapped_revenue_usd,
    fact.revenue_usd as fact_revenue_usd,
    mapped.units as mapped_units,
    fact.units as fact_units
from mapped
cross join fact
where mapped.revenue_usd != fact.revenue_usd
    or mapped.units != fact.units
