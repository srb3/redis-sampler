import time
import re
import argparse
import logging
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


def count_rl_counters(r):
    oldest_windows = {}
    key_regex = re.compile(r"(\d+):(\d+):(.*)")

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
    window_counts = {}
    for identifier, (_, key) in oldest_windows.items():
        window_size, uuid = identifier.split("-", 1)
        hash_entries = r.hgetall(key)
        window_total = sum(int(value) for value in hash_entries.values())

        window_counts[identifier] = window_total
        total_count += window_total

    return total_count, window_counts


def collect_metrics(redis_client, instance):
    try:
        total_count, window_counts = count_rl_counters(redis_client)

        # Update total requests metric
        rate_limiting_total_requests.labels(instance=instance).set(total_count)
        logging.info(
            f"Updated rate limiting total requests metric for {instance}: {total_count}"
        )

        # Update individual window metrics
        for identifier, count in window_counts.items():
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


def main(r, port, host):
    # Start up the server to expose the metrics.
    start_http_server(port)
    logging.info(f"Prometheus metrics server started on port {port}")
    while not shutdown_flag:
        collect_metrics(r, host)
        time.sleep(5)
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
        main(redis_client, args.metric_port, args.host)
    except Exception as e:
        logging.error(f"Exporter failed to start: {e}")
