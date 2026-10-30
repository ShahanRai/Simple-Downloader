"""
Token Bucket Speed Limiter for controlling network throughput.
Equivalent to IDM's CSpeedLimiter class.
"""

import time
import threading


class SpeedLimiter:
    """
    Thread-safe Token Bucket Rate Limiter.
    Limits aggregate bandwidth across all concurrent download threads.
    """

    def __init__(self, max_bytes_per_sec: float = 0.0):
        """
        :param max_bytes_per_sec: Max download speed in bytes/sec. 0 or negative means unlimited.
        """
        self.max_bytes_per_sec = float(max_bytes_per_sec)
        self._tokens = self.max_bytes_per_sec
        self._last_time = time.monotonic()
        self._lock = threading.Lock()

    def set_limit(self, max_bytes_per_sec: float):
        with self._lock:
            self.max_bytes_per_sec = float(max_bytes_per_sec)
            self._tokens = min(self._tokens, self.max_bytes_per_sec)

    def consume(self, num_bytes: int):
        """
        Consumes tokens for transferred bytes.
        Blocks calling thread if tokens are exhausted.
        """
        if self.max_bytes_per_sec <= 0:
            return  # Unlimited

        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_time
                self._last_time = now

                # Replenish tokens based on elapsed time
                self._tokens = min(
                    self.max_bytes_per_sec,
                    self._tokens + elapsed * self.max_bytes_per_sec
                )

                if self._tokens >= num_bytes:
                    self._tokens -= num_bytes
                    return

                # Calculate sleep duration needed
                needed = num_bytes - self._tokens
                sleep_sec = needed / self.max_bytes_per_sec

            # Sleep outside lock to avoid starving other threads
            time.sleep(min(sleep_sec, 0.1))
