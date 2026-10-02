import os
from unittest import mock

from app.config import Config


def test_config_load_defaults():
    with mock.patch.dict(os.environ, {"ENV": "dev"}, clear=True):
        cfg = Config.load()
        assert cfg.port == 8080
        assert cfg.db_max_conns == 20
        assert "5432" in cfg.database_url
        assert cfg.jwt_secret == "supersecret-dev-jwt-key-must-be-at-least-32-bytes"


def test_config_load_custom():
    custom_env = {
        "PORT": "9090",
        "DATABASE_URL": "postgresql://custom:custom@localhost:5432/custom_db",
        "JWT_SECRET": "my-production-secret",
        "DB_MAX_CONNS": "50",
    }
    with mock.patch.dict(os.environ, custom_env, clear=True):
        cfg = Config.load()
        assert cfg.port == 9090
        assert cfg.database_url == "postgresql://custom:custom@localhost:5432/custom_db"
        assert cfg.jwt_secret == "my-production-secret"
        assert cfg.db_max_conns == 50


def test_config_invalid_port_fallback():
    with mock.patch.dict(os.environ, {"ENV": "dev", "PORT": "invalid", "DB_MAX_CONNS": "-5"}, clear=True):
        cfg = Config.load()
        assert cfg.port == 8080
        assert cfg.db_max_conns == 20
