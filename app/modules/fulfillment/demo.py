"""Advance only D's independent demo clock past the seeded inventory baseline."""
from datetime import timedelta

import click
from flask import current_app

from app.extensions import db
from app.models import BusinessClock, User, Order, OrderItem
from app.services.clock import aware, set_clock
from app.services.tasks import create_task, policy_setting
from app.services.version import transaction


def register_demo(bp):
    @bp.cli.command('prepare-demo')
    def prepare_demo():
        if current_app.config['APP_ENV'] != 'demo' or current_app.config['MODULE_DEV'] != 'D':
            raise click.ClickException('僅限 APP_ENV=demo、MODULE_DEV=D')
        name = db.engine.url.database or ''
        if not name.startswith('system2_d') or not name.endswith('_demo'):
            raise click.ClickException('僅允許 D 自己的 system2_d*_demo')
        with transaction():
            clock = db.session.get(BusinessClock, 1)
            if clock is None:
                raise click.ClickException('請先執行 seed-demo；未修改資料')
            target = aware(clock.business_anchor) + timedelta(minutes=1)
            if clock.paused and aware(clock.business_anchor).isoformat() == '2026-10-08T13:00:00+00:00':
                admin = db.session.execute(db.select(User).where(
                    User.username == 'admin')).scalar_one()
                set_clock(admin, target, paused=True)
                click.echo('D 示範時間已推進至 2026-10-08 21:01 Asia/Taipei；未重設資料。')
            else:
                click.echo('保留既有示範時間；檢查 D 測試訂單待辦。')
            orders = db.session.execute(db.select(Order).where(
                Order.fixture_only.is_(True))).scalars().all()
            for order in orders:
                items = db.session.execute(db.select(OrderItem).where(
                    OrderItem.order_id == order.id)).scalars().all()
                for item in items:
                    if item.status not in ('SUBMITTED', 'CHANGE_PENDING'):
                        continue
                    minutes = policy_setting(db.session, order.store_id, item.product_id,
                        'supply_response_minutes', 60)
                    create_task(db.session, order.store_id, 'operator', 'order_item',
                        str(item.id), 'respond_order',
                        aware(order.submitted_at) + timedelta(minutes=minutes), item.product_id)
            click.echo('D 測試訂單接單待辦已備妥；既有待辦不覆寫。')
