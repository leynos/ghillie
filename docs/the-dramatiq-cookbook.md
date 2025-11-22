# The Dramatiq cookbook

This document describes two common patterns for integrating Dramatiq into
Ghillie:

- a two-tier scheduling model using either an in-process application scheduler
  or Kubernetes CronJobs, and
- asynchronous workers for CPU-bound work using `loky` and
  `asyncio.run_in_executor`.

The goal is to provide predictable, observable behaviour in small deployments
while allowing more complex estates to scale CPU-intensive jobs and scheduling
concerns independently of the core web application.

## Scheduled tasks

### Design goals

Scheduled tasks in Ghillie share the following design goals:

- **Single logical model**: Each scheduled task is defined once as a logical
  job. The job identifies which Dramatiq actor to call, the schedule, and any
  fixed arguments.
- **Multiple drivers**: The same logical job can be executed by an
  application-level scheduler, or by Kubernetes CronJobs, without changing the
  code that implements the work.
- **Config-driven behaviour**: Schedules and drivers are configured in a
  configuration file, not hardcoded in Python. Changes to job cadence and
  driver are applied via configuration and deployment rather than code edits.
- **Gradual complexity**: Small deployments use an in-process scheduler. Larger
  deployments can promote heavy jobs to dedicated CronJobs with separate
  resource limits.

### Job model

Logical jobs are declared in configuration. The exact format is implementation
specific, but the following YAML illustrates the model:

```yaml
jobs:
  estate_scan:
    actor: "ghillie.tasks.run_estate_scan"
    schedule: "*/15 * * * *"  # every 15 minutes
    driver: "app_scheduler"
    enabled: true

  nightly_rollup:
    actor: "ghillie.tasks.run_nightly_rollup"
    schedule: "0 2 * * *"     # 02:00 UTC every day
    driver: "k8s_cron"
    enabled: true

  ad_hoc_heavy_thing:
    actor: "ghillie.tasks.run_big_data_crunch"
    schedule: "0 */6 * * *"   # every 6 hours
    driver: "k8s_cron"
    enabled: false
```

Each job definition includes:

- `actor`: the fully-qualified name of the Dramatiq actor to invoke,
- `schedule`: the crontab expression defining the execution cadence,
- `driver`: the execution driver, either `app_scheduler` or `k8s_cron`, and
- `enabled`: a boolean flag for temporarily disabling a job.

The configuration file is treated as the single source of truth for scheduled
jobs.

### Tier 1: app_scheduler

