from __future__ import annotations

from tortoise import fields
from tortoise.models import Model

from app.utils.snowflake import next_id


class ShopProduct(Model):
    id = fields.BigIntField(primary_key=True, generated=False, default=next_id)
    category = fields.TextField(default="LDC")
    name = fields.TextField()
    description = fields.TextField(default="")
    points_price = fields.BigIntField()
    ldc_amount = fields.TextField(default="1.00")
    user_daily_limit = fields.IntField(default=0)
    total_daily_limit = fields.IntField(default=0)
    is_active = fields.IntField()
    draw_count = fields.IntField(default=0)

    class Meta:
        table = "shop_products"


class ShopPurchase(Model):
    order_no = fields.CharField(max_length=128, primary_key=True)
    product_id = fields.BigIntField()
    category = fields.TextField()
    product_name = fields.TextField()
    user_id = fields.TextField()
    username = fields.TextField()
    points_cost = fields.BigIntField()
    ldc_amount = fields.TextField()
    status = fields.TextField()
    trade_no = fields.TextField(default="")
    error = fields.TextField(default="")
    created_at = fields.FloatField()
    day = fields.TextField()
    request_id = fields.TextField(null=True)
    draw_count = fields.IntField(default=0)

    class Meta:
        table = "shop_purchases"
