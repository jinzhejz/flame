#!/usr/bin/env python3
"""
Example usage of the Flame Python SDK.
"""

from concurrent.futures import wait

import flamepy


class MyTaskInformer(flamepy.TaskInformer):
    """Example task informer that prints task updates."""

    def on_update(self, task):
        print(f"Task {task.id}: {task.state.name}")

    def on_error(self, error):
        print(f"Error: {error}")


def main():
    print("Creating session...")
    session = flamepy.create_session(application="flmtest", common_data=b"shared data")
    print(f"Created session: {session.id}")

    # Invoke task synchronously with informer
    print("\n1. Running task with informer...")
    session.invoke(b"task input data", MyTaskInformer())

    # Invoke task synchronously and get result
    print("\n2. Running task synchronously...")
    result = session.invoke(b"sync task input")
    print(f"Sync result: {result}")

    # Run task asynchronously with Future
    print("\n3. Running task asynchronously with Future...")
    future = session.run(b"async task input")
    print("Task submitted, doing other work...")
    result = future.result()  # Wait for completion
    print(f"Async result: {result}")

    # Run multiple tasks in parallel
    print("\n4. Running multiple tasks in parallel...")
    futures = [session.run(f"parallel task {i}".encode()) for i in range(5)]

    # Wait for all tasks to complete
    wait(futures)
    results = [f.result() for f in futures]
    print(f"Parallel results: {len(results)} tasks completed")

    # Run tasks with callbacks
    print("\n5. Running task with callback...")

    def task_done(future):
        try:
            result = future.result()
            print(f"Callback: Task completed with result: {result}")
        except Exception as e:
            print(f"Callback: Task failed with error: {e}")

    future = session.run(b"callback task input")
    future.add_done_callback(task_done)
    future.result()  # Wait for completion

    # Close session
    print("\nClosing session...")
    session.close()

    print("Example completed successfully!")


if __name__ == "__main__":
    main()
