with source as (

    select * from {{ source('raw', 'toyworks_sales') }}

),

renamed as (

    select
        'toyworks' as partner_id,
        strptime("Sales Date", '%m/%d/%Y')::date as sale_date,
        trim("Item #") as partner_sku,
        "Item Desc" as item_description,
        coalesce(nullif(trim("Region"), ''), 'UNKNOWN') as country_code,
        "Units Sold"::integer as units,
        replace(replace("Sales Amt", '$', ''), ',', '')::decimal(14, 2) as gross_amount,
        'USD' as currency_code,
        _source_file,
        _loaded_at
    from source

)

select * from renamed
