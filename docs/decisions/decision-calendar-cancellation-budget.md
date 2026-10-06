# Decision: calendar HTTP permits survive client cancellation

`list_all_events` limits in-flight HTTP reads across calls in one event loop. Cancelling
an `asyncio.to_thread` waiter leaves its thread running, so the permit must outlive
that waiter (issue #918).

Acquire the shared semaphore before starting a worker task. Shield the worker from
caller cancellation, retain it until completion, and release the permit from its done
callback. Cancellation while waiting for capacity starts no worker. A client can stop
waiting immediately; the already-issued read finishes in the background and its
exception is consumed if its original waiter is gone. The existing per-thread HTTP
transport and per-calendar error attribution remain in place.

This changes read cancellation ordering only. Event-loop shutdown remains governed by
Python's task and executor shutdown; no new server process or persistent queue is added.
Tests hold real HTTP worker threads behind events and verify that a cancelled call
cannot release capacity to a second call, then that completion releases all capacity.
