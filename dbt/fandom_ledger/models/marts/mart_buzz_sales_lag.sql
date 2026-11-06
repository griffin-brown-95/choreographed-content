with titles as (

    select * from {{ ref('dim_titles') }}

),

sales as (

    select
        title_id,
        partner_id,
        sale_date,
        sum(units) as units
    from {{ ref('fct_merch_sales_daily') }}
    group by title_id, partner_id, sale_date

),

buzz as (

    select * from {{ ref('fct_title_buzz_daily') }}
    where pageviews is not null

),

title_partners as (

    select distinct
        title_id,
        partner_id
    from sales

),

-- Days with no sales count as zero units, so quiet days stay in the correlation.
sale_days as (

    select
        title_partners.title_id,
        title_partners.partner_id,
        unnest(
            generate_series(
                titles.first_sale_date,
                '{{ var("window_end") }}'::date,
                interval 1 day
            )
        )::date as sale_date
    from title_partners
    inner join titles
        on title_partners.title_id = titles.title_id

),

daily_units as (

    select
        sale_days.title_id,
        sale_days.partner_id,
        sale_days.sale_date,
        coalesce(sales.units, 0) as units
    from sale_days
    left join sales
        on sale_days.title_id = sales.title_id
        and sale_days.partner_id = sales.partner_id
        and sale_days.sale_date = sales.sale_date

),

lags as (

    select unnest(range(0, 22)) as lag_days

),

correlations as (

    select
        daily_units.title_id,
        daily_units.partner_id,
        lags.lag_days,
        corr(daily_units.units, buzz.pageviews) as correlation,
        count(*) as days_compared
    from daily_units
    cross join lags
    inner join buzz
        on daily_units.title_id = buzz.title_id
        and buzz.view_date = daily_units.sale_date - lags.lag_days::integer
    group by daily_units.title_id, daily_units.partner_id, lags.lag_days

)

select
    title_id,
    partner_id,
    lag_days,
    correlation,
    days_compared,
    row_number() over (
        partition by title_id, partner_id
        order by correlation desc
    ) = 1 as is_best_lag
from correlations
