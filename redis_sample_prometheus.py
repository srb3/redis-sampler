import time
import re
import argparse
import logging
from typing import Dict, Tuple
import redis
from redis.cluster import RedisCluster, ClusterNode
from prometheus_client import start_http_server, Gauge

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

# Prometheus Gauges
rate_limiting_total_requests = Gauge(
    "rate_limiting_total_requests", "Total requests for rate limiting", ["instance"]
)

rate_limiting_window_requests = Gauge(
    "rate_limiting_window_requests",
    "Requests for specific rate limiting window",
    ["instance", "window_size", "uuid", "identifier"],
)

shutdown_flag = False

# Global variable to store the previous window counts and their last seen timestamps
previous_window_counts: Dict[str, Tuple[int, float]] = {}


def create_redis_client(host, port, username, password, ssl, is_cluster):
    connection_kwargs = {
        "host": host,
        "port": port,
        "password": password,
        "ssl": ssl,
        "decode_responses": True,
    }

    if username:
        connection_kwargs["username"] = username

    try:
        if is_cluster:
            nodes = [ClusterNode(host, port)]
            client = RedisCluster(
                startup_nodes=nodes,
                **connection_kwargs,
                skip_full_coverage_check=True,
            )
            logging.info(f"Connected to Redis Cluster at {host}:{port}")
        else:
            client = redis.Redis(**connection_kwargs)
            logging.info(f"Connected to Redis at {host}:{port}")

        # Test connection
        client.ping()
        return client
    except Exception as e:
        logging.error(
            f"Failed to connect to Redis{'Cluster' if is_cluster else ''}: {e}"
        )
        raise


def count_rl_counters(r, keep_zero):
    global previous_window_counts
    current_window_counts = {}
    oldest_windows = {}
    key_regex = re.compile(r"(\d+):(\d+):(.*)")
    current_time = time.time()

    # First pass: find the oldest window for each window_size-uuid combination
    for key in r.scan_iter(match="*:*:*"):  # Match any key with two colons
        match = key_regex.match(key)
        if match:
            timestamp, window_size, uuid = match.groups()
            timestamp = int(timestamp)
            identifier = f"{window_size}-{uuid}"

            if (
                identifier not in oldest_windows
                or timestamp < oldest_windows[identifier][0]
            ):
                oldest_windows[identifier] = (timestamp, key)

    # Second pass: count the values for the oldest windows
    total_count = 0
    for identifier, (_, key) in oldest_windows.items():
        hash_entries = r.hgetall(key)
        window_total = sum(int(value) for value in hash_entries.values())

        current_window_counts[identifier] = (window_total, current_time)
        total_count += window_total

    # Check for expired counters and set them to zero
    expired_counters = []
    for identifier, (count, last_seen) in previous_window_counts.items():
        if identifier not in current_window_counts:
            if (
                current_time - last_seen <= keep_zero
            ):  # Keep zero value for 30 seconds (default)
                current_window_counts[identifier] = (0, last_seen)
            else:
                expired_counters.append(identifier)

    # Remove expired counters
    for identifier in expired_counters:
        del previous_window_counts[identifier]

    # Update the previous_window_counts for the next iteration
    previous_window_counts = current_window_counts.copy()

    return total_count, current_window_counts


def collect_metrics(redis_client, instance, keep_zero):
    try:
        total_count, window_counts = count_rl_counters(redis_client, keep_zero)

        # Update total requests metric
        rate_limiting_total_requests.labels(instance=instance).set(total_count)
        logging.info(
            f"Updated rate limiting total requests metric for {instance}: {total_count}"
        )

        # Update individual window metrics
        for identifier, (count, _) in window_counts.items():
            window_size, uuid = identifier.split("-", 1)
            rate_limiting_window_requests.labels(
                instance=instance,
                window_size=window_size,
                uuid=uuid,
                identifier=identifier,
            ).set(count)
            logging.info(
                f"Updated rate limiting window requests metric for {instance}: {identifier} = {count}"
            )

    except Exception as e:
        logging.error(f"Error collecting metrics: {e}")


def main(r, port, host, keep_zero, sleep_time=5):
    # Start up the server to expose the metrics.
    start_http_server(port)
    logging.info(f"Prometheus metrics server started on port {port}")
    while not shutdown_flag:
        collect_metrics(r, host, keep_zero)
        time.sleep(sleep_time)
    logging.info("Metrics collection stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Prometheus exporter for Redis rate limiting counters"
    )
    parser.add_argument(
        "--metric-port",
        type=int,
        default=8000,
        help="Port to expose Prometheus metrics on",
    )
    parser.add_argument(
        "--host",
        type=str,
        required=True,
        help="The Redis host",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=6379,
        help="Redis port",
    )
    parser.add_argument(
        "--username",
        type=str,
        default="default",
        help="Redis username",
    )
    parser.add_argument(
        "--password",
        type=str,
        required=True,
        help="Redis password",
    )
    parser.add_argument(
        "--ssl",
        action="store_true",
        help="Use SSL for Redis connection",
    )
    parser.add_argument(
        "--cluster",
        action="store_true",
        help="Connect to a Redis Cluster",
    )
    parser.add_argument(
        "--keep-zero",
        type=int,
        default=30,
        help="Keep zero value for expired counters for this many seconds",
    )
    parser.add_argument(
        "--sleep-time",
        type=int,
        default=5,
        help="Time to sleep between metric collections",
    )
    args = parser.parse_args()

    try:
        redis_client = create_redis_client(
            host=args.host,
            port=args.port,
            username=args.username,
            password=args.password,
            ssl=args.ssl,
            is_cluster=args.cluster,
        )
        main(redis_client, args.metric_port, args.host, args.keep_zero, args.sleep_time)
    except Exception as e:
        logging.error(f"Exporter failed to start: {e}")
