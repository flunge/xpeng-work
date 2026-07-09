import asyncio
import uvicorn
from fastapi import FastAPI
from tse.config import get_settings
from tse.worker import connect, run_worker
from tse.server.control_api import build_router


async def _serve() -> None:
    s = get_settings()
    client = await connect()

    app = FastAPI(title="tse-agentd")
    app.include_router(build_router(client))

    host, port = s.control_listen.split(":")
    config = uvicorn.Config(app, host=host, port=int(port),
                            ssl_certfile=s.tls_cert, ssl_keyfile=s.tls_key, log_level="info")
    server = uvicorn.Server(config)

    # 同进程并发跑：控制 API + Temporal Worker
    await asyncio.gather(server.serve(), run_worker())


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
