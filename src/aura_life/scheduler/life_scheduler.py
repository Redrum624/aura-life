"""
Life Scheduler

APScheduler-based background simulation for the persona's autonomous life.
"""

import logging
from datetime import datetime
from typing import Callable, Optional

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False


logger = logging.getLogger(__name__)


class LifeScheduler:
    """
    Manages the background simulation loop.

    Tick intervals:
    - World tick: 5 minutes (weather, time)
    - Activity tick: 20 minutes (perform activities)
    - Energy tick: 5 minutes (circadian, boosts decay)
    - Goal tick: 60 minutes (check progress, generate daily)
    """

    def __init__(
        self,
        on_world_tick: Optional[Callable] = None,
        on_activity_tick: Optional[Callable] = None,
        on_energy_tick: Optional[Callable] = None,
        on_goal_tick: Optional[Callable] = None,
        on_plan_tick: Optional[Callable] = None,
    ):
        """
        Initialize the scheduler.

        Args:
            on_world_tick: Callback for world updates
            on_activity_tick: Callback for activity simulation
            on_energy_tick: Callback for energy updates
            on_goal_tick: Callback for goal management
            on_plan_tick: Callback for daily plan generation/revision
        """
        self._on_world_tick = on_world_tick
        self._on_activity_tick = on_activity_tick
        self._on_energy_tick = on_energy_tick
        self._on_goal_tick = on_goal_tick
        self._on_plan_tick = on_plan_tick

        self._scheduler: Optional["AsyncIOScheduler"] = None
        self._is_running = False
        self._last_ticks = {
            "world": None,
            "activity": None,
            "energy": None,
            "goal": None,
            "plan": None,
        }

    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._is_running

    def start(self) -> None:
        """Start the background scheduler."""
        if not HAS_APSCHEDULER:
            logger.warning("APScheduler not installed. Life simulation will run manually.")
            return

        if self._is_running:
            logger.warning("Scheduler already running")
            return

        self._scheduler = AsyncIOScheduler()

        # World tick - every 5 minutes
        if self._on_world_tick:
            self._scheduler.add_job(
                self._world_tick_wrapper,
                IntervalTrigger(minutes=5),
                id="world_tick",
                name="World Environment Update",
            )

        # Energy tick - every 5 minutes
        if self._on_energy_tick:
            self._scheduler.add_job(
                self._energy_tick_wrapper,
                IntervalTrigger(minutes=5),
                id="energy_tick",
                name="Energy State Update",
            )

        # Activity tick - every 20 minutes
        if self._on_activity_tick:
            self._scheduler.add_job(
                self._activity_tick_wrapper,
                IntervalTrigger(minutes=20),
                id="activity_tick",
                name="Activity Simulation",
            )

        # Goal tick - every 60 minutes
        if self._on_goal_tick:
            self._scheduler.add_job(
                self._goal_tick_wrapper,
                IntervalTrigger(minutes=60),
                id="goal_tick",
                name="Goal Management",
            )

        # Plan tick - every 30 minutes (checks if new day, revises if needed)
        if self._on_plan_tick:
            self._scheduler.add_job(
                self._plan_tick_wrapper,
                IntervalTrigger(minutes=30),
                id="plan_tick",
                name="Daily Plan Management",
            )

        try:
            self._scheduler.start()
        except RuntimeError as e:
            # AsyncIOScheduler binds to the *running* loop here. A synchronous
            # host has none, and the origin application never hit this because
            # it always started the service from inside an async server.
            # Degrade to the same manual-tick fallback a host with no
            # APScheduler at all gets -- otherwise installing the optional
            # extra makes the failure worse instead of better.
            self._scheduler = None
            self._is_running = False
            logger.warning(
                "Life scheduler could not start: %s. "
                "AsyncIOScheduler needs a running asyncio event loop; call "
                "start() from inside one, or drive the ticks yourself with "
                "force_all_ticks(). Life simulation will run manually.",
                e,
            )
            return
        self._is_running = True
        logger.info("Life scheduler started")

    def stop(self) -> None:
        """Stop the scheduler and drop every reference it holds.

        `wait=True` asks APScheduler to let in-flight ticks settle instead of
        abandoning them mid-run while the owning service tears its state down.
        Clearing `self._scheduler` afterwards releases the dead scheduler and
        the job objects that close over the tick callbacks; leaving it set kept
        all of that reachable for the life of the process.  `start()` rebuilds
        the scheduler, so stop/start cycles still work.
        """
        scheduler, self._scheduler = self._scheduler, None
        was_running, self._is_running = self._is_running, False
        if scheduler is None or not was_running:
            return
        try:
            scheduler.shutdown(wait=True)
        except Exception as e:
            logger.warning(f"Error shutting down life scheduler: {e}")
        logger.info("Life scheduler stopped")

    def force_tick(self, tick_type: str) -> None:
        """
        Force a specific tick to run immediately.

        Args:
            tick_type: "world", "activity", "energy", or "goal"
        """
        callbacks = {
            "world": self._on_world_tick,
            "activity": self._on_activity_tick,
            "energy": self._on_energy_tick,
            "goal": self._on_goal_tick,
            "plan": self._on_plan_tick,
        }

        callback = callbacks.get(tick_type)
        if callback:
            try:
                callback()
                self._last_ticks[tick_type] = datetime.now()
            except Exception as e:
                logger.error(f"Error in forced {tick_type} tick: {e}")

    def force_all_ticks(self) -> None:
        """Force all ticks to run immediately."""
        for tick_type in ["world", "energy", "plan", "activity", "goal"]:
            self.force_tick(tick_type)

    def get_status(self) -> dict:
        """Get scheduler status."""
        jobs_info = []
        if self._scheduler and self._is_running:
            for job in self._scheduler.get_jobs():
                next_run = job.next_run_time
                jobs_info.append({
                    "id": job.id,
                    "name": job.name,
                    "next_run": next_run.isoformat() if next_run else None,
                })

        return {
            "is_running": self._is_running,
            "has_apscheduler": HAS_APSCHEDULER,
            "jobs": jobs_info,
            "last_ticks": {
                k: v.isoformat() if v else None
                for k, v in self._last_ticks.items()
            },
        }

    # ============= Tick Wrappers =============

    async def _world_tick_wrapper(self) -> None:
        """Wrapper for world tick with error handling."""
        try:
            if self._on_world_tick:
                self._on_world_tick()
                self._last_ticks["world"] = datetime.now()
        except Exception as e:
            logger.error(f"Error in world tick: {e}")

    async def _energy_tick_wrapper(self) -> None:
        """Wrapper for energy tick with error handling."""
        try:
            if self._on_energy_tick:
                self._on_energy_tick()
                self._last_ticks["energy"] = datetime.now()
        except Exception as e:
            logger.error(f"Error in energy tick: {e}")

    async def _activity_tick_wrapper(self) -> None:
        """Wrapper for activity tick with error handling."""
        try:
            if self._on_activity_tick:
                self._on_activity_tick()
                self._last_ticks["activity"] = datetime.now()
        except Exception as e:
            logger.error(f"Error in activity tick: {e}")

    async def _goal_tick_wrapper(self) -> None:
        """Wrapper for goal tick with error handling."""
        try:
            if self._on_goal_tick:
                self._on_goal_tick()
                self._last_ticks["goal"] = datetime.now()
        except Exception as e:
            logger.error(f"Error in goal tick: {e}")

    async def _plan_tick_wrapper(self) -> None:
        """Wrapper for plan tick with error handling."""
        try:
            if self._on_plan_tick:
                self._on_plan_tick()
                self._last_ticks["plan"] = datetime.now()
        except Exception as e:
            logger.error(f"Error in plan tick: {e}")
