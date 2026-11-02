from __future__ import annotations

from tortoise import fields
from tortoise.models import Model

from app.utils.snowflake import next_id

# 复合主键表（reviews / sessions / entries）：Tortoise 只支持单列主键，这里把 day 声明为 ORM 主键，
# 真实主键是 (day, user_id)。禁止对这些模型调用 instance.save()；一律用 filter(day=, user_id=).update()/create()。


class CheckinSetting(Model):
    key = fields.CharField(max_length=128, primary_key=True)
    value = fields.TextField()

    class Meta:
        table = "checkin_settings"


class Day(Model):
    day = fields.CharField(max_length=10, primary_key=True)
    opened_at = fields.FloatField(null=True)
    open_reason = fields.TextField(default="")

    class Meta:
        table = "days"


class Visit(Model):
    id = fields.BigIntField(primary_key=True, generated=False, default=next_id)
    day = fields.TextField()
    subject = fields.TextField()
    username = fields.TextField()
    visitor = fields.TextField()
    ip_hash = fields.TextField()
    kind = fields.TextField()
    created_at = fields.FloatField()

    class Meta:
        table = "visits"


class Review(Model):
    day = fields.CharField(max_length=10, primary_key=True)
    user_id = fields.CharField(max_length=256)
    reason = fields.TextField()
    approved = fields.IntField(default=0)

    class Meta:
        table = "reviews"
        unique_together = (("day", "user_id"),)


class PracticeSession(Model):
    day = fields.CharField(max_length=10, primary_key=True)
    user_id = fields.CharField(max_length=256)
    token = fields.TextField()
    step = fields.IntField(default=0)
    updated_at = fields.FloatField()
    expires_at = fields.FloatField()
    min_seconds = fields.IntField()
    flow_id = fields.TextField(default="")
    eligible = fields.IntField(default=0)
    mode = fields.TextField(default="manual")
    repetitions = fields.IntField(default=3)
    interval_seconds = fields.IntField(null=True)

    class Meta:
        table = "sessions"
        unique_together = (("day", "user_id"),)


class Entry(Model):
    day = fields.CharField(max_length=10, primary_key=True)
    user_id = fields.CharField(max_length=256)
    username = fields.TextField()
    rank = fields.IntField()
    amount = fields.BigIntField()
    completed_at = fields.FloatField()
    claimed_at = fields.FloatField(null=True)
    reward_status = fields.TextField()
    flow_id = fields.TextField(null=True)

    class Meta:
        table = "entries"
        unique_together = (("day", "user_id"), ("day", "rank"))
