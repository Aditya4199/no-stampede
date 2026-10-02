import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    port: int
    database_url: str
    jwt_secret: str
    db_max_conns: int
    db_pool_acquire_timeout: float
    max_inflight_reserves: int
    admin_key: str
    env: str

    @classmethod
    def load(cls) -> "Config":
        port_raw = os.getenv("PORT", "8080")
        try:
            port = int(port_raw)
        except ValueError:
            port = 8080

        database_url = os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:password@localhost:5432/no_stampede",
        )
        
        env = os.getenv("ENV", "prod")
        jwt_secret = os.getenv("JWT_SECRET")
        if not jwt_secret:
            if env != "dev":
                raise RuntimeError("JWT_SECRET environment variable is required outside dev environment")
            jwt_secret = "supersecret-dev-jwt-key-must-be-at-least-32-bytes"

        db_max_conns_raw = os.getenv("DB_MAX_CONNS", "20")
        try:
            db_max_conns = int(db_max_conns_raw)
            if db_max_conns <= 0:
                db_max_conns = 20
        except ValueError:
            db_max_conns = 20
            
        db_pool_acquire_timeout_raw = os.getenv("DB_POOL_ACQUIRE_TIMEOUT", "5.0")
        try:
            db_pool_acquire_timeout = float(db_pool_acquire_timeout_raw)
        except ValueError:
            db_pool_acquire_timeout = 5.0
            
        max_inflight_raw = os.getenv("MAX_INFLIGHT_RESERVES")
        if max_inflight_raw:
            try:
                max_inflight_reserves = int(max_inflight_raw)
            except ValueError:
                max_inflight_reserves = 2 * db_max_conns
        else:
            max_inflight_reserves = 2 * db_max_conns

        return cls(
            port=port,
            database_url=database_url,
            jwt_secret=jwt_secret,
            db_max_conns=db_max_conns,
            db_pool_acquire_timeout=db_pool_acquire_timeout,
            max_inflight_reserves=max_inflight_reserves,
            admin_key=os.getenv("ADMIN_KEY", ""),
            env=env,
        )
