"""Isolated local integration server; never opens the application's data directory."""
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from fastapi import FastAPI
from core.photo_route_v2 import PhotoRouteJobManager, PhotoRouteV2Store, create_photo_route_v2_router

scratch = TemporaryDirectory(prefix="boulder-ui-test-")
store = PhotoRouteV2Store(Path(scratch.name))
jobs = PhotoRouteJobManager(store)


@asynccontextmanager
async def lifespan(app):
    yield
    jobs.close()
    scratch.cleanup()


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def test_owner(request, call_next):
    request.state.pilot_user = SimpleNamespace(username="boulder-ui-test")
    return await call_next(request)


app.include_router(create_photo_route_v2_router(store, jobs))
