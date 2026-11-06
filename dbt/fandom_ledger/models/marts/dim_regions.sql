with regions as (

    select distinct region from {{ ref('regions') }}

)

select
    region,
    case region
        when 'NORTH_AMERICA' then 'North America'
        when 'EU' then 'European Union'
        when 'UK' then 'United Kingdom'
        when 'APAC' then 'Asia-Pacific'
        when 'LATAM' then 'Latin America'
        when 'UNKNOWN' then 'Unknown'
    end as region_name
from regions
