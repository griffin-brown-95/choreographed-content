with sales as (

    select * from {{ ref('int_partner_sales_unioned') }}

),

crosswalk as (

    select * from {{ ref('sku_crosswalk') }}

),

regions as (

    select * from {{ ref('regions') }}

),

fx_rates as (

    select * from {{ ref('int_fx_rates_daily') }}

),

mapped as (

    select
        sales.partner_id,
        sales.sale_date,
        sales.partner_sku,
        crosswalk.title_id,
        crosswalk.product_category,
        crosswalk.partner_sku is not null as is_mapped,
        sales.country_code as raw_country_code,
        regions.country_code,
        regions.region,
        sales.units,
        sales.gross_amount,
        sales.currency_code,
        fx_rates.usd_rate,
        (sales.gross_amount * fx_rates.usd_rate)::decimal(14, 2) as gross_amount_usd,
        sales._source_file
    from sales
    left join crosswalk
        on sales.partner_id = crosswalk.partner_id
        and sales.partner_sku = crosswalk.partner_sku
    left join regions
        on sales.partner_id = regions.partner_id
        and sales.country_code = regions.raw_country_code
    left join fx_rates
        on sales.currency_code = fx_rates.currency_code
        and sales.sale_date = fx_rates.rate_date

)

select * from mapped
