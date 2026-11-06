with toyworks as (

    select
        partner_id,
        sale_date,
        partner_sku,
        country_code,
        units,
        gross_amount,
        currency_code,
        _source_file
    from {{ ref('stg_toyworks__sales') }}

),

maison_merch as (

    select
        partner_id,
        sale_date,
        partner_sku,
        country_code,
        units,
        gross_amount,
        currency_code,
        _source_file
    from {{ ref('int_maison_merch__latest_restatement') }}

),

vault as (

    select
        partner_id,
        sale_date,
        partner_sku,
        country_code,
        units,
        gross_amount,
        currency_code,
        _source_file
    from {{ ref('stg_vault__order_lines') }}

),

unioned as (

    select * from toyworks
    union all
    select * from maison_merch
    union all
    select * from vault

)

select * from unioned
