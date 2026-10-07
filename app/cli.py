import click
from flask import current_app
from app.extensions import db
from app.config import validate_database


def register_cli(app):
    @app.cli.command('seed-module')
    @click.argument('module', type=click.Choice(['B', 'C', 'D']))
    def seed_module(module):
        if current_app.config['APP_ENV'] != 'demo' or current_app.config['MODULE_DEV'] != module:
            raise click.ClickException('請明確啟用對應 MODULE_DEV，僅限本機 demo')
        validate_database(str(db.engine.url), 'demo')
        from app.services.version import transaction
        from app.testing.seed import seed_module_data
        with transaction():
            seed_module_data(module)
        click.echo(f'{module} 模組開發資料已備妥；測試工廠／替身不是正式功能。')
    @app.cli.command('seed-demo')
    def seed():
        if current_app.config['APP_ENV'] != 'demo':
            raise click.ClickException('僅允許本機 demo 環境')
        validate_database(str(db.engine.url), 'demo')
        from app.seed import seed_demo
        from app.services.version import transaction
        with transaction():
            seed_demo()
        click.echo('示範資料已建立：DEMO1／DEMO2，10 商品；密碼取自本機 DEMO_PASSWORD。')

    @app.cli.command('reset-demo')
    @click.option('--username', prompt='管理者帳號')
    @click.option('--password', prompt='管理者密碼', hide_input=True)
    @click.option('--confirm', prompt='輸入 RESET LOCAL DEMO')
    def reset(username, password, confirm):
        if current_app.config['APP_ENV'] != 'demo' or confirm != 'RESET LOCAL DEMO':
            raise click.ClickException('重設僅限本機 demo 與指定確認字串')
        validate_database(str(db.engine.url), 'demo')
        from app.models import User
        user = db.session.execute(db.select(User).where(User.username == username)).scalar_one_or_none()
        if not user or not user.active or user.role != 'admin' or not user.check_password(password):
            raise click.ClickException('需要有效管理者身份')
        # Delete rows in FK reverse order; preserve schema and alembic_version.
        from app.services.version import transaction
        with transaction():
            # Schema includes circular historical references. Disable checks only on
            # this validated local demo connection, restore before returning it.
            connection = db.session.connection()
            connection.exec_driver_sql('SET FOREIGN_KEY_CHECKS=0')
            try:
                for table in reversed(db.metadata.sorted_tables):
                    db.session.execute(table.delete())
                from app.seed import seed_demo
                seed_demo()
            finally:
                connection.exec_driver_sql('SET FOREIGN_KEY_CHECKS=1')
        click.echo('僅此本機 demo 資料已重設。')
