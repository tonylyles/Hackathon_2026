"""Latest-frame, single-flight inference for the live booth preview."""
from dataclasses import dataclass
import threading
import time


@dataclass(frozen=True)
class PreviewResult:
    frame: object
    sequence: int
    captured_at: float
    finished_at: float
    inference_ms: float


class PreviewWorker:
    def __init__(self, stylizer, inference_lock=None, clock=time.monotonic):
        self.stylizer = stylizer
        self.inference_lock = inference_lock or threading.Lock()
        self.clock = clock
        self._condition = threading.Condition()
        self._pending = None
        self._result = None
        self._sequence = 0
        self._stopped = False
        self._enabled = True
        self._generation = 0
        self._error = None
        self._thread = None
        self.dropped = 0

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="booth-preview", daemon=True)
            self._thread.start()
        return self

    def submit(self, frame, captured_at=None):
        with self._condition:
            if self._stopped or not self._enabled:
                return
            if self._pending is not None:
                self.dropped += 1
            self._sequence += 1
            self._pending = (self._sequence, frame.copy(),
                             self.clock() if captured_at is None else captured_at)
            self._condition.notify()

    def set_enabled(self, enabled):
        with self._condition:
            if enabled != self._enabled:
                self._generation += 1
            self._enabled = enabled
            if not enabled:
                self._pending = None
            self._condition.notify()

    def snapshot(self):
        with self._condition:
            return self._result, self._error

    def _loop(self):
        while True:
            with self._condition:
                while self._pending is None and not self._stopped:
                    self._condition.wait()
                if self._stopped:
                    return
                sequence, frame, captured_at = self._pending
                generation = self._generation
                self._pending = None
            try:
                started = self.clock()
                with self.inference_lock:
                    result = self.stylizer(frame)
                finished = self.clock()
                if result is None or result.ndim != 3 or result.shape[2] != 3:
                    raise ValueError("风格化未返回有效彩色画面")
                with self._condition:
                    if not self._stopped and self._enabled and generation == self._generation:
                        self._result = PreviewResult(result, sequence, captured_at,
                                                     finished, (finished - started) * 1000)
                        self._error = None
            except Exception as exc:
                with self._condition:
                    if not self._stopped and self._enabled and generation == self._generation:
                        self._error = str(exc)

    def close(self):
        with self._condition:
            self._stopped = True
            self._pending = None
            self._condition.notify()
        if self._thread is not None:
            self._thread.join(timeout=2)
