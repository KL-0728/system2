"""Local B demo preparation. No deletion, reset, or credential changes."""
from datetime import datetime, timezone

import click
from flask import current_app
from app.extensions import db
from app.models import BusinessClock, InventoryCount, InventoryMovement, SalesImportBatch, Store, User
from app.services.clock import aware, set_clock
from app.services.version import transaction


def register_demo(bp):
    @bp.cli.command('prepare-demo')
    def prepare_demo():
        if current_app.config['APP_ENV'] != 'demo' or current_app.config['MODULE_DEV'] != 'B':
            raise click.ClickException('僅限 APP_ENV=demo、MODULE_DEV=B')
        name = db.engine.url.database or ''
        if not name.startswith('system2_b') or not name.endswith('_demo'):
            raise click.ClickException('僅允許 B 自己的 system2_b*_demo；不操作其他成員 DB')
        with transaction():
            if db.session.execute(db.select(Store.id).limit(1)).first() is None:
                from app.seed import seed_demo
                seed_demo()
            clock = db.session.get(BusinessClock, 1)
            start = datetime(2026, 10, 8, 13, tzinfo=timezone.utc)
            target = datetime(2026, 10, 9, 13, 20, tzinfo=timezone.utc)
            if clock is None:
                raise click.ClickException('缺少示範時鐘，未修改資料')
            if aware(clock.business_anchor) == start and clock.paused:
                if (db.session.execute(db.select(InventoryMovement.id).limit(1)).first()
                        or db.session.execute(db.select(InventoryCount.id).limit(1)).first()
                        or db.session.execute(db.select(SalesImportBatch.id).where(
                            SalesImportBatch.source_batch_id != 'A03-HISTORY-14D').limit(1)).first()):
                    raise click.ClickException('已有模組操作，保留資料；請自行使用管理時鐘推進，不自動變動')
                admin = db.session.execute(db.select(User).where(User.username == 'admin')).scalar_one()
                set_clock(admin, target, paused=True)
                click.echo('B02 起點已準備：2026-10-09 21:20；最近核對盤點為前一日21:00，帳面20件。')
            else:
                click.echo('保留既有資料與示範時間；未重設、未倒退時鐘。')
        click.echo('帳號 manager1／manager2；密碼沿用本機 DEMO_PASSWORD。畫面 /store/data。')