The `app_scheduler` driver uses
[APScheduler](https://apscheduler.readthedocs.io/) from within each Ghillie
worker pod. A dedicated scheduler process loads the job configuration, creates
`CronTrigger` instances for jobs with `driver == "app_scheduler"`, and sends
messages to the appropriate Dramatiq actors.

#### Scheduler process

The scheduler process can be implemented as a small module that runs a
`BlockingScheduler`:

```python
# ghillie/scheduler/app_scheduler.py
from __future__ import annotations

import importlib

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import dramatiq

from ghillie.config import load_schedule_config


def resolve_actor(path: str) -> dramatiq.Actor:
    module_name, attr = path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    actor = getattr(module, attr)
    if not isinstance(actor, dramatiq.Actor):
        msg = f"Object at {path} is not a Dramatiq actor"
        raise TypeError(msg)
    return actor


def start_app_scheduler() -> None:
    cfg = load_schedule_config()
    scheduler = BlockingScheduler(timezone="UTC")

    for name, job in cfg.jobs.items():
        if not job.enabled or job.driver != "app_scheduler":
            continue

        actor = resolve_actor(job.actor)
        trigger = CronTrigger.from_crontab(job.schedule)

        def make_job(a: dramatiq.Actor, logical_name: str):
            def _job() -> None:
                # Optional: add idempotency keys or additional metadata.
                a.send()

            _job.__name__ = f"{logical_name}_runner"
            return _job

        scheduler.add_job(
            make_job(actor, name),
            trigger=trigger,
            id=name,
            max_instances=1,
            coalesce=True,
        )

    scheduler.start()
```

The scheduler runs as a sidecar process in lightweight deployments, for
example:

```plaintext
python -m ghillie.scheduler.app_scheduler
```

Each scheduled job resolves the actor at runtime, which keeps the Dramatiq
application code independent of the scheduling driver.

#### Characteristics

The `app_scheduler` driver has the following characteristics:

- shares the same deployment unit as the web application and Dramatiq workers,
- requires no Kubernetes-specific configuration,
- is suitable for development environments and small installations, and
- is easy to reason about, as all scheduling logic resides in the application
  repository.

The trade-off is that the scheduler and the workers share resource limits. CPU
heavy jobs may impact latency for other work in the same pod.

### Tier 2: k8s_cron

The `k8s_cron` driver represents the same logical jobs using Kubernetes
CronJobs. Each CronJob runs a small trigger command that loads configuration
and sends a message to the correct Dramatiq actor.

This approach allows heavy or long-running jobs to run in dedicated pods with
separate resource limits, pod disruption budgets, and observability.

#### Trigger entrypoint

A minimal trigger entrypoint loads the schedule configuration and sends the
message for the named job:

```python
# ghillie/cli_trigger.py
from __future__ import annotations

import importlib
import sys

import dramatiq

from ghillie.config import load_schedule_config


def resolve_actor(path: str) -> dramatiq.Actor:
    module_name, attr = path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    actor = getattr(module, attr)
    if not isinstance(actor, dramatiq.Actor):
        msg = f"Object at {path} is not a Dramatiq actor"
        raise TypeError(msg)
    return actor


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("Usage: ghillie-trigger <job_name>", file=sys.stderr)
        return 1

    job_name = args[0]

    cfg = load_schedule_config()
    job = cfg.jobs.get(job_name)
    if job is None:
        print(f"Unknown job: {job_name}", file=sys.stderr)
        return 1

    if not job.enabled:
        print(f"Job {job_name} disabled; skipping", file=sys.stderr)
        return 0

    actor = resolve_actor(job.actor)
    actor.send()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
```

The container image for Ghillie includes this entrypoint. The CronJob invokes
it with the logical job name.

#### CronJob manifest generation

CronJob manifests can be generated from the same schedule configuration used by
`app_scheduler`.

The following function emits a list of Kubernetes-manifest dictionaries for
jobs with `driver == "k8s_cron"` and `enabled == true`:

```python
# ghillie/scheduler/k8s_export.py
from __future__ import annotations

from typing import Any

from ghillie.config import load_schedule_config


def export_k8s_cronjobs(namespace: str = "ghillie") -> list[dict[str, Any]]:
    cfg = load_schedule_config()
    manifests: list[dict[str, Any]] = []

    for name, job in cfg.jobs.items():
        if not job.enabled or job.driver != "k8s_cron":
            continue

        cronjob = {
            "apiVersion": "batch/v1",
            "kind": "CronJob",
            "metadata": {
                "name": f"ghillie-{name}",
                "namespace": namespace,
            },
            "spec": {
                "schedule": job.schedule,
                "concurrencyPolicy": "Forbid",
                "jobTemplate": {
                    "spec": {
                        "template": {
                            "spec": {
                                "restartPolicy": "Never",
                                "containers": [
                                    {
                                        "name": "trigger",
                                        "image": "ghillie:latest",
                                        "command": [
                                            "python",
                                            "-m",
                                            "ghillie.cli_trigger",
                                            name,
                                        ],
                                        "envFrom": [
                                            {"configMapRef": {"name": "ghillie-config"}},
                                            {"secretRef": {"name": "ghillie-secrets"}},
                                        ],
                                    }
                                ],
                            }
                        }
                    }
                },
            },
        }
        manifests.append(cronjob)

    return manifests
```

A command-line wrapper can serialise the manifests to YAML and emit them for
continuous delivery pipelines to apply:

```plaintext
ghillie-schedule export --format k8s-cron > k8s/cronjobs.generated.yaml
kubectl apply -f k8s/cronjobs.generated.yaml
```

#### Choosing a driver

The following guidance can help select an appropriate driver.

- Use `app_scheduler` when:
  - deployments run a small number of pods,
  - scheduled jobs are primarily I/O bound or short-lived,
  - operational teams prefer a single deployment unit, and
  - configuration management is simpler inside the application repository.

- Use `k8s_cron` when:
  - scheduled jobs are CPU-heavy or memory-intensive,
  - resource limits and retry policies differ from the main worker pods,
  - jobs benefit from independent scaling, or
  - platform teams prefer cluster-native observability and control.

Jobs can change driver by modifying the configuration. The application code
and Dramatiq actor implementation remain unchanged.

### Operational considerations

Some operational concerns apply regardless of driver.

- **Idempotency**: Scheduled jobs should be idempotent or accept an
  idempotency key. Both drivers may re-run a job following failures.
- **Time zones**: Schedules are expressed in UTC. User-facing reporting should
  convert to relevant local time zones.
- **Observability**: Jobs should log at start and completion. Logs should
  include the logical job name and any idempotency key or correlation ID.
- **Back-pressure**: Jobs that enqueue further work should respect existing
  queue depth and back-pressure mechanisms.

## CPU-bound work in async Dramatiq actors

### Overview

Dramatiq actors are synchronous by default but can be defined as asynchronous
functions when the AsyncIO middleware is enabled. For actors that perform both
I/O and CPU-bound computation, it is often desirable to:

- use native asynchronous I/O for network and database access, and
- offload CPU-heavy sections to a pool of worker processes.

This section describes a pattern that uses `loky` and
`asyncio.AbstractEventLoop.run_in_executor` to provide an awaitable API for
CPU-bound tasks called from async Dramatiq actors.

### Using loky with run_in_executor

[loky](https://loky.readthedocs.io/) provides a robust
`ProcessPoolExecutor` implementation with a `get_reusable_executor` helper that
returns a process-local pool. Reusing the pool avoids the overhead of creating
new processes for every task.

The following helper module defines an `async` function that submits a callable
and arguments to loky and awaits the result:

```python
# ghillie/concurrency/cpu_pool.py
from __future__ import annotations

import asyncio
from functools import partial
from typing import Any, Awaitable, Callable, TypeVar

from loky import get_reusable_executor

T = TypeVar("T")


async def run_cpu_bound(
    func: Callable[..., T],
    *args: Any,
    max_workers: int | None = None,
    **kwargs: Any,
) -> T:
    """Run a CPU-bound function in a loky process pool.

    The callable and its arguments must be picklable. The function is executed
    in a child process and the result is returned to the caller.
    """

    loop = asyncio.get_running_loop()

    # get_reusable_executor returns a per-process executor that persists across
    # calls and reuses worker processes.
    executor = get_reusable_executor(max_workers=max_workers)

    bound = partial(func, *args, **kwargs)
    return await loop.run_in_executor(executor, bound)
```

### Example: async Dramatiq actor using loky

The following example shows an async Dramatiq actor that performs I/O-bound
work to fetch data, then delegates CPU-heavy analysis to `run_cpu_bound`.

```python
# ghillie/tasks/repo_analysis.py
from __future__ import annotations

import dramatiq
from dramatiq.middleware import AsyncIO

from ghillie.concurrency.cpu_pool import run_cpu_bound
from ghillie.github import fetch_repo_metadata_async
from ghillie.graph import build_dependency_graph_async
from ghillie.storage import store_analysis_async


# Ensure the AsyncIO middleware is enabled when configuring the broker.
# broker.add_middleware(AsyncIO())


def _analyse_graph(graph: dict) -> dict:
    """CPU-heavy analysis of a repository dependency graph.

    This function must be pure with respect to process state. It may not share
    database sessions or network connections with the parent process.
    """

    # Perform expensive traversal, clustering, and scoring.
    return perform_expensive_analysis(graph)


@dramatiq.actor
async def analyse_repo(repo_id: str) -> None:
    """Analyse a repository using async I/O and a CPU pool.

    The actor fetches metadata and dependency graph information using
    asynchronous I/O, then offloads CPU-bound analysis to loky. The result is
    stored using asynchronous persistence.
    """

    metadata = await fetch_repo_metadata_async(repo_id)
    graph = await build_dependency_graph_async(repo_id, metadata)

    analysis = await run_cpu_bound(_analyse_graph, graph)

    await store_analysis_async(repo_id, analysis)
```

The actor uses native async functions for remote calls and storage, while the
pure CPU work executes in a separate process. From the perspective of the
actor implementation, the CPU-bound section appears as a single `await`.

### Error handling and timeouts

Errors raised by the CPU-bound function will propagate back to the Dramatiq
actor as exceptions. These should be handled consistently with other actor
failures.

If job-level timeouts are required, they can be implemented by combining
`asyncio.wait_for` with `run_cpu_bound`:

```python
import asyncio


async def run_cpu_bound_with_timeout(func, *args, timeout: float, **kwargs):
    return await asyncio.wait_for(
        run_cpu_bound(func, *args, **kwargs),
        timeout=timeout,
    )
```

Dramatiq middleware such as `TimeLimit` may also be used to bound total actor
execution time, although this does not directly cancel work already running in
child processes.

### Tuning and queues

The following guidelines help prevent oversubscription and contention:

- Use a dedicated Dramatiq queue for CPU-heavy actors and configure a smaller
  number of worker processes for that queue.
- Configure `max_workers` in `get_reusable_executor` based on the available
  CPU cores and the expected number of concurrent workers.
- Prefer a small number of CPU-heavy actors in flight per process to avoid
  contention for CPU resources.

Empirical observation of queue depth, latency, and CPU utilisation should
inform the final values.

### When not to use loky

The loky-based pattern is not appropriate in all situations.

- Workloads that are primarily I/O-bound benefit more from native async I/O
  than from additional processes.
- Functions that depend on non-picklable state, such as open database
  connections, cannot be passed to loky.
- Libraries that are not safe for use with multiple processes or repeated
  imports may display undefined behaviour when used inside the pool.

In such cases, consider either a purely async implementation or a dedicated
Dramatiq queue with more worker processes and no additional child processes.

## Summary

The patterns described in this document provide a consistent foundation for
scheduled work and CPU-bound tasks in Ghillie:

- Scheduled tasks are defined once as logical jobs and executed either by an
  application scheduler or by Kubernetes CronJobs, depending on deployment
  needs.
- Async Dramatiq actors can safely offload CPU-bound work to a loky
  process pool, preserving a clear separation between I/O and computation.

Both patterns prioritise configuration-driven behaviour, isolation of
responsibilities, and operational observability.

