"""
Flask API Entry Point
Serves violation data from the shared SQLite database.

Usage:
    python main.py
"""

import sys
from pathlib import Path
from flask import Flask
from flasgger import Swagger

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from app.routes import api_bp, init_routes
from app.db.database import ViolationDatabase
from config.config import API_HOST, API_PORT, API_DEBUG


def create_app(db_path=None):
    """Create and configure the Flask application

    Args:
        db_path: Optional path to SQLite database. If None, uses config default.
    """
    app = Flask(__name__)

    # ── Swagger / OpenAPI interactive docs (served at /docs/) ──────────
    # Endpoints are documented via YAML docstrings in app/routes.py.
    app.config['SWAGGER'] = {
        'title': 'Traffic Violation Detection API',
        'description': (
            'REST API for the Traffic Violation Detection System. '
            'Serves violation records, statistics, health status, and the '
            'live detection feed produced by the worker.'
        ),
        'version': '1.0.0',
        'uiversion': 3,
        'specs_route': '/docs/'
    }
    Swagger(app)

    # Initialize database
    db = ViolationDatabase(db_path=db_path)

    # Initialize routes with database reference
    init_routes(db)

    # Register blueprint
    app.register_blueprint(api_bp, url_prefix='')

    return app


if __name__ == '__main__':
    app = create_app()
    print(f"🚀 API server starting on {API_HOST}:{API_PORT}")
    app.run(host=API_HOST, port=API_PORT, debug=API_DEBUG)
