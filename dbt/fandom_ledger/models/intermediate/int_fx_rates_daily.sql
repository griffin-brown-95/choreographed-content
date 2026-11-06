with rates as (

    select * from {{ ref('stg_frankfurter__fx_rates') }}

),

currencies as (

    select distinct currency_code from rates

),

-- Starts at the first published rate, before the window opens, so the first days can be filled.
calendar as (

    select
        unnest(
            generate_series(
                (select min(rate_date) from rates),
                '{{ var("window_end") }}'::date,
                interval 1 day
            )
        )::date as rate_date

),

currency_days as (

    select
        currencies.currency_code,
        calendar.rate_date
    from currencies
    cross join calendar

),

filled as (

    select
        currency_days.currency_code,
        currency_days.rate_date,
        last_value(rates.usd_rate ignore nulls) over (
            partition by currency_days.currency_code
            order by currency_days.rate_date
            rows between unbounded preceding and current row
        ) as usd_rate,
        rates.usd_rate is null as is_forward_filled
    from currency_days
    left join rates
        on currency_days.currency_code = rates.currency_code
        and currency_days.rate_date = rates.rate_date

),

usd as (

    select
        'USD' as currency_code,
        rate_date,
        1::decimal(12, 6) as usd_rate,
        false as is_forward_filled
    from calendar

),

all_currencies as (

    select * from filled
    union all
    select * from usd

)

select *
from all_currencies
where rate_date >= '{{ var("window_start") }}'::date
