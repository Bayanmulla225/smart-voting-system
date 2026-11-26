
import threading
import time


class LivenessSessionStore:
    """
    Maintains a separate liveness service for each browser login session.
    """

    def __init__(self, timeout_seconds=300):
        self.sessions = {}
        self.timeout_seconds = timeout_seconds
        self.lock = threading.RLock()

    def create(self, token, service):
        with self.lock:
            old_entry = self.sessions.pop(token, None)

            if old_entry:
                try:
                    old_entry["service"].close()
                except Exception:
                    pass

            self.sessions[token] = {
                "service": service,
                "verified": False,
                "last_activity": time.time()
            }

    def get(self, token):
        with self.lock:
            entry = self.sessions.get(token)

            if not entry:
                return None

            if time.time() - entry["last_activity"] > self.timeout_seconds:
                self._remove(token)
                return None

            entry["last_activity"] = time.time()
            return entry

    def mark_verified(self, token):
        with self.lock:
            entry = self.get(token)

            if entry:
                entry["verified"] = True
                return True

            return False

    def is_verified(self, token):
        entry = self.get(token)
        return bool(entry and entry["verified"])

    def consume(self, token):
        with self.lock:
            entry = self.get(token)

            if not entry or not entry["verified"]:
                return False

            entry["verified"] = False
            return True

    def remove(self, token):
        with self.lock:
            self._remove(token)

    def _remove(self, token):
        entry = self.sessions.pop(token, None)

        if entry:
            try:
                entry["service"].close()
            except Exception:
                pass


liveness_store = LivenessSessionStore()
