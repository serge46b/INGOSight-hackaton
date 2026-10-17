import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.assistant import safe_scheduled_digest
from app.config import settings
from app.errors import AppError
from app.routes import prepare_database, router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("ingosight")
scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    prepare_database()
    scheduler.add_job(
        safe_scheduled_digest,
        "cron",
        hour=settings.digest_hour,
        minute=0,
        id="morning-digest",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("application started")
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="INGOSight", version="0.1.0", lifespan=lifespan)
app.include_router(router)


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    logger.info("request failed code=%s status=%s", exc.code, exc.status)
    return JSONResponse(
        status_code=exc.status,
        content={"code": exc.code, "message": exc.message, "details": exc.details},
    )


@app.exception_handler(Exception)
async def unhandled_handler(_request: Request, _exc: Exception) -> JSONResponse:
    logger.info("request failed code=DATABASE_ERROR")
    return JSONResponse(
        status_code=500,
        content={
            "code": "DATABASE_ERROR",
            "message": "Не удалось сохранить. Попробуйте ещё раз",
            "details": None,
        },
    )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    response = await call_next(request)
    logger.info("%s %s -> %s", request.method, request.url.path, response.status_code)
    return response
