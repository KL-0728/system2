"""B02 sales imports. All effects use the caller's transaction and real B writer."""
import csv
from datetime import date, datetime, time, timedelta, timezone
from io import StringIO
import re

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.contracts import InventoryMutation, quantity
from app.extensions import db
from app.models import (Inventory, InventoryReconciliation, Product, SalesDaily, SalesImportBatch, StoreProduct)
from app.services.clock import TAIPEI, aware, utc_naive
from app.services.errors import DomainError
from app.services.inventory import (_audit, _authorize, _business_now, _hash, _inventory,
    _lock_store, _posted_day, _text, InventoryService)
from app.services.version import bump_store

COLUMNS = ('source_batch_id', 'store_code', 'sku', 'business_date', 'sold_qty', 'was_stockout', 'is_open')
MAX_BYTES = 512 * 1024
MAX_ROWS = 2000


def _serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='b-sales-validation-v1')


def _canonical(payload):
    if not isinstance(payload, dict):
        raise DomainError('INVALID_INPUT', '請提供 JSON 物件', 400)
    store_id = quantity(payload.get('store_id'), minimum=1, maximum=2_147_483_647)
    mode = payload.get('import_mode')
    if mode not in ('historical', 'daily_posting'):
        raise DomainError('INVALID_MODE', '請明確選擇歷史資料或日常入帳', 400)
    text = payload.get('csv_text')
    if not isinstance(text, str) or not text.strip():
        raise DomainError('INVALID_CSV', '請選擇非空 UTF-8 CSV', 400)
    try:
        size = len(text.encode('utf-8'))
    except UnicodeEncodeError:
        raise DomainError('INVALID_CSV', 'CSV 必須是有效 UTF-8 文字', 400)
    if size > MAX_BYTES:
        raise DomainError('CSV_TOO_LARGE', 'CSV 不得超過512 KiB', 413)
    replacement = payload.get('replaces_batch_id')
    if replacement is not None:
        quantity(replacement, minimum=1, maximum=2_147_483_647)
    reason = payload.get('reason', '')
    if not isinstance(reason, str) or len(reason) > 500:
        raise DomainError('INVALID_INPUT', '理由不得超過500字元', 400)
    if replacement:
        _text(reason, '更正理由', 500)
    return dict(store_id=store_id, import_mode=mode, csv_text=text.lstrip('\ufeff').replace('\r\n', '\n'),
        replaces_batch_id=replacement, reason=reason.strip())


def _parse(text, store, now):
    """Report all row errors; never accept partial data."""
    errors, rows, seen = [], [], set()
    try:
        reader = csv.DictReader(StringIO(text, newline=''), strict=True)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            return [], [dict(line=1, code='CSV_HEADER', message='欄位及順序須為：' + ','.join(COLUMNS))]
        for line, raw in enumerate(reader, 2):
            if line > MAX_ROWS + 1:
                errors.append(dict(line=line, code='CSV_TOO_MANY_ROWS', message='整批最多2000列'))
                break
            try:
                if None in raw or any(value is None for value in raw.values()):
                    raise DomainError('CSV_COLUMNS', '欄位數量不符')
                raw = {key: value.strip() for key, value in raw.items()}
                source = _text(raw['source_batch_id'], '來源批次', 100)
                if raw['store_code'] != store.code:
                    raise DomainError('STORE_MISMATCH', 'CSV 含其他門市，整批拒絕')
                sku = _text(raw['sku'], '商品代碼', 32)
                day = date.fromisoformat(raw['business_date'])
                if day.isoformat() != raw['business_date']:
                    raise DomainError('INVALID_DATE', '日期須為 YYYY-MM-DD')
                end = datetime.combine(day, time(21), TAIPEI).astimezone(timezone.utc)
                if end > now:
                    raise DomainError('FUTURE_SALES', '銷售區間尚未結束')
                if not re.fullmatch(r'0|[1-9][0-9]{0,6}', raw['sold_qty']):
                    raise DomainError('INVALID_QUANTITY', '銷售須為0至1000000整數件數')
                sold = quantity(int(raw['sold_qty']))
                if raw['was_stockout'] not in ('0', '1') or raw['is_open'] not in ('0', '1'):
                    raise DomainError('INVALID_FLAG', '營業／缺貨欄位只接受0或1')
                if raw['is_open'] == '0' and sold:
                    raise DomainError('CLOSED_SALES', '未營業日不得填正數銷售')
                identity = (sku, day)
                if identity in seen:
                    raise DomainError('DUPLICATE_ROW', '同商品及營業日重複')
                seen.add(identity)
                rows.append(dict(line=line, source_batch_id=source, sku=sku,
                    business_date=day.isoformat(), sold_qty=sold,
                    was_stockout=raw['was_stockout'] == '1', is_open=raw['is_open'] == '1',
                    interval_start=(end - timedelta(days=1)).isoformat(), interval_end=end.isoformat()))
            except (ValueError, OverflowError, DomainError) as error:
                errors.append(dict(line=line, code=getattr(error, 'code', 'INVALID_DATE'),
                    message=str(error) if isinstance(error, DomainError) else '日期格式不正確'))
        if rows and len({row['source_batch_id'] for row in rows}) != 1:
            errors.append(dict(line=1, code='MIXED_BATCH', message='整批只能使用一個來源批次識別'))
        if not rows and not errors:
            errors.append(dict(line=2, code='EMPTY_CSV', message='CSV 沒有資料列'))
    except csv.Error:
        errors.append(dict(line=1, code='CSV_SYNTAX', message='CSV 引號或格式錯誤'))
    return rows, errors


