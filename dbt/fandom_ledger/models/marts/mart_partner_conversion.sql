with sales as (

    select * from {{ ref('fct_merch_sales_daily') }}
    where region != 'UNKNOWN'

),

titles as (

    select * from {{ ref('dim_titles') }}

),

buzz as (

    select * from {{ ref('fct_title_buzz_daily') }}

),

-- Pageviews before a title's first sale date can't produce sales, so they aren't counted.
title_buzz as (

    select
        titles.title_id,
        titles.fan_segment,
        sum(buzz.pageviews)::bigint as pageviews
    from titles
    inner join buzz
        on titles.title_id = buzz.title_id
        and buzz.view_date >= titles.first_sale_date
    group by titles.title_id, titles.fan_segment

),

partner_sales as (

    select
        partner_id,
        region,
        title_id,
        sum(units)::bigint as units,
        sum(revenue_usd)::decimal(16, 2) as revenue_usd
    from sales
    group by partner_id, region, title_id

)

select
    partner_sales.partner_id,
    partner_sales.region,
    partner_sales.title_id,
    title_buzz.fan_segment,
    partner_sales.units,
    partner_sales.revenue_usd,
    title_buzz.pageviews,
    partner_sales.revenue_usd * 1000.0 / title_buzz.pageviews as revenue_per_1k_pageviews,
    partner_sales.units * 1000.0 / title_buzz.pageviews as units_per_1k_pageviews
from partner_sales
inner join title_buzz
    on partner_sales.title_id = title_buzz.title_id
