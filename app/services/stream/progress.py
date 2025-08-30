# app/services/progress.py
import asyncio

class ProgressRegistry:
    def __init__(self):
        self.state: dict[int, dict] = {}
        self.queues: dict[int, asyncio.Queue] = {}

    def get_queue(self, user_id: int) -> asyncio.Queue:
        # setdefault — атомарно для одного треда; под asyncio этого хватает
        return self.queues.setdefault(user_id, asyncio.Queue())

    def start(self, user_id: int, task_id: str):
        snap = {"task_id": task_id, "percent": 0, "step": "queued", "status": "running"}
        self.state[user_id] = snap
        self.get_queue(user_id).put_nowait(snap)

    def update(self, user_id: int, percent: int, step: str):
        snap = {**self.state.get(user_id, {}), "percent": percent, "step": step, "status": "running"}
        self.state[user_id] = snap
        self.get_queue(user_id).put_nowait(snap)

    def finish(self, user_id: int, ok: bool, error: str | None = None):
        snap = {
            **self.state.get(user_id, {}),
            "percent": 100 if ok else self.state.get(user_id, {}).get("percent", 0),
            "status": "done" if ok else "error",
            "error": error,
        }
        self.state[user_id] = snap
        self.get_queue(user_id).put_nowait(snap)

    def snapshot(self, user_id: int) -> dict | None:
        return self.state.get(user_id)

    async def stream(self, user_id: int):
        q = self.get_queue(user_id)
        if user_id in self.state:
            yield self.state[user_id]
        while True:
            yield await q.get()

progress_registry = ProgressRegistry()
