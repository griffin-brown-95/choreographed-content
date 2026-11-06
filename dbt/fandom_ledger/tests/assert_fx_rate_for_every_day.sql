-- Every day in the window must have a rate for each currency after forward-fill.
with calendar as (

    select
        unnest(
            generate_series(
                '{{ var("window_start") }}'::date,
                '{{ var("window_end") }}'::date,
                interval 1 day
            )
        )::date as rate_date

),

currencies as (

    select unnest(['EUR', 'GBP', 'USD']) as currency_code

),

expected as (

    select
        currencies.currency_code,
        calendar.rate_date
    from currencies
    cross join calendar

)

select expected.*
from expected
left join {{ ref('int_fx_rates_daily') }} as rates
    on expected.currency_code = rates.currency_code
    and expected.rate_date = rates.rate_date
where rates.usd_rate is null
