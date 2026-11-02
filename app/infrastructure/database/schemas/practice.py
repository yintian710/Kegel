from __future__ import annotations

from tortoise import fields
from tortoise.models import Model

from app.utils.snowflake import next_id


class PracticeTrigger(Model):
    id = fields.BigIntField(primary_key=True, generated=False, default=next_id)
    day = fields.TextField()
    user_id = fields.TextField()
    username = fields.TextField()
    flow_id = fields.TextField()
    group_no = fields.IntField()
    min_seconds = fields.IntField()
    created_at = fields.FloatField()
    mode = fields.TextField(default="manual")
    repetitions = fields.IntField(default=3)

    class Meta:
        table = "practice_triggers"
        unique_together = (("flow_id", "group_no"),)


class TrainingRecord(Model):
    id = fields.BigIntField(primary_key=True, generated=False, default=next_id)
    user_id = fields.TextField()
    username = fields.TextField()
    day = fields.TextField()
    round_id = fields.TextField()
    started_at = fields.BigIntField()
    ended_at = fields.BigIntField()
    repetitions = fields.IntField()
    interval_seconds = fields.IntField()
    mode = fields.TextField()
    received_at = fields.BigIntField()

    class Meta:
        table = "training_records"
        unique_together = (("user_id", "round_id"),)
