"""ControlManager: safety-gated brightness actuation (PLAN.md section 11).

Owns the policy engine, the safety gate (floor clamp, deadband, rate limit,
motion freeze, user-override inhibit), the write worker thread, and the
write ledger. Non-negotiable invariants (11.6):

1. auto disabled → zero writes
2. target clamped to [max(ABS_FLOOR, factor_min·baseline), baseline]
3. motion freeze holds
4. deadband + min write interval gate every write
5. external displays are never instantiated here — the caller routes by
   ``OutputInfo.is_internal``
6. every write is recorded in the WriteLedger
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable

from openbrightness.due.control.base import DisplayControlBackend, WriteLedger
from openbrightness.due.control.policy import AdaptiveBrightnessPolicy, PolicyConfig
from openbrightness.due.models import LuminanceMetrics

log = logging.getLogger(__name__)

ABS_FLOOR = 0.05  # never blackout the panel (research 10.4)
DEADBAND = 0.03  # of baseline
MIN_WRITE_INTERVAL_S = 2.0
INHIBIT_SECONDS = 300.0
OVERRIDE_TOLERANCE = 0.02  # |actual − last_written| beyond this = user change
OVERRIDE_SETTLE_S = 2.0  # ignore drift within this window after our own write

_SENTINEL: object = object()


class ControlStatus:
    """Immutable-ish snapshot for the TUI status strip."""

    __slots__ = (
        "applied",
        "auto_enabled",
        "baseline",
        "inhibited_until",
        "supported",
        "target",
        "writes",
    )

    def __init__(
        self,
        auto_enabled: bool,
        supported: bool = True,
        baseline: float | None = None,
        target: float | None = None,
        applied: float | None = None,
        inhibited_until: float | None = None,
        writes: int = 0,
    ) -> None:
        self.auto_enabled = auto_enabled
        self.supported = supported
        self.baseline = baseline
        self.target = target
        self.applied = applied
        self.inhibited_until = inhibited_until
        self.writes = writes


class ControlManager:
    """Metrics → policy → safety gate → async hardware write."""

    def __init__(
        self,
        backend: DisplayControlBackend | None,
        connector: str = "internal",
        policy_config: PolicyConfig | None = None,
        ledger: WriteLedger | None = None,
        clock: Callable[[], float] = time.monotonic,
        deadband: float = DEADBAND,
        min_write_interval: float = MIN_WRITE_INTERVAL_S,
        inhibit_seconds: float = INHIBIT_SECONDS,
        on_status: Callable[[ControlStatus], None] | None = None,
    ) -> None:
        self._backend = backend
        self._connector = connector
        self._policy = AdaptiveBrightnessPolicy(policy_config)
        self._ledger = ledger or WriteLedger()
        self._clock = clock
        self._deadband = deadband
        self._min_interval = min_write_interval
        self._inhibit_seconds = inhibit_seconds
        self._on_status = on_status

        self._lock = threading.Lock()
        self._auto_enabled = False
        self._baseline: float | None = None
        self._target: float | None = None
        self._applied: float | None = None
        self._last_write_ts = -float("inf")
        self._last_written: float | None = None
        self._inhibited_until: float | None = None

        self._queue: queue.Queue[object] = queue.Queue(maxsize=1)
        self._worker = threading.Thread(
            target=self._worker_loop, name="due-control", daemon=True
        )
        self._worker.start()

    # ---- public API -------------------------------------------------------

    @property
    def ledger(self) -> WriteLedger:
        return self._ledger

    @property
    def supported(self) -> bool:
        return self._backend is not None

    def status(self) -> ControlStatus:
        with self._lock:
            return ControlStatus(
                auto_enabled=self._auto_enabled,
                supported=self._backend is not None,
                baseline=self._baseline,
                target=self._target,
                applied=self._applied,
                inhibited_until=self._inhibited_until,
                writes=self._ledger.count(),
            )

    def enable(self) -> None:
        """Turn auto on; capture the user's current brightness as baseline."""
        if self._backend is None:
            return
        current = self._backend.get_brightness()
        if current is None:
            log.warning("cannot read brightness; auto-adjust not enabled")
            return
        with self._lock:
            self._auto_enabled = True
            self._baseline = current
            self._applied = current
            self._last_written = None
            self._inhibited_until = None
            self._policy.reset()
        self._emit_status()

    def disable(self) -> None:
        """Turn auto off and restore the captured baseline (decision 2:
        restore happens here, NOT on process exit)."""
        restore: float | None = None
        with self._lock:
            self._auto_enabled = False
            self._policy.reset()
            self._target = None
            if self._baseline is not None and self._backend is not None:
                restore = self._baseline
                self._applied = self._baseline
                self._last_written = self._baseline
        if restore is not None and self._backend is not None:
            self._backend.set_brightness(restore)
            self._ledger.record(self._connector, restore)
        self._emit_status()

    def toggle(self) -> bool:
        with self._lock:
            enabled = self._auto_enabled
        if enabled:
            self.disable()
        else:
            self.enable()
        return not enabled

    def on_metrics(self, metrics: LuminanceMetrics) -> None:
        """Feed one metric sample (called from the coordinator worker)."""
        try:
            self._process_metrics(metrics)
        finally:
            self._emit_status()  # every tick: target moves even without writes

    def _process_metrics(self, metrics: LuminanceMetrics) -> None:
        with self._lock:
            if not self._auto_enabled or self._backend is None:
                return
            now = self._clock()
            self._check_override(now)
            if self._inhibited_until is not None and now < self._inhibited_until:
                return
            if self._inhibited_until is not None and now >= self._inhibited_until:
                self._inhibited_until = None

            baseline = self._baseline
            if baseline is None:
                return
            target = self._policy.update(metrics, baseline)
            if target is None:  # motion freeze
                return
            target = self._clamp(target, baseline)
            self._target = target

            applied = self._applied if self._applied is not None else baseline
            if abs(target - applied) < self._deadband * baseline:
                return
            if now - self._last_write_ts < self._min_interval:
                return

            self._last_write_ts = now
            self._last_written = target
            self._applied = target

        # enqueue outside the lock; drop-oldest keeps the pipeline non-blocking
        try:
            self._queue.put_nowait(target)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(target)
            except queue.Full:
                pass

    def stop(self) -> None:
        """Stop the worker thread. Brightness is intentionally left as-is
        (decision 2: quitting must not blind the user at night)."""
        try:
            self._queue.put_nowait(_SENTINEL)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(_SENTINEL)
            except queue.Full:
                pass
        self._worker.join(timeout=2.0)

    # ---- internals --------------------------------------------------------

    def _clamp(self, target: float, baseline: float) -> float:
        floor = max(ABS_FLOOR, min(1.0, self._policy.factor_min * baseline))
        return min(max(target, floor), baseline)

    def _check_override(self, now: float) -> None:
        """Detect manual brightness changes (Fn keys / slider) → inhibit
        (research 10.3: user intent supersedes)."""
        if self._backend is None or self._last_written is None:
            return
        if now - self._last_write_ts < OVERRIDE_SETTLE_S:
            return  # allow our own write to settle
        actual = self._backend.get_brightness()
        if actual is None:
            return
        if abs(actual - self._last_written) > OVERRIDE_TOLERANCE:
            self._inhibited_until = now + self._inhibit_seconds
            self._baseline = actual  # adopt the user's new setting
            self._policy.reset()
            self._last_written = None
            log.debug("manual override detected; inhibiting for %.0fs", self._inhibit_seconds)

    def _worker_loop(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is _SENTINEL:
                    return
                assert isinstance(item, float)
                if self._backend is not None:
                    ok = self._backend.set_brightness(item)
                    if ok:
                        self._ledger.record(self._connector, item)
                    else:
                        log.debug("brightness write of %.3f failed", item)
            finally:
                self._queue.task_done()

    def wait_idle(self, timeout: float = 2.0) -> bool:
        """Block until queued writes are applied (test synchronization)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._queue.unfinished_tasks == 0:
                return True
            time.sleep(0.005)
        return False

    def _emit_status(self) -> None:
        if self._on_status is not None:
            try:
                self._on_status(self.status())
            except Exception:
                log.exception("control status callback failed")
