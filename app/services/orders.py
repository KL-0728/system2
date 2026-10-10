"""C module ordering workflow.

Cross-module providers never commit.  Public mutating methods are called by an
outer route transaction so draft, confirmation, order and audit rows stay
atomic.
"""
from __future__ import annotations

from datetime import date, timedelta
from hashlib import sha256
import json
import secrets

from flask import current_app

from app.contracts import (
    WARNING_LEVELS,
    WARNING_VERSION,
    OrderDTO,
    WarningDTO,
    dto_dict,
    quantity,
)
from app.extensions import db
from app.models import (
    DeliveryCycle,
    DraftItem,
    Order,
    OrderConfirmation,
    OrderDraft,
    OrderItem,
    PolicyVersion,
    Product,
    ReplenishmentRun,
    SubmissionKey,
    UserAcknowledgement,
)
from app.providers import get_provider
from app.services.audit import record_event
from app.services.clock import aware, business_now, server_now, utc_naive
from app.services.errors import DomainError
from app.services.version import bump_store, lock_store


INTRO_VERSION = 'ordering-intro-v1'
CONFIRMATION_TEXT_VERSION = 'ordering-confirmation-v1'
IMPORTANT_CODES = frozenset(code for code, level in WARNING_LEVELS.items() if level == 'important')
BLOCK_CODES = frozenset(code for code, level in WARNING_LEVELS.items() if level == 'block')
REASON_REQUIRED_CODES = frozenset({
    'LARGE_QUANTITY', 'DEVIATION', 'CAPACITY', 'MANUAL_FORECAST',
    'SPECIAL_DEMAND', 'DIRECT_ORDER',
})
GENERAL_REASON_CODES = frozenset({'promotion', 'local_demand', 'display', 'reduce_stock', 'skip', 'other'})


def _jsonable(value):
    return current_app.json.loads(current_app.json.dumps(value))


def _canonical(value):
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')


def _hash(value):
    return sha256(_canonical(value)).hexdigest()


def _token_hash(token):
    return sha256(token.encode('utf-8')).hexdigest()


def _require_dict(value, message='資料格式錯誤'):
    if not isinstance(value, dict):
        raise DomainError('INVALID_INPUT', message, 400)
    return value


def _policy(version, *, store_id, product_id):
    row = db.session.execute(db.select(PolicyVersion).where(
        PolicyVersion.store_id == store_id, PolicyVersion.product_id == product_id,
        PolicyVersion.version == version)).scalar_one_or_none()
    return _policy_parameters(row.parameters if row else {})


def _policy_parameters(parameters):
    return {
        'absolute_large_qty': int(parameters.get('absolute_large_qty', 100)),
        'deviation_floor': int(parameters.get('deviation_floor', 100)),
        'deviation_multiplier': int(parameters.get('deviation_multiplier', 3)),
        'confirmation_minutes': int(parameters.get('confirmation_minutes', 5)),
        'deduction_minutes': int(parameters.get('deduction_minutes', 60)),
    }


def _product_map(product_ids):
    rows = db.session.execute(db.select(Product).where(Product.id.in_(set(product_ids)))).scalars().all()
    return {row.id: row for row in rows}


def _warning_dict(warning):
    return _jsonable(dto_dict(warning))


def _append_warning(warnings, warning):
    identity = (warning.code, _hash(warning.details))
    if all((existing.code, _hash(existing.details)) != identity for existing in warnings):
        warnings.append(warning)


