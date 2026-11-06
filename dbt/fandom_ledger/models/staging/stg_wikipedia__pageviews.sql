with source as (

    select * from {{ source('raw', 'wikipedia_pageviews') }}

),

renamed as (

    select
        article as wikipedia_article,
        strptime(left("timestamp", 8), '%Y%m%d')::date as view_date,
        views::bigint as pageviews,
        _source_file,
        _loaded_at
    from source

)

select * from renamed
