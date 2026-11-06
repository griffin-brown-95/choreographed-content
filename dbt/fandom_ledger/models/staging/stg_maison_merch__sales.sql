with source as (

    select * from {{ source('raw', 'maison_merch_sales') }}

),

renamed as (

    select
        'maison_merch' as partner_id,
        strptime("Date Vente", '%d.%m.%Y')::date as sale_date,
        "Ref Article" as partner_sku,
        "Pays" as country_code,
        "Qte"::integer as units,
        replace("CA Net", ',', '.')::decimal(14, 2) as gross_amount,
        "Devise" as currency_code,
        strptime(
            regexp_extract(_source_file, 'maison_merch_(\d{6})', 1), '%Y%m'
        )::date as report_month,
        coalesce(
            nullif(regexp_extract(_source_file, '_v(\d+)\.xlsx$', 1), '')::integer, 1
        ) as report_version,
        _source_file,
        _loaded_at
    from source

)

select * from renamed
