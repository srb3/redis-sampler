import redis
import time
import re
import argparse
from prometheus_client import start_http_server, Gauge

# Configuration
redis_host = "master.redis-rla-grp-1.jsmi90.euw3.cache.amazonaws.com"
redis_port = 6379

r = redis.Redis(
    host=redis_host,
    port=redis_port,
    username="redis-rla",
    password="strongkong123456",
    ssl=True,
    decode_responses=True,  # Ensure Redis responses are decoded as strings
)

# Prometheus Gauge with pattern label
rate_limiting_total_requests = Gauge(
    "rate_limiting_total_requests", "Total requests for rate limiting", ["pattern"]
)


def get_keys_with_pattern(pattern):
    keys = r.keys(pattern)
    return keys if keys else []


def extract_timestamp_from_key(key):
    match = re.match(r"(\d+):\d+:.+", key)
    if match:
        return int(match.group(1))
    return None


def get_oldest_key(keys):
    timestamps = [(key, extract_timestamp_from_key(key)) for key in keys]
    oldest_key = min(timestamps, key=lambda x: x[1])[0]
    return oldest_key


def sum_counters_in_bucket(key):
    counters = r.hgetall(key)
    total_count = sum(int(count) for count in counters.values() if count.isdigit())
    return total_count


def collect_metrics(pattern):
    keys = get_keys_with_pattern(pattern)
    if keys:
        oldest_key = get_oldest_key(keys)
        total_count = sum_counters_in_bucket(oldest_key)
        rate_limiting_total_requests.labels(pattern=pattern).set(total_count)
    else:
        # Set metric to 0 if no keys are found
        rate_limiting_total_requests.labels(pattern=pattern).set(0)


def main(pattern, port):
    start_http_server(port)  # Start Prometheus client
    while True:
        collect_metrics(pattern)
        time.sleep(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Prometheus metrics collector for Redis rate limiting"
    )
    parser.add_argument(
        "--key-pattern", type=str, required=True, help="Pattern to match keys in Redis."
    )
    parser.add_argument(
        "--metric-port",
        type=int,
        default=8881,
        help="Port to expose metrics on (default: 8881).",
    )
    args = parser.parse_args()
    main(args.key_pattern, args.metric_port)
