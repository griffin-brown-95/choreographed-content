-- Only the latest version of each Maison Merch month may reach the intermediate layer.
select
    report_month,
    count(distinct report_version) as version_count
from {{ ref('int_maison_merch__latest_restatement') }}
group by report_month
having count(distinct report_version) != 1
