with source as (

    select * from {{ source('raw', 'vault_exports') }}

),

exports as (

    select
        export_id,
        strptime(generated_at, '%Y-%m-%dT%H:%M:%SZ') as generated_at,
        from_json(
            orders,
            '[{
                "order_ref": "VARCHAR",
                "date": "VARCHAR",
                "country_iso2": "VARCHAR",
                "lines": [{
                    "vault_sku": "VARCHAR",
                    "qty": "INTEGER",
                    "unit_price_usd": "DECIMAL(14, 2)"
                }]
            }]'
        ) as orders,
        _source_file,
        _loaded_at
    from source

),

orders as (

    select
        export_id,
        generated_at,
        unnest(orders) as order_record,
        _source_file,
        _loaded_at
    from exports

),

order_lines as (

    select
        export_id,
        generated_at,
        order_record.order_ref as order_ref,
        order_record.date as ordered_at_local,
        order_record.country_iso2 as country_code,
        generate_subscripts(order_record.lines, 1) as line_number,
        unnest(order_record.lines) as line,
        _source_file,
        _loaded_at
    from orders

),

renamed as (

    select
        'vault' as partner_id,
        -- A plain cast to date would use the session time zone, so state UTC explicitly.
        (ordered_at_local::timestamptz at time zone 'UTC')::date as sale_date,
        line.vault_sku as partner_sku,
        country_code,
        line.qty as units,
        (line.qty * line.unit_price_usd)::decimal(14, 2) as gross_amount,
        'USD' as currency_code,
        order_ref,
        line_number,
        ordered_at_local,
        export_id,
        generated_at,
        _source_file,
        _loaded_at
    from order_lines

)

select * from renamed
