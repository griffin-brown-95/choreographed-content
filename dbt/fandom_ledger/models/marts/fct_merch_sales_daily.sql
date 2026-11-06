with sales as (

    select * from {{ ref('int_partner_sales_mapped') }}
    where is_mapped

),

daily as (

    select
        title_id,
        partner_id,
        region,
        sale_date,
        sum(units)::bigint as units,
        sum(gross_amount_usd)::decimal(16, 2) as revenue_usd
    from sales
    group by title_id, partner_id, region, sale_date

)

select * from daily