class SalesService:
    def _plan(self, *, payload, actor_id, session):
        data = _canonical(payload)
        store = _lock_store(session, data['store_id'])
        _authorize(session, actor_id, store, count=True)
        now = _business_now(session)
        rows, errors = _parse(data['csv_text'], store, now)
        if errors:
            return data, store, now, rows, errors
        source = rows[0]['source_batch_id']
        products = session.execute(db.select(Product).join(StoreProduct,
            StoreProduct.product_id == Product.id).where(StoreProduct.store_id == store.id,
            StoreProduct.active.is_(True), Product.active.is_(True))).scalars().all()
        by_sku = {product.sku: product for product in products}
        # The store lock serializes the entire batch; acquire all inventory locks in product order.
        inventories = {product_id: _inventory(session, store.id, product_id, lock=True)
            for product_id in sorted({by_sku[row['sku']].id for row in rows if row['sku'] in by_sku})}
        existing_batch = session.execute(db.select(SalesImportBatch).where(
            SalesImportBatch.store_id == store.id, SalesImportBatch.source_batch_id == source)
            .with_for_update()).scalar_one_or_none()
        if existing_batch:
            errors.append(dict(line=1, code='BATCH_EXISTS', message='此批次已提交；使用原提交重試，或新批次明確更正'))
            return data, store, now, rows, errors
        target = data['replaces_batch_id']
        if target:
            batch = session.execute(db.select(SalesImportBatch).where(
                SalesImportBatch.id == target, SalesImportBatch.store_id == store.id)
                .with_for_update()).scalar_one_or_none()
            if batch is None:
                raise DomainError('NOT_FOUND', '更正批次不存在或不可存取', 404)
        identities = set()
        for row in rows:
            try:
                product = by_sku.get(row['sku'])
                if not product:
                    raise DomainError('UNKNOWN_PRODUCT', '本店無此啟用商品')
                inventory = inventories[product.id]
                day = date.fromisoformat(row['business_date'])
                old = session.execute(db.select(SalesDaily).where(SalesDaily.store_id == store.id,
                    SalesDaily.product_id == product.id, SalesDaily.business_date == day)
                    .execution_options(populate_existing=True).with_for_update()).scalar_one_or_none()
                end = datetime.fromisoformat(row['interval_end'])
                covered = end <= aware(inventory.counted_at)
                posted = old is not None and old.applied_at is not None and old.movement_id is not None
                if old and (not target or old.batch_id != target):
                    raise DomainError('SALES_EXISTS', '區間已有資料，須指定目前批次及更正理由')
                if target and old is None:
                    raise DomainError('CORRECTION_SCOPE', '更正不能新增其他銷售區間')
                if old and (old.import_mode == 'daily_posting' or old.applied_at or old.movement_id):
                    if not _posted_day(session, store.id, product.id, end, lock=True):
                        raise DomainError('INVALID_POSTING_SOURCE', '原日常入帳來源不完整，須先核對來源，不能重扣')
                if posted and data['import_mode'] != 'daily_posting':
                    raise DomainError('DAILY_MODE_REQUIRED', '已入帳資料更正須維持日常模式')
                if data['import_mode'] == 'daily_posting' and not posted and covered:
                    raise DomainError('COUNT_COVERED', '此區間已被盤點涵蓋，不可再扣庫存；只可歷史更正並對帳')
                stock_delta = 0
                reconciliation = bool(old and covered and (
                    row['sold_qty'] != old.sold_qty or row['was_stockout'] != old.was_stockout
                    or row['is_open'] != old.is_open))
                if data['import_mode'] == 'daily_posting' and not covered:
                    stock_delta = (old.sold_qty if posted else 0) - row['sold_qty']
                row.update(product_id=product.id, name=product.name, old_sales_id=old.id if old else None,
                    old_sold_qty=old.sold_qty if old else None, old_version=old.version if old else None,
                    inventory_version=inventory.version, stock_delta=stock_delta,
                    count_covered=covered, reconciliation=reconciliation,
                    action='reconcile' if reconciliation else ('post' if data['import_mode'] == 'daily_posting'
                        and not covered else 'forecast_only'))
                identities.add(old.id if old else None)
            except DomainError as error:
                errors.append(dict(line=row['line'], code=error.code, message=error.message))
        if target:
            active_ids = set(session.execute(db.select(SalesDaily.id).where(
                SalesDaily.store_id == store.id, SalesDaily.batch_id == target).with_for_update()).scalars())
            snapshot = batch.snapshot
            original_count = len(snapshot.get('rows', [])) if 'rows' in snapshot else len(active_ids)
            if active_ids != identities or len(active_ids) != original_count:
                errors.append(dict(line=1, code='CORRECTION_SCOPE',
                    message='須整批更正原批次所有有效列；不可部分取代或取代已被其他批次更正的資料'))
        return data, store, now, rows, errors

    def validate(self, *, payload, actor_id, session):
        data, store, now, rows, errors = self._plan(payload=payload, actor_id=actor_id, session=session)
        result = dict(valid=not errors, errors=errors, rows=rows, store_version=store.calculation_version,
            import_mode=data['import_mode'], message='整批未寫入；請核對每列區間與庫存影響')
        if not errors:
            result['validation_token'] = _serializer().dumps(dict(actor_id=actor_id, store_id=store.id,
                payload_hash=_hash(data), store_version=store.calculation_version))
        return result

    def commit(self, *, payload, actor_id, validation_token, session):
        data = _canonical(payload)
        store = _lock_store(session, data['store_id'])
        _authorize(session, actor_id, store, count=True)
        rows, errors = _parse(data['csv_text'], store, _business_now(session))
        if errors:
            raise DomainError('CSV_INVALID', 'CSV 整批驗證失敗', details={'errors': errors})
        payload_hash = _hash(data)
        # Even success replays obey Store -> ordered Inventory -> source-key locking.
        product_ids = session.execute(db.select(Product.id).join(
            Inventory, Inventory.product_id == Product.id).where(Inventory.store_id == store.id,
            Product.sku.in_([row['sku'] for row in rows]))).scalars().all()
        for product_id in sorted(set(product_ids)):
            _inventory(session, store.id, product_id, lock=True)
        batch = session.execute(db.select(SalesImportBatch).where(SalesImportBatch.store_id == store.id,
            SalesImportBatch.source_batch_id == rows[0]['source_batch_id']).with_for_update()).scalar_one_or_none()
        if batch:
            if batch.payload_hash != payload_hash or batch.actor_id != actor_id:
                raise DomainError('IDEMPOTENCY_CONFLICT', '同一批次識別內容或提交者不同', 409)
            if 'result' not in batch.snapshot:
                raise DomainError('SOURCE_RESULT_UNAVAILABLE', '此舊批次無正式提交快照', 409)
            return {**batch.snapshot['result'], 'replayed': True}
        try:
            if not isinstance(validation_token, str) or len(validation_token) > 2000:
                raise BadSignature('Invalid token format')
            token = _serializer().loads(validation_token, max_age=900)
        except (BadSignature, SignatureExpired, TypeError):
            raise DomainError('VALIDATION_EXPIRED', '驗證無效或超過15分鐘，請重新驗證', 409)
        if not isinstance(token, dict) or token != dict(actor_id=actor_id, store_id=store.id,
                payload_hash=payload_hash, store_version=store.calculation_version):
            raise DomainError('VALIDATION_STALE', '內容或庫存基準已變更，請重新驗證整批', 409)
        data, store, now, rows, errors = self._plan(payload=data, actor_id=actor_id, session=session)
        if errors:
            raise DomainError('CSV_INVALID', 'CSV 整批驗證失敗', details={'errors': errors})
        batch = SalesImportBatch(store_id=store.id, source_batch_id=rows[0]['source_batch_id'],
            payload_hash=payload_hash, import_mode=data['import_mode'],
            replaces_batch_id=data['replaces_batch_id'], actor_id=actor_id, created_at=utc_naive(now),
            snapshot={'pending': True})
        session.add(batch)
        session.flush()
        result_rows = []
        writer = InventoryService()
        for item in sorted(rows, key=lambda row: (row['product_id'], row['business_date'])):
            inventory = _inventory(session, store.id, item['product_id'], lock=True)
            old = session.get(SalesDaily, item['old_sales_id']) if item['old_sales_id'] else None
            row = old or SalesDaily(store_id=store.id, product_id=item['product_id'],
                business_date=date.fromisoformat(item['business_date']), version=1)
            previous = None if old is None else dict(sold_qty=old.sold_qty, batch_id=old.batch_id,
                import_mode=old.import_mode, applied_at=aware(old.applied_at).isoformat() if old.applied_at else None,
                movement_id=old.movement_id, version=old.version)
            row.interval_start = utc_naive(datetime.fromisoformat(item['interval_start']))
            row.interval_end = utc_naive(datetime.fromisoformat(item['interval_end']))
            row.sold_qty, row.was_stockout, row.is_open = item['sold_qty'], item['was_stockout'], item['is_open']
            row.batch_id, row.event_note = batch.id, data['reason'] or None
            if old:
                row.version += 1
            if item['action'] == 'post':
                source_type = 'sales_correction' if previous and previous['applied_at'] else 'sales'
                mutation = InventoryMutation(store.id, item['product_id'], source_type,
                    f'sales-batch:{batch.id}:{item["business_date"]}', item['stock_delta'], 0,
                    inventory.version, actor_id, datetime.fromisoformat(item['interval_end']),
                    data['reason'] or '日常銷售整批入帳')
                movement = writer.apply_movement(mutation=mutation, session=session)
                row.import_mode, row.applied_at, row.movement_id = 'daily_posting', utc_naive(now), movement.movement_id
            elif not previous or not previous['applied_at']:
                row.import_mode, row.applied_at, row.movement_id = 'historical', None, None
            if item['reconciliation']:
                session.add(InventoryReconciliation(store_id=store.id, product_id=item['product_id'],
                    source_type='sales_covered', source_id=f'sales-batch:{batch.id}:{item["business_date"]}',
                    reason=('已盤點涵蓋銷售更正，未回頭改目前庫存：' + data['reason'])[:500], status='OPEN',
                    created_at=utc_naive(now), resolution={'business_date': item['business_date'], 'batch_id': batch.id}))
            session.add(row)
            session.flush()
            result_rows.append(dict(product_id=item['product_id'], business_date=item['business_date'],
                sales_id=row.id, sold_qty=row.sold_qty, sales_version=row.version, stock_delta=item['stock_delta'],
                reconciliation=item['reconciliation'], physical_book=inventory.book_physical_qty,
                inventory_version=inventory.version, previous=previous))
        # Historical/metadata changes also invalidate C confirmations.
        bump_store(store)
        result = dict(batch_id=batch.id, source_batch_id=batch.source_batch_id, import_mode=batch.import_mode,
            store_id=store.id, store_version=store.calculation_version, count=len(rows),
            stock_delta=sum(row['stock_delta'] for row in rows), rows=result_rows, replayed=False)
        batch.snapshot = dict(input=data, rows=rows, result=result, validated_at=now.isoformat())
        _audit(session, actor_id, store.id, 'sales.commit', f'sales-batch:{batch.id}',
            None, {'batch_id': batch.id, 'payload_hash': payload_hash, 'result': result}, now)
        session.flush()
        return result
