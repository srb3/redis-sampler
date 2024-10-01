import unittest
from unittest.mock import Mock, patch, ANY
from redis_sample_prometheus import count_rl_counters, collect_metrics


class TestPrometheusExporter(unittest.TestCase):

    def setUp(self):
        self.mock_redis = Mock()
        # Clear previous_window_counts before each test
        import redis_sample_prometheus

        redis_sample_prometheus.previous_window_counts = {}

    def test_count_rl_counters_empty(self):
        self.mock_redis.scan_iter.return_value = []
        total_count, window_counts = count_rl_counters(self.mock_redis, 30)
        self.assertEqual(total_count, 0)
        self.assertEqual(window_counts, {})

    def test_count_rl_counters_single_window(self):
        self.mock_redis.scan_iter.return_value = ["1000:60:abc123"]
        self.mock_redis.hgetall.return_value = {"field1": "5", "field2": "10"}
        total_count, window_counts = count_rl_counters(self.mock_redis, 30)
        self.assertEqual(total_count, 15)
        self.assertEqual(window_counts, {"60-abc123": (15, ANY)})

    def test_count_rl_counters_multiple_windows(self):
        self.mock_redis.scan_iter.return_value = [
            "1000:60:abc123",
            "1100:60:abc123",  # Newer timestamp, should be ignored
            "1000:120:def456",
        ]
        self.mock_redis.hgetall.side_effect = [
            {"field1": "5", "field2": "10"},  # For 60:abc123
            {"field1": "15", "field2": "20"},  # For 120:def456
        ]
        total_count, window_counts = count_rl_counters(self.mock_redis, 30)
        self.assertEqual(total_count, 50)
        self.assertEqual(
            window_counts, {"60-abc123": (15, ANY), "120-def456": (35, ANY)}
        )

    @patch("redis_sample_prometheus.rate_limiting_total_requests")
    @patch("redis_sample_prometheus.rate_limiting_window_requests")
    def test_collect_metrics(self, mock_window_requests, mock_total_requests):
        mock_redis = Mock()
        mock_redis.scan_iter.return_value = ["1000:60:abc123", "1000:120:def456"]
        mock_redis.hgetall.side_effect = [
            {"field1": "5", "field2": "10"},
            {"field1": "15", "field2": "20"},
        ]
        collect_metrics(mock_redis, "redis-instance1", 30)
        mock_total_requests.labels.assert_called_once_with(instance="redis-instance1")
        mock_total_requests.labels().set.assert_called_once_with(50)
        self.assertEqual(mock_window_requests.labels.call_count, 2)
        mock_window_requests.labels.assert_any_call(
            instance="redis-instance1",
            window_size="60",
            uuid="abc123",
            identifier="60-abc123",
        )
        mock_window_requests.labels.assert_any_call(
            instance="redis-instance1",
            window_size="120",
            uuid="def456",
            identifier="120-def456",
        )
        mock_window_requests.labels().set.assert_any_call(15)
        mock_window_requests.labels().set.assert_any_call(35)


if __name__ == "__main__":
    unittest.main()
