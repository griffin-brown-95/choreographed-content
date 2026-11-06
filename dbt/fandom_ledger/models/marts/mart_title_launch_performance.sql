with launches as (

    select * from {{ ref('dim_title_launches') }}

),

buzz as (

    select * from {{ ref('fct_title_buzz_daily') }}

),

daily_sales as (

    select
        title_id,
        sale_date,
        sum(units) as units,
        sum(revenue_usd) as revenue_usd
    from {{ ref('fct_merch_sales_daily') }}
    group by title_id, sale_date

),

offsets as (

    select unnest(range(-30, 91)) as days_since_launch

),

launch_days as (

    select
        launches.launch_id,
        launches.title_id,
        launches.launch_name,
        launches.launch_date,
        offsets.days_since_launch,
        launches.launch_date + offsets.days_since_launch::integer as calendar_date
    from launches
    cross join offsets

)

select
    launch_days.launch_id,
    launch_days.title_id,
    launch_days.launch_name,
    launch_days.launch_date,
    launch_days.days_since_launch,
    launch_days.calendar_date,
    buzz.pageviews,
    coalesce(daily_sales.units, 0)::bigint as units,
    coalesce(daily_sales.revenue_usd, 0)::decimal(16, 2) as revenue_usd
from launch_days
left join buzz
    on launch_days.title_id = buzz.title_id
    and launch_days.calendar_date = buzz.view_date
left join daily_sales
    on launch_days.title_id = daily_sales.title_id
    and launch_days.calendar_date = daily_sales.sale_date
