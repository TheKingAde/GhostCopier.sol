import logging
from quart import Quart

from .config import Config
from . import db as db_module
from . import monitor
from .routes import bp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app():
    app = Quart(__name__, static_folder="../static", template_folder="../templates")
    app.config.from_object(Config)
    app.register_blueprint(bp)

    @app.before_serving
    async def _startup():
        await db_module.init_db()
        await monitor.bootstrap_running_sessions()

    @app.after_serving
    async def _shutdown():
        for session_id in list(monitor._tasks.keys()):
            await monitor.stop_session(session_id)

    return app
