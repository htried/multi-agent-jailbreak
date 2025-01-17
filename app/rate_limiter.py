from functools import wraps
import time
from .config import MAX_REQUESTS

class RateLimiter:
    def __init__(self, max_requests, time_window):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []

    def __call__(self, func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            now = time.time()
            self.requests = [req for req in self.requests 
                           if now - req < self.time_window]
            
            if len(self.requests) >= self.max_requests:
                sleep_time = self.requests[0] + self.time_window - now
                time.sleep(max(0, sleep_time))
            
            self.requests.append(now)
            return func(*args, **kwargs)
        return wrapped

# Usage decorator
rate_limit = RateLimiter(MAX_REQUESTS, 60)