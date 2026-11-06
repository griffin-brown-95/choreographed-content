with launches as (

    select * from {{ ref('title_launches') }}

),

titles as (

    select * from {{ ref('titles') }}

)

select
    launches.launch_id,
    launches.title_id,
    titles.title_name,
    launches.season_label,
    titles.title_name || ' - ' || launches.season_label as launch_name,
    launches.launch_date
from launches
inner join titles
    on launches.title_id = titles.title_id
