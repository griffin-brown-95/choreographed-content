-- Every launch must have all 121 days from −30 to +90.
select
    launch_id,
    count(*) as day_count
from {{ ref('mart_title_launch_performance') }}
group by launch_id
having count(*) != 121
