with sales as (

    select * from {{ ref('stg_maison_merch__sales') }}

),

latest as (

    select *
    from sales
    qualify report_version = max(report_version) over (partition by report_month)

)

select * from latest
