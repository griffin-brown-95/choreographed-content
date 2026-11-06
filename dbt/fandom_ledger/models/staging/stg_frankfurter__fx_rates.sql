with source as (

    select * from {{ source('raw', 'frankfurter_fx_rates') }}

),

renamed as (

    select
        base_currency as currency_code,
        rate_date::date as rate_date,
        rate::decimal(12, 6) as usd_rate,
        _source_file,
        _loaded_at
    from source
    where quote_currency = 'USD'

)

select * from renamed
