-- Joins must not add or drop rows, because a duplicate key would silently inflate revenue.
with source_rows as (

    select
        (select count(*) from {{ ref('stg_toyworks__sales') }})
        + (select count(*) from {{ ref('int_maison_merch__latest_restatement') }})
        + (select count(*) from {{ ref('stg_vault__order_lines') }}) as row_count

),

mapped_rows as (

    select count(*) as row_count from {{ ref('int_partner_sales_mapped') }}

)

select
    source_rows.row_count as source_row_count,
    mapped_rows.row_count as mapped_row_count
from source_rows
cross join mapped_rows
where source_rows.row_count != mapped_rows.row_count
