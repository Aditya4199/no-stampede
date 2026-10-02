import time
from prometheus_client import Counter, Histogram, Gauge
from prometheus_client.registry import Collector
from prometheus_client.core import GaugeMetricFamily
from app.store.db import get_pool

# HTTP Metrics
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['route', 'code']
)

http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['route']
)

# Domain Metrics
reservations_confirmed_total = Counter(
    'reservations_confirmed_total',
    'Total reservations confirmed',
    ['show_id']
)

reservations_held_total = Counter(
    'reservations_held_total',
    'Total reservations held',
    ['show_id']
)
reservations_declined_total = Counter(
    'reservations_declined_total',
    'Total reservations declined',
    ['reason']
)

# Pool Metrics
db_pool_acquired_conns = Gauge('db_pool_acquired_conns', 'DB pool acquired connections')
db_pool_idle_conns = Gauge('db_pool_idle_conns', 'DB pool idle connections')
db_pool_wait_duration_seconds = Histogram(
    'db_pool_wait_duration_seconds', 
    'Time spent waiting for a DB connection from the pool'
)



seats_available = Gauge('seats_available', 'Seats available', ['show_id'])
seats_held = Gauge('seats_held', 'Seats held', ['show_id'])
seats_confirmed = Gauge('seats_confirmed', 'Seats confirmed', ['show_id'])
