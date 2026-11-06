with order_lines as (

    select * from {{ ref('base_vault__order_lines') }}

),

deduplicated as (

    select *
    from order_lines
    qualify row_number() over (
        partition by order_ref, line_number
        order by generated_at desc, _source_file desc
    ) = 1

)

select * from deduplicated