class OrderingService:
    """Owns C drafts, confirmation snapshots and reliable submission."""

    def acknowledgement_status(self, actor):
        row = db.session.execute(db.select(UserAcknowledgement).where(
            UserAcknowledgement.user_id == actor.id,
            UserAcknowledgement.text_version == INTRO_VERSION)).scalar_one_or_none()
        return {'version': INTRO_VERSION, 'acknowledged': row is not None,
            'acknowledged_at': aware(row.acknowledged_at) if row else None}

    def acknowledge_intro(self, actor, acknowledged):
        if acknowledged is not True:
            raise DomainError('ACKNOWLEDGEMENT_REQUIRED', '請勾選已了解說明', 422)
        row = db.session.execute(db.select(UserAcknowledgement).where(
            UserAcknowledgement.user_id == actor.id,
            UserAcknowledgement.text_version == INTRO_VERSION).with_for_update()).scalar_one_or_none()
        if row is None:
            row = UserAcknowledgement(user_id=actor.id, text_version=INTRO_VERSION,
                acknowledged_at=utc_naive(server_now()))
            db.session.add(row)
            record_event(actor.id, None, 'ordering.intro_acknowledged',
                f'user-acknowledgement:{INTRO_VERSION}', None, {'text_version': INTRO_VERSION})
        db.session.flush()
        return self.acknowledgement_status(actor)

    def _require_intro(self, actor):
        if not self.acknowledgement_status(actor)['acknowledged']:
            raise DomainError('ACKNOWLEDGEMENT_REQUIRED', '請先閱讀並確認首次使用說明', 422,
                {'text_version': INTRO_VERSION})

    def _owned_draft(self, draft_id, actor, *, lock=False):
        statement = db.select(OrderDraft).where(OrderDraft.id == draft_id)
        if lock:
            statement = statement.execution_options(populate_existing=True).with_for_update()
        draft = db.session.execute(statement).scalar_one_or_none()
        if not draft or draft.user_id != actor.id:
            raise DomainError('NOT_FOUND', '草稿不存在或不可存取', 404)
        from app.services.access import authorize_store
        authorize_store(actor, draft.store_id, roles=('manager', 'admin'))
        return draft

    @staticmethod
    def _require_open_cycle(cycle, now):
        if not cycle or cycle.cancelled:
            raise DomainError('INVALID_CYCLE', '配送輪次不可用', 409)
        if now < aware(cycle.baseline_at):
            raise DomainError('ROUND_NOT_OPEN', '本輪尚未開放訂購；請在畫面所列開放時間後操作', 409)
        if now >= aware(cycle.cutoff_at):
            raise DomainError('CUTOFF_PASSED', '本輪已截止，請取得下一輪建議後重新確認', 409)

    def _draft_items(self, draft_id, *, lock=False):
        statement = db.select(DraftItem).where(DraftItem.draft_id == draft_id).order_by(DraftItem.product_id)
        if lock:
            statement = statement.with_for_update()
        return list(db.session.execute(statement).scalars())

    def create_draft(self, actor, *, store_id, run_id, cycle_id, final_quantities=None):
        self._require_intro(actor)
        from app.services.access import authorize_store
        authorize_store(actor, store_id, roles=('manager', 'admin'))
        store = lock_store(store_id)
        now = business_now()
        run = get_provider('runs').get_run(run_id=run_id, store_id=store_id,
            actor_id=actor.id, session=db.session)
        if run.run_id != run_id or run.store_id != store_id:
            raise DomainError('PROVIDER_MISMATCH', '計算結果與門市不一致', 409)
        if run.store_version != store.calculation_version:
            raise DomainError('VERSION_CONFLICT', '計算資料已更新，請重新產生建議', 409,
                {'current_version': store.calculation_version})
        if run.cycle_id != cycle_id:
            raise DomainError('INVALID_CYCLE', '配送輪次與計算結果不一致', 422)
        cycle = db.session.get(DeliveryCycle, cycle_id)
        if not cycle or cycle.store_id != store_id or cycle.cancelled:
            raise DomainError('INVALID_CYCLE', '配送輪次不可用', 422)
        self._require_open_cycle(cycle, now)
        supplied = final_quantities or {}
        if not isinstance(supplied, dict):
            raise DomainError('INVALID_INPUT', 'final_quantities 必須是商品與件數對照', 400)
        draft = OrderDraft(store_id=store_id, user_id=actor.id, cycle_id=cycle_id,
            run_id=run_id, status='DRAFT', created_at=utc_naive(now), updated_at=utc_naive(now))
        db.session.add(draft)
        db.session.flush()
        for item in run.items:
            if item.run_item_id is None:
                raise DomainError('RUN_NOT_PERSISTED', '計算品項尚未持久化，無法建立草稿', 409)
            raw = supplied.get(str(item.product_id), supplied.get(item.product_id,
                item.suggested_qty if item.suggested_qty is not None else 0))
            final = quantity(raw)
            db.session.add(DraftItem(draft_id=draft.id, product_id=item.product_id,
                run_item_id=item.run_item_id, final_qty=final,
                manual_forecast_acknowledged=False))
        record_event(actor.id, store_id, 'order_draft.created', f'order-draft:{draft.id}', None,
            {'run_id': run_id, 'cycle_id': cycle_id, 'version': draft.version})
        db.session.flush()
        return self.draft_detail(draft, actor)

    def draft_detail(self, draft, actor):
        if draft.user_id != actor.id:
            raise DomainError('NOT_FOUND', '草稿不存在或不可存取', 404)
        items = self._draft_items(draft.id)
        products = _product_map(i.product_id for i in items)
        return {
            'id': draft.id, 'store_id': draft.store_id, 'run_id': draft.run_id,
            'cycle_id': draft.cycle_id, 'status': draft.status, 'version': draft.version,
            'created_at': aware(draft.created_at), 'updated_at': aware(draft.updated_at),
            'items': [{
                'product_id': item.product_id,
                'sku': products[item.product_id].sku,
                'name': products[item.product_id].name,
                'unit': products[item.product_id].base_unit,
                'pack_size': products[item.product_id].pack_size,
                'run_item_id': item.run_item_id,
                'final_qty': item.final_qty,
                'reason_code': item.reason_code,
                'reason': item.reason,
                'special_need': item.special_need,
                'manual_forecast_acknowledged': item.manual_forecast_acknowledged,
            } for item in items],
        }

    def get_draft(self, actor, draft_id):
        return self.draft_detail(self._owned_draft(draft_id, actor), actor)

    def update_draft(self, actor, draft_id, payload):
        payload = _require_dict(payload)
        draft = self._owned_draft(draft_id, actor)
        from app.services.access import authorize_store
        authorize_store(actor, draft.store_id, roles=('manager', 'admin'))
        lock_store(draft.store_id)
        draft = self._owned_draft(draft_id, actor, lock=True)
        if draft.status != 'DRAFT':
            raise DomainError('INVALID_STATE', '只有草稿可修改', 409)
        if payload.get('expected_version') != draft.version:
            raise DomainError('VERSION_CONFLICT', '草稿已更新，請重新載入', 409,
                {'current_version': draft.version})
        changes = payload.get('items')
        if not isinstance(changes, list) or not changes:
            raise DomainError('INVALID_INPUT', '請提供要修改的草稿品項', 400)
        rows = {item.product_id: item for item in self._draft_items(draft.id, lock=True)}
        old = {str(key): {'final_qty': row.final_qty, 'reason_code': row.reason_code,
            'reason': row.reason, 'special_need': row.special_need,
            'manual_forecast_acknowledged': row.manual_forecast_acknowledged}
            for key, row in rows.items()}
        seen = set()
        for change in changes:
            change = _require_dict(change, '草稿品項格式錯誤')
            product_id = change.get('product_id')
            if type(product_id) is not int or product_id not in rows or product_id in seen:
                raise DomainError('INVALID_INPUT', '草稿商品不存在或重複', 400)
            seen.add(product_id)
            row = rows[product_id]
            final = quantity(change.get('final_qty'))
            reason_code = change.get('reason_code')
            reason = change.get('reason')
            special = change.get('special_need')
            manual_ack = change.get('manual_forecast_acknowledged', False)
            if reason_code is not None and reason_code not in GENERAL_REASON_CODES:
                raise DomainError('INVALID_REASON', '未知的調整原因', 422, {'product_id': product_id})
            if final != row.final_qty and not reason_code:
                raise DomainError('REASON_REQUIRED', '修改數量或設為0必須選擇原因', 422,
                    {'product_id': product_id})
            if reason_code == 'other' and (not isinstance(reason, str) or not reason.strip()):
                raise DomainError('REASON_REQUIRED', '選擇其他時請填寫說明', 422,
                    {'product_id': product_id})
            if reason is not None and (not isinstance(reason, str) or len(reason.strip()) > 500):
                raise DomainError('INVALID_REASON', '理由最多500字', 422, {'product_id': product_id})
            if special is not None and not isinstance(special, dict):
                raise DomainError('INVALID_SPECIAL_NEED', '特殊需求格式錯誤', 400,
                    {'product_id': product_id})
            if manual_ack is not True and manual_ack is not False:
                raise DomainError('INVALID_INPUT', '人工預測確認必須是布林值', 400)
            row.final_qty, row.reason_code = final, reason_code
            row.reason = reason.strip() if isinstance(reason, str) and reason.strip() else None
            row.special_need = special
            row.manual_forecast_acknowledged = manual_ack
        draft.version += 1
        draft.updated_at = utc_naive(business_now())
        # Unsubmitted previews are disposable; every material edit invalidates them.
        db.session.execute(db.delete(OrderConfirmation).where(
            OrderConfirmation.draft_id == draft.id, OrderConfirmation.order_id.is_(None)))
        record_event(actor.id, draft.store_id, 'order_draft.updated', f'order-draft:{draft.id}', old,
            {'version': draft.version, 'changed_products': sorted(seen)})
        db.session.flush()
        return self.draft_detail(draft, actor)

    def _evaluate(self, actor, draft, *, evaluated_at):
        items = self._draft_items(draft.id)
        final_quantities = {item.product_id: item.final_qty for item in items}
        manual_confirmations = tuple(item.product_id for item in items if item.manual_forecast_acknowledged)
        run = get_provider('runs').evaluate(run_id=draft.run_id, store_id=draft.store_id,
            actor_id=actor.id, cycle_id=draft.cycle_id, final_quantities=final_quantities,
            manual_confirmations=manual_confirmations, evaluated_at=evaluated_at, session=db.session)
        if run.run_id != draft.run_id or run.store_id != draft.store_id or run.cycle_id != draft.cycle_id:
            raise DomainError('PROVIDER_MISMATCH', '重算結果與草稿不一致', 409)
        run_items = {item.product_id: item for item in run.items}
        products = _product_map(row.product_id for row in items)
        blocks = []
        output_items = []
        important_products = []
        confirmation_minutes = 5
        policy_rows = db.session.execute(db.select(PolicyVersion).where(
            PolicyVersion.store_id == draft.store_id,
            PolicyVersion.product_id.in_(run_items))).scalars().all()
        policies = {(p.product_id, p.version): p.parameters for p in policy_rows}
        for row in items:
            item = run_items.get(row.product_id)
            product = products.get(row.product_id)
            if item is None or product is None or item.run_item_id != row.run_item_id:
                raise DomainError('VERSION_CONFLICT', '計算品項已改變，請重建草稿', 409,
                    {'product_id': row.product_id})
            integrity = get_provider('integrity').get_integrity(store_id=draft.store_id,
                product_id=row.product_id, baseline_at=run.baseline_at, session=db.session)
            if integrity.store_id != draft.store_id or integrity.product_id != row.product_id:
                raise DomainError('PROVIDER_MISMATCH', '庫存完整性結果與門市商品不一致', 409)
            warnings = list(item.warnings)
            included = row.final_qty > 0
            if included and (item.mode == 'direct' or row.special_need is not None):
                self._validate_special_need(row)
            policy = _policy_parameters(policies.get((row.product_id, item.policy_version), {}))
            confirmation_minutes = min(confirmation_minutes, policy['confirmation_minutes'])
            if not integrity.usable:
                for warning in integrity.warnings:
                    _append_warning(warnings, warning)
                if not integrity.warnings:
                    _append_warning(warnings, WarningDTO('INVENTORY_GAP', '缺少有效盤點基準', {}))
            if row.final_qty % item.pack_size:
                _append_warning(warnings, WarningDTO('INVALID_PACK', '最終量不符合訂購單位',
                    {'pack_size': item.pack_size, 'lower': row.final_qty - row.final_qty % item.pack_size,
                        'upper': row.final_qty + item.pack_size - row.final_qty % item.pack_size}))
            if item.mode == 'unavailable':
                _append_warning(warnings, WarningDTO('FORECAST_INSUFFICIENT',
                    '缺乏有效預測；請改用合法人工預測或特殊直接訂購', {}))
            if item.mode == 'manual' and not row.manual_forecast_acknowledged:
                _append_warning(warnings, WarningDTO('MANUAL_FORECAST', '本輪尚未確認人工預測', {}))
            if item.mode == 'direct':
                _append_warning(warnings, WarningDTO('DIRECT_ORDER', '特殊直接訂購無法評估精確需求缺口', {}))
                if row.final_qty <= 0:
                    _append_warning(warnings, WarningDTO('INVALID_QUANTITY', '特殊直接訂購須指定正數', {}))
            suggested = item.suggested_qty
            if row.final_qty >= policy['absolute_large_qty']:
                _append_warning(warnings, WarningDTO('LARGE_QUANTITY', '大量需求須確認件／箱及收貨安排',
                    {'final_qty': row.final_qty, 'threshold': policy['absolute_large_qty']}))
            if suggested is not None and ((suggested == 0 and row.final_qty >= policy['deviation_floor']) or
                    (suggested > 0 and row.final_qty > max(policy['deviation_floor'],
                        policy['deviation_multiplier'] * suggested))):
                _append_warning(warnings, WarningDTO('DEVIATION', '最終量明顯高於系統建議',
                    {'suggested_qty': suggested, 'final_qty': row.final_qty}))
            if item.h is not None and row.final_qty + item.h > item.capacity:
                _append_warning(warnings, WarningDTO('CAPACITY', '到貨後可能高於常規容量',
                    {'capacity': item.capacity, 'h': item.h, 'final_qty': row.final_qty}))
            if row.special_need:
                _append_warning(warnings, WarningDTO('SPECIAL_DEMAND', '已知活動或團體需求須加強確認',
                    {'need_date': row.special_need.get('need_date'),
                        'need_qty': row.special_need.get('need_qty')}))
            # Excluded items remain in the decision snapshot, but cannot block
            # the valid positive items that will actually be ordered.
            block_codes = sorted({warning.code for warning in warnings if warning.code in BLOCK_CODES}) if included else []
            if block_codes:
                blocks.append({'product_id': row.product_id, 'codes': block_codes})
            important = sorted({warning.code for warning in warnings if warning.code in IMPORTANT_CODES}) if included else []
            reason_text = self._important_reason(row)
            if set(important) & REASON_REQUIRED_CODES and len(''.join(reason_text.split())) < 10:
                blocks.append({'product_id': row.product_id, 'codes': ['IMPORTANT_REASON_REQUIRED']})
            if important:
                important_products.append(row.product_id)
            sources = {'U': 0, 'C': 0, 'RISK': 0}
            for source in item.sources:
                sources[source.bucket] += source.quantity
            output_items.append({
                'product_id': row.product_id, 'run_item_id': row.run_item_id,
                'sku': product.sku, 'name': product.name, 'unit': product.base_unit,
                'pack_size': item.pack_size, 'mode': item.mode, 'h': item.h,
                'mu': item.mu, 'target_stock': item.target_stock, 'raw_qty': item.raw_qty,
                'suggested_qty': suggested, 'final_qty': row.final_qty,
                'adjusted': suggested is None or row.final_qty != suggested,
                'reason_code': row.reason_code, 'reason': row.reason,
                'special_need': row.special_need,
                'manual_forecast_acknowledged': row.manual_forecast_acknowledged,
                'manual_forecast': item.manual_forecast,
                'policy_version': item.policy_version, 'inventory_version': item.inventory_version,
                'policy_parameters': policy,
                'capacity': item.capacity, 'lead_days': item.lead_days,
                'safety_stock': item.safety_stock, 'sources': sources,
                'source_details': [dto_dict(source) for source in item.sources],
                'warnings': [_warning_dict(warning) for warning in warnings],
                'important_codes': important, 'input_snapshot': item.input_snapshot,
                'timeline_committed': item.timeline_committed,
                'timeline_with_pending': item.timeline_with_pending,
            })
        cycle = db.session.get(DeliveryCycle, draft.cycle_id)
        if not cycle or cycle.cancelled:
            blocks.append({'product_id': None, 'codes': ['INVALID_CYCLE']})
        snapshot = {
            'draft_id': draft.id, 'draft_version': draft.version,
            'store_id': draft.store_id, 'store_version': run.store_version,
            'run_id': run.run_id, 'cycle_id': draft.cycle_id,
            'baseline_at': run.baseline_at, 'data_through_at': run.data_through_at,
            'actual_generated_at': run.actual_generated_at,
            'risk_evaluated_at': evaluated_at, 'protection_end': run.protection_end,
            'model_version': run.model_version, 'warning_version': run.warning_version,
            'requested_arrival_at': aware(cycle.arrival_at) if cycle else None,
            'cutoff_at': aware(cycle.cutoff_at) if cycle else None,
            'intro_version': INTRO_VERSION,
            'confirmation_text_version': CONFIRMATION_TEXT_VERSION,
            'items': output_items,
            'important_product_ids': sorted(important_products),
        }
        stable = dict(snapshot)
        stable.pop('risk_evaluated_at')
        return snapshot, _hash(stable), blocks, confirmation_minutes

    @staticmethod
    def _validate_special_need(row):
        special = row.special_need
        invalid = []
        if not isinstance(special, dict):
            invalid = ['need_date', 'need_qty', 'arrangement']
        else:
            raw_date = special.get('need_date')
            try:
                if not isinstance(raw_date, str) or date.fromisoformat(raw_date).isoformat() != raw_date:
                    invalid.append('need_date')
            except ValueError:
                invalid.append('need_date')
            try:
                if quantity(special.get('need_qty')) <= 0:
                    invalid.append('need_qty')
            except DomainError:
                invalid.append('need_qty')
            arrangement = special.get('arrangement')
            if not isinstance(arrangement, str) or not arrangement.strip() or len(arrangement.strip()) > 200:
                invalid.append('arrangement')
        if invalid:
            raise DomainError('SPECIAL_NEED_REQUIRED', '請完整填寫特殊需求日期、需求量及存放／交付安排', 422,
                {'product_id': row.product_id, 'fields': invalid})

    @staticmethod
    def _important_reason(row):
        pieces = [row.reason or '']
        if row.special_need:
            pieces.extend(str(row.special_need.get(key) or '')
                for key in ('reason', 'need_date', 'need_qty', 'arrangement'))
        return ' '.join(pieces).strip()

    def preview(self, actor, draft_id, expected_version):
        self._require_intro(actor)
        draft = self._owned_draft(draft_id, actor)
        from app.services.access import authorize_store
        authorize_store(actor, draft.store_id, roles=('manager', 'admin'))
        store = lock_store(draft.store_id)
        draft = self._owned_draft(draft_id, actor, lock=True)
        if draft.status != 'DRAFT':
            raise DomainError('INVALID_STATE', '草稿已送出或不可預覽', 409)
        if expected_version != draft.version:
            raise DomainError('VERSION_CONFLICT', '草稿版本已更新，請重新載入', 409,
                {'current_version': draft.version})
        now = business_now()
        cycle = db.session.get(DeliveryCycle, draft.cycle_id)
        if not cycle or cycle.cancelled:
            raise DomainError('INVALID_CYCLE', '配送輪次已取消', 409)
        self._require_open_cycle(cycle, now)
        snapshot, content_hash, blocks, minutes = self._evaluate(actor, draft, evaluated_at=now)
        if snapshot['store_version'] != store.calculation_version:
            raise DomainError('VERSION_CONFLICT', '資料已更新，請重新產生建議', 409,
                {'current_version': store.calculation_version})
        if blocks:
            item_map = {item['product_id']: item for item in snapshot['items']}
            for block in blocks:
                item = item_map.get(block['product_id'])
                block['name'] = item['name'] if item else '訂購輪次'
                warnings = {warning['code']: warning['message'] for warning in item['warnings']} if item else {}
                block['messages'] = [
                    '重要例外理由至少需要10個非空白字元；請說明需求及收貨安排'
                    if code == 'IMPORTANT_REASON_REQUIRED' else warnings.get(code, '請重新核對訂購資料')
                    for code in block['codes']]
            message = '；'.join(f"{block['name']}：{'、'.join(block['messages'])}" for block in blocks)
            raise DomainError('PREVIEW_BLOCKED', message, 422, {'items': blocks})
        token = secrets.token_urlsafe(32)
        db.session.execute(db.delete(OrderConfirmation).where(
            OrderConfirmation.draft_id == draft.id, OrderConfirmation.order_id.is_(None)))
        row = OrderConfirmation(draft_id=draft.id, user_id=actor.id, store_id=draft.store_id,
            draft_version=draft.version, store_version=store.calculation_version,
            token_hash=_token_hash(token), payload_hash=content_hash,
            text_version=CONFIRMATION_TEXT_VERSION, warning_version=WARNING_VERSION,
            created_at=utc_naive(now), expires_at=utc_naive(now + timedelta(minutes=minutes)),
            risk_evaluated_at=utc_naive(now), order_acknowledged=False,
            exception_acknowledgements=[], snapshot=_jsonable(snapshot))
        db.session.add(row)
        db.session.flush()
        return {'confirmation_token': token, 'expires_at': aware(row.expires_at),
            'snapshot': snapshot}

    def _existing_submission(self, actor, store_id, key, payload_hash, *, lock=False):
        statement = db.select(SubmissionKey).where(SubmissionKey.user_id == actor.id,
            SubmissionKey.store_id == store_id, SubmissionKey.key == key)
        if lock:
            statement = statement.with_for_update()
        row = db.session.execute(statement).scalar_one_or_none()
        if row and row.payload_hash != payload_hash:
            raise DomainError('IDEMPOTENCY_CONFLICT', '同一冪等鍵的送出內容不同', 409)
        return row

    def submit(self, actor, draft_id, payload, idempotency_key):
        payload = _require_dict(payload)
        if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 100:
            raise DomainError('IDEMPOTENCY_KEY_REQUIRED', '請提供有效 Idempotency-Key', 400)
        key = idempotency_key.strip()
        draft = self._owned_draft(draft_id, actor)
        from app.services.access import authorize_store
        authorize_store(actor, draft.store_id, roles=('manager', 'admin'))
        submission_payload = {
            'draft_id': draft_id,
            'draft_version': payload.get('draft_version'),
            'confirmation_token': payload.get('confirmation_token'),
            'order_acknowledged': payload.get('order_acknowledged'),
            'exception_acknowledgements': payload.get('exception_acknowledgements'),
        }
        payload_hash = _hash(submission_payload)
        existing = self._existing_submission(actor, draft.store_id, key, payload_hash)
        if existing:
            return self.order_result(existing.order_id, replayed=True)
        store = lock_store(draft.store_id)
        draft = self._owned_draft(draft_id, actor, lock=True)
        existing = self._existing_submission(actor, draft.store_id, key, payload_hash, lock=True)
        if existing:
            return self.order_result(existing.order_id, replayed=True, current_read=True)
        prior_order = db.session.execute(db.select(Order).where(Order.draft_id == draft.id)
            .with_for_update()).scalar_one_or_none()
        if prior_order:
            raise DomainError('DRAFT_ALREADY_SUBMITTED', '此草稿已由另一請求送出', 409,
                {'order_id': prior_order.id})
        if draft.status != 'DRAFT' or payload.get('draft_version') != draft.version:
            raise DomainError('VERSION_CONFLICT', '草稿已更新或不可送出', 409,
                {'current_version': draft.version})
        token = payload.get('confirmation_token')
        if not isinstance(token, str):
            raise DomainError('CONFIRMATION_REQUIRED', '請先重新預覽並確認', 422)
        confirmation = db.session.execute(db.select(OrderConfirmation).where(
            OrderConfirmation.token_hash == _token_hash(token)).with_for_update()).scalar_one_or_none()
        if not confirmation or confirmation.draft_id != draft.id or confirmation.user_id != actor.id:
            raise DomainError('CONFIRMATION_INVALID', '確認憑證無效，請重新預覽', 409)
        if confirmation.order_id is not None:
            raise DomainError('CONFIRMATION_USED', '確認憑證已使用', 409)
        now = business_now()
        cycle = db.session.get(DeliveryCycle, draft.cycle_id)
        if now >= aware(confirmation.expires_at):
            raise DomainError('CONFIRMATION_EXPIRED', '確認已超過五分鐘，請重新預覽', 409)
        self._require_open_cycle(cycle, now)
        if confirmation.draft_version != draft.version or confirmation.store_version != store.calculation_version:
            raise DomainError('VERSION_CONFLICT', '資料已更新，請重新預覽', 409,
                {'current_version': store.calculation_version})
        snapshot, content_hash, blocks, _ = self._evaluate(actor, draft, evaluated_at=now)
        if blocks or content_hash != confirmation.payload_hash:
            raise DomainError('RISK_CHANGED', '數量、資料或風險已改變，請重新預覽', 409,
                {'items': blocks, 'repreview_required': True})
        if payload.get('order_acknowledged') is not True:
            raise DomainError('ORDER_ACK_REQUIRED', '請勾選本單總覽確認', 422)
        acknowledgements = self._validate_exception_acknowledgements(
            snapshot['important_product_ids'], payload.get('exception_acknowledgements'))
        positive = [item for item in snapshot['items'] if item['final_qty'] > 0]
        if not positive:
            raise DomainError('EMPTY_ORDER', '本次無需補貨，不送出空白補貨單', 422)
        number = f"S2-{draft.store_id}-{now.strftime('%Y%m%d%H%M%S')}-{draft.id}"
        order = Order(store_id=draft.store_id, user_id=actor.id, draft_id=draft.id,
            cycle_id=draft.cycle_id, number=number, submitted_at=utc_naive(now),
            status='SUBMITTED', fixture_only=False)
        db.session.add(order)
        db.session.flush()
        deduction_minutes = min(item['policy_parameters']['deduction_minutes'] for item in positive)
        deduction_expires_at = min(now + timedelta(minutes=deduction_minutes), aware(cycle.arrival_at))
        for item in positive:
            db.session.add(OrderItem(order_id=order.id, product_id=item['product_id'],
                original_qty=item['final_qty'], product_snapshot={
                    'sku': item['sku'], 'name': item['name'], 'unit': item['unit'],
                    'pack_size': item['pack_size'], 'suggested_qty': item['suggested_qty'],
                    'mode': item['mode'], 'warnings': item['warnings'],
                }, deduction_expires_at=utc_naive(deduction_expires_at)))
        final_snapshot = _jsonable({**snapshot,
            'actor': {'id': actor.id, 'role': actor.role},
            'order_number': number, 'submission_key': key,
            'submitted_at': now, 'server_time': server_now(),
            'payload_hash': payload_hash,
            'order_acknowledged': True,
            'exception_acknowledgements': acknowledgements,
        })
        confirmation.order_id = order.id
        confirmation.acknowledged_at = utc_naive(now)
        confirmation.order_acknowledged = True
        confirmation.exception_acknowledgements = acknowledgements
        confirmation.snapshot = final_snapshot
        draft.status = 'SUBMITTED'
        draft.updated_at = utc_naive(now)
        draft.version += 1
        db.session.add(SubmissionKey(user_id=actor.id, store_id=draft.store_id, key=key,
            payload_hash=payload_hash, order_id=order.id))
        bump_store(store)
        record_event(actor.id, draft.store_id, 'order.submitted', f'order:{order.id}', None,
            {'number': number, 'draft_id': draft.id, 'item_count': len(positive)})
        db.session.flush()
        return self.order_result(order.id, replayed=False)

    @staticmethod
    def _validate_exception_acknowledgements(required_ids, value):
        if not isinstance(value, list):
            raise DomainError('EXCEPTION_ACK_REQUIRED', '請逐項處理重要例外', 422)
        result = []
        seen = set()
        for entry in value:
            entry = _require_dict(entry, '重要例外確認格式錯誤')
            product_id = entry.get('product_id')
            if type(product_id) is not int or product_id in seen:
                raise DomainError('EXCEPTION_ACK_INVALID', '重要例外商品重複或錯誤', 422)
            seen.add(product_id)
            if entry.get('acknowledged') is not True or entry.get('warning_version') != WARNING_VERSION:
                raise DomainError('EXCEPTION_ACK_REQUIRED', '重要例外須主動勾選目前版本', 422,
                    {'product_id': product_id})
            handling = entry.get('handling')
            reason = entry.get('reason')
            if not isinstance(handling, str) or not handling.strip():
                raise DomainError('EXCEPTION_HANDLING_REQUIRED', '請選擇重要例外處理方式', 422,
                    {'product_id': product_id})
            if handling.strip() == 'exclude':
                raise DomainError('EXCLUSION_REQUIRES_EDIT', '排除品項須先將草稿數量改為0，再重新預覽', 422,
                    {'product_id': product_id, 'repreview_required': True})
            if reason is not None and (not isinstance(reason, str) or len(reason.strip()) > 500):
                raise DomainError('INVALID_REASON', '例外理由最多500字', 422,
                    {'product_id': product_id})
            result.append({'product_id': product_id, 'acknowledged': True,
                'warning_version': WARNING_VERSION, 'handling': handling.strip(),
                'reason': reason.strip() if isinstance(reason, str) else None})
        if seen != set(required_ids):
            raise DomainError('EXCEPTION_ACK_REQUIRED', '重要例外尚未全部確認', 422,
                {'required_product_ids': required_ids, 'received_product_ids': sorted(seen)})
        return sorted(result, key=lambda item: item['product_id'])

    def order_result(self, order_id, *, replayed, current_read=False):
        # A competing transaction may have committed after our first consistent
        # read. MySQL REPEATABLE READ requires a current read after the store lock.
        if current_read:
            order = db.session.execute(db.select(Order).where(Order.id == order_id)
                .execution_options(populate_existing=True).with_for_update(read=True)).scalar_one_or_none()
        else:
            order = db.session.get(Order, order_id)
        if not order:
            raise DomainError('NOT_FOUND', '訂單不存在', 404)
        return {'order_id': order.id, 'number': order.number, 'status': order.status,
            'submitted_at': aware(order.submitted_at), 'replayed': replayed}

    def submission_result(self, actor, store_id, key):
        from app.services.access import authorize_store
        authorize_store(actor, store_id, roles=('manager', 'admin'))
        row = db.session.execute(db.select(SubmissionKey).where(SubmissionKey.user_id == actor.id,
            SubmissionKey.store_id == store_id, SubmissionKey.key == key)).scalar_one_or_none()
        if not row:
            raise DomainError('NOT_FOUND', '尚未找到此送出結果', 404)
        return self.order_result(row.order_id, replayed=True)

    def get_order(self, *, order_id, store_id, actor_id, session):
        from flask import current_app
        from app.models import User
        from app.services.access import authorize_store
        actor = session.get(User, actor_id)
        authorize_store(actor, store_id, roles=('manager', 'operator', 'admin'))
        order = session.get(Order, order_id)
        fixture_allowed = current_app.config['APP_ENV'] == 'test' or current_app.config['MODULE_DEV'] == 'D'
        if not order or order.store_id != store_id or (order.fixture_only and not fixture_allowed):
            raise DomainError('NOT_FOUND', '訂單不存在', 404)
        items = session.execute(db.select(OrderItem).where(OrderItem.order_id == order.id)
            .order_by(OrderItem.id)).scalars().all()
        confirmation = session.execute(db.select(OrderConfirmation).where(
            OrderConfirmation.order_id == order.id)).scalar_one()
        return OrderDTO(order.id, order.store_id, order.cycle_id, order.version,
            aware(order.submitted_at), tuple({
                'id': item.id, 'product_id': item.product_id,
                'original_qty': item.original_qty,
                'product_snapshot': item.product_snapshot,
            } for item in items), confirmation.snapshot)


ordering_service = OrderingService()
