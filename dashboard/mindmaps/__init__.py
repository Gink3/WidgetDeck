from .routes import mindmaps
from .models import init_database


def init_mindmaps(app):
    init_database(app)
    app.register_blueprint(mindmaps)
