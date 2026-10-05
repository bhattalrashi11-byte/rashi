import json
import redis


class RedisCache:

    def __init__(self):

        self.client = redis.Redis(
            host="localhost",
            port=6379,
            db=0,
            decode_responses=True
        )

    # --------------------------------------------------
    # Test Redis connection
    # --------------------------------------------------

    def is_connected(self):

        try:
            self.client.ping()
            return True

        except redis.RedisError:
            return False

    # --------------------------------------------------
    # Store data
    # --------------------------------------------------

    def set(self, key, value, expiration=300):

        self.client.setex(
            key,
            expiration,
            json.dumps(value)
        )

    # --------------------------------------------------
    # Get data
    # --------------------------------------------------

    def get(self, key):

        data = self.client.get(key)

        if data is None:
            return None

        return json.loads(data)

    # --------------------------------------------------
    # Delete cached data
    # --------------------------------------------------

    def delete(self, key):

        self.client.delete(key)


# --------------------------------------------------
# Test Redis
# --------------------------------------------------

if __name__ == "__main__":

    cache = RedisCache()

    if cache.is_connected():

        print("Redis connected successfully.")

        test_data = {
            "subject": "Operating Systems",
            "room": "C-301",
            "time": "10:00-11:00"
        }

        cache.set(
            "test:timetable",
            test_data
        )

        result = cache.get("test:timetable")

        print("Cached data:")
        print(result)

        cache.delete("test:timetable")

        print("Test cache deleted.")

    else:

        print("Could not connect to Redis.")