import redis
import time
import re
import argparse
import logging
import os
import signal
import sys
from prometheus_client import start_http_server, Gauge

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)

# Prometheus Gauge with pattern label
rate_limiting_total_requests = Gauge(
    "rate_limiting_total_requests", "Total requests for rate limiting", ["pattern"]
)

# Flag to handle graceful shutdown
shutdown_flag = False


def signal_handler(sig, frame):
    global shutdown_flag
    logging.info("Shutdown signal received. Exiting gracefully...")
    shutdown_flag = True


def create_redis_client(host, port, username, password, ssl, is_cluster):
    if is_cluster:
        from redis.cluster import RedisCluster, ClusterNode

        # Define startup nodes
        nodes = [ClusterNode(host, port)]
        try:
            rc = RedisCluster(
                startup_nodes=nodes,
                username=username,
                password=password,
                ssl=ssl,
                decode_responses=True,
                skip_full_coverage_check=True,  # Optional: speeds up startup
            )
            logging.info(f"Connected to Redis Cluster at {host}:{port}")
            return rc
        except Exception as e:
            logging.error(f"Failed to connect to Redis Cluster: {e}")
            raise
    else:
        try:
            r = redis.Redis(
                host=host,
                port=port,
                username=username,
                password=password,
                ssl=ssl,
                decode_responses=True,
            )
            # Test connection
            r.ping()
            logging.info(f"Connected to single-instance Redis at {host}:{port}")
            return r
        except Exception as e:
            logging.error(f"Failed to connect to Redis: {e}")
            raise


def get_keys_with_pattern(r, pattern, is_cluster):
    keys = []
    try:
        for key in r.scan_iter(match=pattern, count=1000):
            keys.append(key)
    except Exception as e:
        logging.error(f"Error during scanning keys: {e}")
    logging.info(f"Found {len(keys)} keys matching pattern '{pattern}'")
    return keys


def extract_timestamp_from_key(key):
    match = re.match(r"(\d+):\d+:.+", key)
    if match:
        return int(match.group(1))
    return None


def get_oldest_key(keys):
    timestamps = [(key, extract_timestamp_from_key(key)) for key in keys]
    # Filter out keys where timestamp extraction failed
    timestamps = [(k, ts) for k, ts in timestamps if ts is not None]
    if not timestamps:
        return None
    oldest_key = min(timestamps, key=lambda x: x[1])[0]
    return oldest_key


def sum_counters_in_bucket(r, key):
    try:
        counters = r.hgetall(key)
        total_count = sum(int(count) for count in counters.values() if count.isdigit())
        return total_count
    except Exception as e:
        logging.error(f"Error summing counters for key '{key}': {e}")
        return 0


def collect_metrics(r, pattern, is_cluster):
    keys = get_keys_with_pattern(r, pattern, is_cluster)
    if keys:
        oldest_key = get_oldest_key(keys)
        if oldest_key:
            total_count = sum_counters_in_bucket(r, oldest_key)
            rate_limiting_total_requests.labels(pattern=pattern).set(total_count)
            logging.info(f"Set metric for pattern '{pattern}' to {total_count}")
        else:
            # No valid keys with extractable timestamps
            rate_limiting_total_requests.labels(pattern=pattern).set(0)
            logging.info(
                f"No valid keys found for pattern '{pattern}'. Metric set to 0."
            )
    else:
        # Set metric to 0 if no keys are found
        rate_limiting_total_requests.labels(pattern=pattern).set(0)
        logging.info(f"No keys found for pattern '{pattern}'. Metric set to 0.")


def main(r, pattern, port, is_cluster):
    start_http_server(port)  # Start Prometheus client
    logging.info(f"Prometheus metrics server started on port {port}")
    while not shutdown_flag:
        collect_metrics(r, pattern, is_cluster)
        time.sleep(1)
    logging.info("Metrics collection stopped.")


if __name__ == "__main__":
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    parser = argparse.ArgumentParser(
        description="Prometheus metrics collector for Redis rate limiting"
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
        default=8881,
        help="Port to expose metrics on (default: 8881).",
    )
    parser.add_argument(
        "--host",
        type=str,
        required=True,
        help="Redis server host.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=6379,
        help="Redis server port (default: 6379).",
    )
    parser.add_argument(
        "--username",
        type=str,
        default=None,
        help="Redis username (default: None).",
    )
    parser.add_argument(
        "--password",
        type=str,
        default=os.getenv("REDIS_PASSWORD"),
        required=not bool(os.getenv("REDIS_PASSWORD")),
        help="Redis password.",
    )
    parser.add_argument(
        "--ssl",
        action="store_true",
        help="Use SSL for Redis connection.",
    )
    parser.add_argument(
        "--cluster",
        action="store_true",
        help="Connect to a Redis Cluster.",
    )
    args = parser.parse_args()

    # Validate arguments
    if args.cluster and not args.username:
        logging.warning(
            "Connecting to a cluster without a username. Ensure this is intended."
        )

    # Create Redis client
    try:
        redis_client = create_redis_client(
            host=args.host,
            port=args.port,
            username=args.username,
            password=args.password,
            ssl=args.ssl,
            is_cluster=args.cluster,
        )
    except Exception as e:
        logging.error(f"Exiting due to connection failure: {e}")
        sys.exit(1)

    main(redis_client, args.key_pattern, args.metric_port, args.cluster)
