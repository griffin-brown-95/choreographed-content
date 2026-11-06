with titles as (

    select * from {{ ref('dim_titles') }}

),

pageviews as (

    select * from {{ ref('stg_wikipedia__pageviews') }}

),

calendar as (

    select
        unnest(
            generate_series(
                '{{ var("window_start") }}'::date,
                '{{ var("window_end") }}'::date,
                interval 1 day
            )
        )::date as view_date

),

title_days as (

    select
        titles.title_id,
        titles.wikipedia_article,
        calendar.view_date
    from titles
    cross join calendar

)

select
    title_days.title_id,
    title_days.view_date,
    -- Null means Wikipedia has no data for that day, which is different from zero views.
    pageviews.pageviews
from title_days
left join pageviews
    on title_days.wikipedia_article = pageviews.wikipedia_article
    and title_days.view_date = pageviews.view_date
