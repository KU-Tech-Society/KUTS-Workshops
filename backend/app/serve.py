import asyncio
import signal

import uvicorn

from .main import app
from .student import create_student_app


async def serve():
    organiser = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=8000,
            proxy_headers=False,
            access_log=False,
        )
    )
    student = uvicorn.Server(
        uvicorn.Config(
            create_student_app(app.state.intake),
            host="127.0.0.1",
            port=8001,
            proxy_headers=False,
            access_log=False,
        )
    )
    loop = asyncio.get_running_loop()

    def stop():
        organiser.should_exit = True
        student.should_exit = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop)
    tasks = [asyncio.create_task(server.serve()) for server in (organiser, student)]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop()
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(serve())
