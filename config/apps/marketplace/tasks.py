from celery import shared_task

from .services import create_daily_settlement_batches


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def create_daily_settlement_batches_task(self):
    """Prepare daily vendor settlement batches; never initiate bank transfers."""
    batches = create_daily_settlement_batches()
    return {"created": len(batches), "batch_ids": [batch.id for batch in batches]}
