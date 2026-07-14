"""独立 Outbox 补发 Worker。"""
import asyncio
import signal

from app.core.logging import get_logger
from app.db.database import init_db
from app.services.outbox import run_outbox_loop
from app.services.queue import close_queue_client


logger = get_logger()


async def main() -> None:
    init_db()
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def stop() -> None:
        logger.info("Outbox Worker 收到停止信号")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop)
        except NotImplementedError:
            pass

    await run_outbox_loop(stop_event)
    await close_queue_client()


if __name__ == "__main__":
    asyncio.run(main())
