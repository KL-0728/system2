"""Select persisted runs for the installed provider without replacing providers."""
from flask import current_app
from app.extensions import db
from app.models import ReplenishmentRun
from app.providers import get_provider
from app.services.errors import DomainError

FIXTURE_VERSIONS = ('fixture-v1', 'controlled-test-v1')
STALE_DRAFT_MESSAGE = '此草稿使用的建議已不適用於目前服務。原草稿已保留；請準備本輪建議後重新建立草稿。'


def run_source_filter():
    entry = current_app.extensions['service_providers'].get('runs')
    if entry is None:
        return db.false()
    provider = get_provider('runs')  # Enforce environment restrictions too.
    versions = getattr(provider, 'run_model_versions', None)
    if versions is not None:
        return ReplenishmentRun.model_version.in_(versions)
    # Older v1 providers need no new method or registration argument.
    if entry[1]:
        return ReplenishmentRun.model_version == 'controlled-test-v1'
    return ReplenishmentRun.model_version.not_in(FIXTURE_VERSIONS)


def latest_run(store_id, *, session=None):
    session = session if session is not None else db.session
    return session.execute(db.select(ReplenishmentRun).where(
        ReplenishmentRun.store_id == store_id, run_source_filter()).order_by(
        ReplenishmentRun.actual_generated_at.desc(), ReplenishmentRun.id.desc())).scalars().first()


def run_source_available(run_id, store_id, *, session=None):
    session = session if session is not None else db.session
    return session.execute(db.select(ReplenishmentRun.id).where(
        ReplenishmentRun.id == run_id, ReplenishmentRun.store_id == store_id,
        run_source_filter())).first() is not None


def require_draft_source(draft):
    get_provider('runs')  # A genuinely missing service remains a 503.
    if not run_source_available(draft.run_id, draft.store_id):
        raise DomainError('DRAFT_SOURCE_UNAVAILABLE', STALE_DRAFT_MESSAGE, 409,
            {'draft_id': draft.id, 'run_id': draft.run_id, 'store_id': draft.store_id})
