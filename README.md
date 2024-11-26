# Redis Sampler - Prometheus Exporter for Kong Rate Limiting Advanced Counters

## Overview

Redis Sampler is a lightweight Prometheus exporter that collects and exposes Kong Rate Limiting Advanced (RLA) plugin counters stored in Redis. It is designed to work with both standalone Redis and Redis Cluster setups, supporting SSL connections and authentication. The exported metrics are used to monitor rate-limiting traffic and can be visualized in Grafana or similar tools.
Features

* Collects total and window-specific request counts from Redis.
* Supports Redis Cluster and standalone Redis.
* SSL and username/password authentication.
* Configurable metric exposure port and collection interval.
* Handles expired counters gracefully by optionally keeping zero-value metrics for a configurable period.
* Prometheus metrics compatible with visualization in Grafana.

## Installation

### Docker

You can run Redis Sampler using the provided Docker image:

```bash
docker run -d --name redis-rla-sample \
  --network kong --hostname redis-rla-sample \
  -p 8882:8882 srbrown/redis-rla-sampler:v0.6.0 \
  --metric-port 8882 --cluster --ssl --sleep-time 1 \
  --username ${redis_user} --password ${redis_password} --host ${elasticache_redis_endpoint}
```

Replace the placeholders:

* ${redis_user}: Your Redis username.
* ${redis_password}: Your Redis password.
* ${elasticache_redis_endpoint}: Your Redis endpoint.

## Prometheus Metrics

Redis Sampler exposes the following Prometheus metrics:

```plaintext
    rate_limiting_total_requests
        Description: Total requests for rate limiting.
        Labels: instance

    rate_limiting_window_requests
        Description: Requests for specific rate-limiting windows.
        Labels: instance, window_size, uuid, identifier
```

## Grafana Usage

### Example Visualization

Create a Grafana time series graph to monitor per-second request rates for a specific rate-limiting namespace. For instance:

```plaintext
    Query: sum(rate_limiting_window_requests{job="redis-counters", uuid=~"rla-.*"} / 5)

    Replace rla-.* with your specific namespace pattern.
    Adjust the division factor (/ 5) based on the window size (e.g., for a 5-second window, divide by 5).
```

## Configuration

### Command-Line Arguments

| Argument         | Default | Description                                                    |
|-------------------|---------|----------------------------------------------------------------|
| `--metric-port`   | `8000`  | Port to expose Prometheus metrics.                            |
| `--host`          | None    | Redis host (required).                                        |
| `--port`          | `6379`  | Redis port.                                                  |
| `--username`      | `default` | Redis username.                                              |
| `--password`      | None    | Redis password (required).                                    |
| `--ssl`           | `False` | Enable SSL for Redis connection.                             |
| `--cluster`       | `False` | Enable Redis Cluster mode.                                   |
| `--keep-zero`     | `30`    | Time in seconds to retain zero-value metrics for expired counters. |
| `--sleep-time`    | `5`     | Time in seconds between metric collections.                  |

## Local Development

To run the exporter locally:

* Install Python dependencies:

```bash
pip install -r requirements.txt
```

Run the script:

```bash
    python redis_sampler.py --host <REDIS_HOST> --password <REDIS_PASSWORD> [other args...]
```

## Example Output

Prometheus metrics will be available at http://<host>:<metric-port>/metrics. Example metrics:

```plaintext
# HELP rate_limiting_total_requests Total requests for rate limiting
# TYPE rate_limiting_total_requests gauge
rate_limiting_total_requests{instance="redis_instance"} 12000

# HELP rate_limiting_window_requests Requests for specific rate limiting window
# TYPE rate_limiting_window_requests gauge
rate_limiting_window_requests{instance="redis_instance",window_size="5",uuid="rla-namespace",identifier="5-rla-namespace"} 200
```

## Logging

The application provides detailed logs for connection status, metric updates, and errors. Logs are output to the console by default.
Troubleshooting

* Cannot connect to Redis: Verify the host, port, SSL, username, and password values.
* Metrics not exposed: Ensure the --metric-port is open and not blocked by firewalls.
* Incorrect metrics: Check your Grafana expressions and window size configurations.
