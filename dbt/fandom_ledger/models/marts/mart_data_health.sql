with mapped_sales as (

    select * from {{ ref('int_partner_sales_mapped') }}

),

maison_sales as (

    select * from {{ ref('stg_maison_merch__sales') }}

),

fx_rates as (

    select * from {{ ref('int_fx_rates_daily') }}

),

manifest as (

    select * from {{ ref('stg_partner_feeds__delivery_manifest') }}

),

unmapped_skus as (

    select
        'unmapped_sku' as check_name,
        partner_id,
        partner_sku as subject,
        count(*) as row_count,
        sum(gross_amount_usd) as amount_usd
    from mapped_sales
    where not is_mapped
    group by partner_id, partner_sku

),

unknown_regions as (

    select
        'unknown_region' as check_name,
        partner_id,
        'all_files' as subject,
        count(*) as row_count,
        sum(gross_amount_usd) as amount_usd
    from mapped_sales
    where region = 'UNKNOWN'
    group by partner_id

),

maison_monthly as (

    select
        maison_sales.report_month,
        maison_sales.report_version,
        count(*) as row_count,
        sum(maison_sales.gross_amount * fx_rates.usd_rate) as revenue_usd
    from maison_sales
    inner join fx_rates
        on maison_sales.currency_code = fx_rates.currency_code
        and maison_sales.sale_date = fx_rates.rate_date
    group by maison_sales.report_month, maison_sales.report_version

),

restatements as (

    select
        'restatement' as check_name,
        'maison_merch' as partner_id,
        strftime(restated.report_month, '%Y-%m') as subject,
        restated.row_count,
        restated.revenue_usd as amount_usd,
        original.revenue_usd as original_amount_usd,
        restated.revenue_usd - original.revenue_usd as delta_usd
    from maison_monthly as restated
    inner join maison_monthly as original
        on restated.report_month = original.report_month
        and original.report_version = 1
    where restated.report_version > 1

),

first_versions as (

    select
        *,
        lead(delivered_at) over (
            partition by partner_id
            order by period
        ) as next_period_delivered_at
    from manifest
    where file_name not like '%\_v_.%' escape '\'

),

late_files as (

    select
        'late_file' as check_name,
        partner_id,
        file_name as subject,
        date_diff('day', next_period_delivered_at, delivered_at) as days_late
    from first_versions
    where delivered_at > next_period_delivered_at

),

all_vault_lines as (

    select * from {{ ref('base_vault__order_lines') }}

),

kept_vault_lines as (

    select * from {{ ref('stg_vault__order_lines') }}

),

duplicate_lines as (

    select
        'duplicate_lines' as check_name,
        'vault' as partner_id,
        'all_exports' as subject,
        (select count(*) from all_vault_lines) - (select count(*) from kept_vault_lines)
            as row_count,
        (select sum(gross_amount) from all_vault_lines)
        - (select sum(gross_amount) from kept_vault_lines) as amount_usd

),

all_checks as (

    select * from unmapped_skus
    union all by name
    select * from unknown_regions
    union all by name
    select * from restatements
    union all by name
    select * from late_files
    union all by name
    select * from duplicate_lines

)

select
    check_name,
    partner_id,
    subject,
    row_count::bigint as row_count,
    amount_usd::decimal(16, 2) as amount_usd,
    original_amount_usd::decimal(16, 2) as original_amount_usd,
    delta_usd::decimal(16, 2) as delta_usd,
    days_late::integer as days_late
from all_checks
