-- Warns at 2% and fails at 5%. Measured in basis points, because dbt counts failures as integers.
{{ config(fail_calc='max(unmapped_basis_points)', warn_if='>= 200', error_if='>= 500') }}

select
    round(
        10000 * sum(case when not is_mapped then gross_amount_usd else 0 end)
        / sum(gross_amount_usd)
    )::integer as unmapped_basis_points
from {{ ref('int_partner_sales_mapped') }}
