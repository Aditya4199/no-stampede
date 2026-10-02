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

class DBSeatCollector(Collector):
    def collect(self):
        # We need to run async query in sync context because prometheus_client is synchronous
        # But this is tricky in async frameworks. For simplicity, we can fetch metrics in a background loop
        # or use async-aware prometheus clients.
        # Since we use prometheus_client which is sync, we can just yield dummy values if we can't block.
        # Alternatively, since we are in FastAPI, we can update the gauges via a background task 
        # or just at scrape time using a hack.
        # Given the constraint, we will implement a background updater instead of a strict Collector
        # or we can use `asyncio.run_coroutine_threadsafe` if we have the loop.
        pass

# We will use simple gauges updated periodically via background task or via the /metrics endpoint directly
seats_available = Gauge('seats_available', 'Seats available', ['show_id'])
seats_held = Gauge('seats_held', 'Seats held', ['show_id'])
seats_confirmed = Gauge('seats_confirmed', 'Seats confirmed', ['show_id'])
