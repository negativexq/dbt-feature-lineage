with source_products as (
    select
        product_id,
        product_name,
        category,
        unit_price
    from {{ source('retail_raw', 'products') }}
),

renamed as (
    select
        cast(product_id as bigint) as product_id,
        trim(product_name) as product_name,
        lower(trim(category)) as category,
        cast(unit_price as numeric) as unit_price
    from source_products
)

select *
from renamed
