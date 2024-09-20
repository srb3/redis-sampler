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

# Prometheus Gauge
rate_limiting_total_requests = Gauge(
    "rate_limiting_total_requests",
    "Total requests for rate limiting with pattern",
    ["pattern"],
)

shutdown_flag = False


def signal_handler(sig, frame):
    global shutdown_flag
    logging.info("Shutdown signal received. Exiting gracefully...")
    shutdown_flag = True


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


def count_rl_counters(r, scan_pattern):
    total_count = 0
    oldest_windows = {}
    key_regex = re.compile(r"(\d+):\d+:(.*)")

    for key in r.scan_iter(match=scan_pattern):
        match = key_regex.match(key)
        if match:
            timestamp, uuid = match.groups()
            timestamp = int(timestamp)
            if uuid not in oldest_windows or timestamp < oldest_windows[uuid][0]:
                oldest_windows[uuid] = (timestamp, key)

    for _, key in oldest_windows.values():
        hash_entries = r.hgetall(key)
        for value in hash_entries.values():
            total_count += int(value)

    return total_count


def collect_metrics(redis_client, scan_pattern):
    try:
        total_count = count_rl_counters(redis_client, scan_pattern)
        rate_limiting_total_requests.labels(pattern=scan_pattern).set(total_count)
        logging.info(f"Updated rate limiting total requests metric: {total_count}")
    except Exception as e:
        logging.error(f"Error collecting metrics: {e}")


def main(r, port, scan_pattern):
    # Start up the server to expose the metrics.
    start_http_server(port)
    logging.info(f"Prometheus metrics server started on port {port}")
    while not shutdown_flag:
        collect_metrics(r, scan_pattern)
        time.sleep(5)
    logging.info("Metrics collection stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Prometheus exporter for Redis rate limiting counters"
    )
    parser.add_argument(
        "--key-pattern",
        type=str,
        required=True,
        help="Pattern to match keys in Redis.",
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
        main(redis_client, args.metric_port, args.key_pattern)
    except Exception as e:
        logging.error(f"Exporter failed to start: {e}")
