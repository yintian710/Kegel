from __future__ import annotations

from tortoise import fields
from tortoise.models import Model

from app.utils.snowflake import next_id


class PointsWallet(Model):
    user_id = fields.CharField(max_length=256, primary_key=True)
    username = fields.TextField()
    balance = fields.BigIntField(default=0)

    class Meta:
        table = "points_wallets"


class PointsLedger(Model):
    id = fields.BigIntField(primary_key=True, generated=False, default=next_id)
    user_id = fields.TextField()
    kind = fields.TextField()
    reference = fields.TextField()
    delta = fields.BigIntField()
    balance_after = fields.BigIntField()
    created_at = fields.FloatField()

    class Meta:
        table = "points_ledger"
        unique_together = (("kind", "reference"),)
