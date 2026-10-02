

CREATE TABLE shows (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    price_paise BIGINT NOT NULL CHECK (price_paise >= 0),
    per_user_limit INT NOT NULL DEFAULT 4 CHECK (per_user_limit > 0),
    hold_ttl_seconds INT NULL,
    total_seats INT NOT NULL CHECK (total_seats >= 0),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE seats (
    show_id UUID REFERENCES shows(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('available', 'held', 'confirmed')),
    user_id TEXT NULL,
    reservation_id UUID NULL,
    hold_expires_at TIMESTAMPTZ NULL,
    PRIMARY KEY (show_id, label),
    CONSTRAINT seats_consistency_check CHECK (
        (status = 'available' AND user_id IS NULL AND reservation_id IS NULL) OR
        (status IN ('held', 'confirmed') AND user_id IS NOT NULL AND reservation_id IS NOT NULL)
    )
);

CREATE TABLE reservations (
    id UUID PRIMARY KEY,
    show_id UUID REFERENCES shows(id) NOT NULL,
    user_id TEXT NOT NULL,
    seats TEXT[] NOT NULL,
    amount_paise BIGINT NOT NULL CHECK (amount_paise >= 0),
    status TEXT NOT NULL CHECK (status IN ('confirmed', 'cancelled', 'expired')),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE idempotency_keys (
    user_id TEXT NOT NULL,
    key TEXT NOT NULL,
    show_id UUID REFERENCES shows(id) NOT NULL,
    request_hash TEXT NOT NULL,
    response JSONB NULL,
    status_code INT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, key)
);

CREATE TABLE user_show_quota (
    user_id TEXT NOT NULL,
    show_id UUID REFERENCES shows(id) NOT NULL,
    active_count INT NOT NULL DEFAULT 0 CHECK (active_count >= 0),
    PRIMARY KEY (user_id, show_id)
);
