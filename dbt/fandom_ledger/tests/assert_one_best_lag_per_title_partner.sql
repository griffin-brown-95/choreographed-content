-- Exactly one lag can be best for each title and partner.
select
    title_id,
    partner_id,
    count(*) filter (where is_best_lag) as best_lag_count
from {{ ref('mart_buzz_sales_lag') }}
group by title_id, partner_id
having count(*) filter (where is_best_lag) != 1
