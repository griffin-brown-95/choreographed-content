with titles as (

    select * from {{ ref('titles') }}

)

select
    title_id,
    title_name,
    wikipedia_article,
    title_type,
    fan_segment,
    first_sale_date
from titles
