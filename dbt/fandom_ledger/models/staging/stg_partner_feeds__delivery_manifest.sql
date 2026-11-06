with source as (

    select * from {{ source('raw', 'delivery_manifest') }}

),

renamed as (

    select
        partner_id,
        file_name,
        period,
        strptime(delivered_at, '%Y-%m-%dT%H:%M:%SZ') as delivered_at,
        _loaded_at
    from source

)

select * from renamed
