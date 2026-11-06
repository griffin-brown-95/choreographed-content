with partners as (

    select * from {{ ref('partners') }}

)

select
    partner_id,
    partner_name,
    product_focus,
    report_format,
    report_cadence
from partners
