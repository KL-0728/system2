"""Administrator changes share store locks and preserve historical policies."""
import hashlib
import json
from datetime import time, timedelta
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import Store, User, Product, StoreProduct, PolicyVersion, Inventory, DeliveryCycle
from app.services.audit import record_event
from app.services.clock import business_now, utc_naive, round_window
from app.services.errors import DomainError
from app.services.version import bump_store
from app.seed import POLICY

MODELS = {'products': Product, 'stores': Store, 'users': User, 'policies': StoreProduct}
POLICY_FIELDS = ('lead_days', 'safety_stock', 'capacity', 'absolute_large_qty',
    'deviation_floor', 'deviation_multiplier', 'confirmation_minutes', 'deduction_minutes',
    'supply_response_minutes', 'receipt_minutes', 'variance_hours', 'contact_minutes', 'manual_valid_days')


def invalid(message):
    raise DomainError('INVALID_INPUT', message, 422)


def integer(value, label, minimum=0, maximum=1000000):
    if type(value) is not int or not minimum <= value <= maximum:
        invalid(f'{label}須為{minimum}至{maximum}的整數')
    return value


def text(value, label, limit):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        invalid(f'{label}必填，最多{limit}字')
    return value.strip()


def state(kind, row):
    if kind == 'products':
        result = {k: getattr(row, k) for k in ('id', 'sku', 'name', 'base_unit', 'pack_size', 'active')}
    elif kind == 'stores':
        result = {k: getattr(row, k) for k in ('id', 'code', 'name', 'active', 'calculation_version')}
        result['cutoff'] = row.cutoff.strftime('%H:%M')
    elif kind == 'users':
        result = {k: getattr(row, k) for k in ('id', 'username', 'role', 'active')}
        result['store_ids'] = sorted(s.id for s in row.stores)
    else:
        version = db.session.get(PolicyVersion, row.policy_version_id)
        result = dict(id=row.id, store_id=row.store_id, product_id=row.product_id,
            active=row.active, version=version.version, **version.parameters)
    return result


def revision(kind, row):
    data = state(kind, row)
    if kind == 'users':
        data['password_hash'] = row.password_hash
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def serialize(kind, row):
    return {**state(kind, row), 'revision': revision(kind, row)}


def publish_policy(row, parameters):
    old = db.session.get(PolicyVersion, row.policy_version_id) if row.policy_version_id else None
    version = PolicyVersion(store_id=row.store_id, product_id=row.product_id,
        version=old.version + 1 if old else 1, effective_at=utc_naive(business_now()),
        parameters=parameters)
    db.session.add(version)
    db.session.flush()
    row.policy_version_id = version.id
    for field in ('lead_days', 'safety_stock', 'capacity'):
        setattr(row, field, parameters[field])


