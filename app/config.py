import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    port: int
    database_url: str
    jwt_secret: str
    db_max_conns: int

    @classmethod
    def load(cls) -> "Config":
        port_raw = os.getenv("PORT", "8080")
        try:
            port = int(port_raw)
        except ValueError:
            port = 8080

        database_url = os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/bms",
        )
        jwt_secret = os.getenv("JWT_SECRET", "super-secret-jwt-key-for-dev")

        db_max_conns_raw = os.getenv("DB_MAX_CONNS", "20")
        try:
            db_max_conns = int(db_max_conns_raw)
            if db_max_conns <= 0:
                db_max_conns = 20
        except ValueError:
            db_max_conns = 20

        return cls(
            port=port,
            database_url=database_url,
            jwt_secret=jwt_secret,
            db_max_conns=db_max_conns,
        )
