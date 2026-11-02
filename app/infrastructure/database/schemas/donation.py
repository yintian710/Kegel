from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class DonationOrder(Model):
    order_no = fields.CharField(max_length=128, primary_key=True)
    user_id = fields.TextField()
    username = fields.TextField()
    amount_cents = fields.BigIntField()
    pid = fields.TextField()
    name = fields.TextField()
    created_at = fields.FloatField()

    class Meta:
        table = "donation_orders"


class DonationSettlement(Model):
    order_no = fields.CharField(max_length=128, primary_key=True)
    trade_no = fields.TextField()
    paid_at = fields.FloatField()

    class Meta:
        table = "donation_settlements"