def save(actor, kind, data, row_id=None):
    if not actor or not actor.active or actor.role != 'admin':
        raise DomainError('FORBIDDEN', '僅管理者可維護設定', 403)
    if kind not in MODELS or not isinstance(data, dict):
        invalid('請提供有效的管理資料')
    # All management writes use the same ascending store lock order as B/C/D.
    stores = db.session.execute(db.select(Store).order_by(Store.id)
        .execution_options(populate_existing=True).with_for_update()).scalars().all()
    actor = db.session.execute(db.select(User).where(User.id == actor.id)
        .execution_options(populate_existing=True).with_for_update()).scalar_one()
    if not actor.active or actor.role != 'admin':
        raise DomainError('FORBIDDEN', '管理權限已變更，請重新登入', 403)
    row = db.session.execute(db.select(MODELS[kind]).where(MODELS[kind].id == row_id)
        .execution_options(populate_existing=True).with_for_update()).scalar_one_or_none() if row_id else None
    if row_id and row is None:
        raise DomainError('NOT_FOUND', '資料不存在', 404)
    if row and data.get('revision') != revision(kind, row):
        raise DomainError('VERSION_CONFLICT', '設定已更新，請重新載入再修改', 409)
    old = state(kind, row) if row else None
    active = data.get('active', True)
    if type(active) is not bool:
        invalid('啟用狀態須為布林值')
    affected = set()
    if kind == 'products':
        sku = text(data.get('sku'), '商品代碼', 32)
        name = text(data.get('name'), '商品名稱', 120)
        unit = text(data.get('base_unit', '件'), '基本單位', 16)
        pack = integer(data.get('pack_size'), '箱入數', 1)
        if row and row.sku != sku:
            invalid('既有商品代碼不可修改')
        row = row or Product(sku=sku)
        row.name, row.base_unit, row.pack_size, row.active = name, unit, pack, active
        db.session.add(row)
        db.session.flush()
        policies = db.session.execute(db.select(StoreProduct).where(StoreProduct.product_id == row.id)
            .order_by(StoreProduct.store_id).with_for_update()).scalars().all()
        for policy in policies:
            params = dict(db.session.get(PolicyVersion, policy.policy_version_id).parameters)
            if params['pack_size'] != pack:
                publish_policy(policy, {**params, 'pack_size': pack})
            affected.add(policy.store_id)
    elif kind == 'stores':
        code = text(data.get('code'), '門市代碼', 32)
        name = text(data.get('name'), '門市名稱', 120)
        if data.get('cutoff', '22:00') != '22:00':
            invalid('本版日常訂貨截止固定為22:00，須與配送輪次一致')
        if row and row.code != code:
            invalid('既有門市代碼不可修改')
        row = row or Store(code=code, cutoff=time(22), timezone='Asia/Taipei')
        row.name, row.active = name, active
        db.session.add(row)
        db.session.flush()
        affected.add(row.id)
    elif kind == 'users':
        username = text(data.get('username'), '帳號', 80)
        role = data.get('role')
        if role not in ('manager', 'operator', 'admin'):
            invalid('角色須為店長、接單人員或管理者')
        ids = data.get('store_ids', [])
        if not isinstance(ids, list) or any(type(i) is not int for i in ids):
            invalid('請選擇門市')
        allowed = [s for s in stores if s.id in ids]
        if len(set(ids)) != len(allowed) or (role == 'manager' and not allowed) or (role != 'manager' and ids):
            invalid('店長須至少指派一間門市；其他角色不指派門市')
        if row and row.username != username:
            invalid('既有帳號不可修改')
        if row and row.id == actor.id and (role != 'admin' or not active):
            invalid('不能停用自己或移除自己的管理權限')
        row = row or User(username=username)
        password = data.get('password')
        if password:
            if not isinstance(password, str) or not 8 <= len(password) <= 128:
                invalid('密碼須為8至128字元')
            row.set_password(password)
        elif not row.id:
            invalid('新增帳號須設定密碼')
        affected.update(s.id for s in row.stores)
        affected.update(ids)
        row.role, row.active, row.stores = role, active, allowed
        db.session.add(row)
    else:
        store_id = integer(data.get('store_id'), '門市', 1)
        product_id = integer(data.get('product_id'), '商品', 1)
        product = db.session.get(Product, product_id)
        if not product or store_id not in {s.id for s in stores}:
            invalid('門市或商品不存在')
        if row and (row.store_id, row.product_id) != (store_id, product_id):
            invalid('政策的門市與商品不可修改')
        params = dict(db.session.get(PolicyVersion, row.policy_version_id).parameters) if row else dict(POLICY)
        for field in POLICY_FIELDS:
            minimum = 0 if field in ('safety_stock', 'capacity') else 1
            maximum = 365 if field in ('lead_days', 'manual_valid_days') else 8760 if field == 'variance_hours' else 1000000
            params[field] = integer(data.get(field, params.get(field)), field, minimum, maximum)
        params['pack_size'] = product.pack_size
        row = row or StoreProduct(store_id=store_id, product_id=product_id)
        if not row.id:
            # Empty ledger is explicitly unverified, never a checked opening count.
            baseline = round_window(business_now())[0]
            db.session.add(Inventory(store_id=store_id, product_id=product_id,
                physical_qty=0, unsellable_qty=0, book_physical_qty=0, book_unsellable_qty=0,
                counted_at=utc_naive(baseline - timedelta(seconds=1)), updated_at=utc_naive(business_now()),
                reconciliation_required=True))
        publish_policy(row, params)
        row.active = active
        db.session.add(row)
        affected.add(store_id)
    for store in stores:
        if store.id in affected:
            bump_store(store)
    try:
        db.session.flush()
    except IntegrityError as error:
        raise DomainError('DUPLICATE_RECORD', '代碼、帳號或門市商品已存在', 409) from error
    new = state(kind, row)
    if kind == 'users':
        new['password_changed'] = bool(data.get('password'))
    record_event(actor.id, row.store_id if kind == 'policies' else None,
        f'management.{kind}.save', f'{kind}:{row.id}', old, new)
    return serialize(kind, row)


def prepare_cycles(actor, store_id):
    from app.services.version import lock_store
    if not actor or actor.role != 'admin' or not actor.active:
        raise DomainError('FORBIDDEN', '僅管理者可準備輪次', 403)
    store = lock_store(integer(store_id, '門市', 1))
    baseline, cutoff = round_window(business_now())
    lead_days = set(db.session.execute(db.select(StoreProduct.lead_days).where(
        StoreProduct.store_id == store.id, StoreProduct.active.is_(True))).scalars()) | {1,2,3}
    existing = {r.arrival_at for r in db.session.execute(db.select(DeliveryCycle).where(
        DeliveryCycle.store_id == store.id, DeliveryCycle.baseline_at == utc_naive(baseline))).scalars()}
    added = 0
    for days in sorted(lead_days):
        arrival = utc_naive(baseline + timedelta(days=days))
        if arrival not in existing:
            db.session.add(DeliveryCycle(store_id=store.id, baseline_at=utc_naive(baseline),
                cutoff_at=utc_naive(cutoff), arrival_at=arrival))
            added += 1
    if added:
        bump_store(store)
        record_event(actor.id, store.id, 'management.cycles.prepare', f'store:{store.id}', None,
            {'baseline':baseline.isoformat(), 'added':added})
    return {'added':added, 'baseline_at':baseline, 'store_version':store.calculation_version}
