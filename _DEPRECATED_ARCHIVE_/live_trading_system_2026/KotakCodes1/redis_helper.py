import redis
import json
from datetime import datetime

class RedisHelper:
    """A helper class to abstract Redis operations for the trading application."""

    def __init__(self, host='localhost', port=6379):
        """Initializes the Redis connection."""
        try:
            self.r = redis.Redis(host=host, port=port, decode_responses=True)
            self.r.ping()
            print("RedisHelper: Successfully connected to Redis.")
        except redis.exceptions.ConnectionError as e:
            print(f"RedisHelper: Could not connect to Redis at {host}:{port}. Error: {e}")
            self.r = None

    def read_latest_ltp(self, stockname: str):
        """
        Reads the latest LTP for a stock, returning only the price as a number.

        Args:
            stockname: The name of the stock (e.g., "EICHERMOT").

        Returns:
            The latest LTP as a float, or None if no data is found.
        """
        if not self.r:
            print("RedisHelper: Cannot execute command, no connection to Redis.")
            return None

        primary_keys = [f"{stockname}_ICICI", f"{stockname}_KOTAK"]
        secondary_keys = [f"{stockname}_ICICI_minute", f"{stockname}_KOTAK_minute"]

        def get_latest_from_keys(keys_to_check: list):
            """Helper function to find the latest LTP from a list of keys."""
            values = self.r.mget(keys_to_check)
            valid_entries = []
            for value in values:
                if value is None:
                    continue
                try:
                    data = json.loads(value)
                    # Add timestamp object for comparison, but don't store it
                    entry = {
                        'ltp': data.get('ltp'),
                        'timestamp_obj': datetime.strptime(data['timestamp'], "%Y-%m-%d %H:%M:%S.%f")
                    }
                    valid_entries.append(entry)
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue  # Ignore malformed data

            if not valid_entries:
                return None

            # Find the entry with the latest timestamp and return its LTP
            latest_entry = max(valid_entries, key=lambda x: x['timestamp_obj'])
            return latest_entry.get('ltp')

        try:
            # 1. Try primary keys
            latest_ltp = get_latest_from_keys(primary_keys)
            if latest_ltp is not None:
                return float(latest_ltp) if latest_ltp is not None else None

            # 2. Fall back to secondary keys
            latest_ltp = get_latest_from_keys(secondary_keys)
            if latest_ltp is not None:
                return float(latest_ltp) if latest_ltp is not None else None
            
            # 3. If nothing is found, return None
            return None

        except redis.exceptions.RedisError as e:
            print(f"RedisHelper: A Redis error occurred: {e}")
            return None


