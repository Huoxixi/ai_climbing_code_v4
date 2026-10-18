"""Local boulder application: photos, replay and settings only.

Uses the same owner and storage paths as the previous local application. No
setter routes, solvers, agents or shared-board stores are imported here.
"""
import json
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from core.photo_route_drafts import PhotoRouteStore, create_photo_route_router
from core.photo_route_v2 import PhotoRouteJobManager, PhotoRouteV2Store, create_photo_route_v2_router
from core.climb_replay import ClimbReplayStore, ClimbReplayManager, create_climb_replay_router

if os.getenv('LOCAL_ONLY','').lower() not in {'true','1','yes'}:
    raise RuntimeError('The boulder local entrypoint requires LOCAL_ONLY=true')
os.environ['LOCAL_REPLAY_SIMPLE'] = '1'

CLIMB_REPLAY_TEST_VIDEO_PATH=os.getenv('CLIMB_REPLAY_TEST_VIDEO_PATH','').strip()
CLIMB_REPLAY_TEST_VIDEO_SOURCE_URL=os.getenv('CLIMB_REPLAY_TEST_VIDEO_SOURCE_URL','').strip()
try:
    CLIMB_REPLAY_TEST_VIDEOS=json.loads(os.getenv('CLIMB_REPLAY_TEST_VIDEOS','[]'))
    if not isinstance(CLIMB_REPLAY_TEST_VIDEOS,list):CLIMB_REPLAY_TEST_VIDEOS=[]
except ValueError:
    CLIMB_REPLAY_TEST_VIDEOS=[]

app=FastAPI(title='攀岩助手 · 本地抱石',version='boulder-local-20261009')
app.add_middleware(CORSMiddleware,allow_origins=[f'http://{host}:{port}' for host in ('localhost','127.0.0.1') for port in (5173,4173,4176)],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])

@app.middleware('http')
async def local_owner(request:Request, call_next):
    if request.method == 'POST' and request.url.path.endswith('/actions'):
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        if any(payload.get(key) for key in ('cloud_consent','reuse_saved_commentary','retry_saved_response','replace_legacy_return')):
            return JSONResponse({'detail':'本地版仅生成复盘视频。'},status_code=410)
    if request.method not in {'GET','HEAD','OPTIONS'}:
        origin=request.headers.get('origin')
        if origin and urlsplit(origin).netloc!=request.headers.get('host'):
            return JSONResponse({'detail':'请求来源无效。'},status_code=403)
    request.state.pilot_user=SimpleNamespace(username='owner',display_name='负责人')
    return await call_next(request)

@app.get('/api/auth/session')
def session():
    return {'authenticated':True,'username':'owner','display_name':'负责人','auth_enabled':False}

@app.post('/api/auth/logout')
def logout():
    response=JSONResponse({'authenticated':False})
    response.delete_cookie('pilot_session')
    return response

@app.get('/api/health')
def health():
    return {'status':'success','version':'boulder-local-20261009','local_only':True,'workspace':'boulder','data_readable':PHOTO_ROUTE_DATA_ROOT.is_dir()}

PHOTO_ROUTE_DATA_ROOT = Path(os.getenv("PHOTO_ROUTE_DATA_DIR", str(Path(__file__).resolve().parent / "data/photo_routes")))
photo_route_store = PhotoRouteStore(PHOTO_ROUTE_DATA_ROOT)
app.include_router(create_photo_route_router(photo_route_store))
photo_route_v2_store = PhotoRouteV2Store(PHOTO_ROUTE_DATA_ROOT)
photo_route_jobs = PhotoRouteJobManager(photo_route_v2_store)
app.include_router(create_photo_route_v2_router(photo_route_v2_store, photo_route_jobs))
climb_replay_manager = None
if True:
    def replay_route_reference(route_id: str, owner: str) -> dict | None:
        route = photo_route_v2_store.get_route(route_id, owner)
        board = photo_route_v2_store.get_board(route["board_version_id"], owner)
        member_ids = {member["object_id"] for member in route["members"]}
        confirmed = [
            {"object_id": item["id"], "contour": item["contour"]}
            for item in board["objects"]
            if item["id"] in member_ids and item["review_status"] == "confirmed"
            and item["kind"] == "hold" and len(item["contour"]) >= 3
        ]
        if not confirmed:
            return None
        return {
            "asset_path": str(photo_route_v2_store.asset_path(board["original_asset"]["filename"])),
            "board_id": board["id"], "members": confirmed,
        }

    climb_replay_store = ClimbReplayStore(PHOTO_ROUTE_DATA_ROOT / "climb_replay")
    from core.replay_pose_clip import LocalClipReplayAnalyzer
    climb_replay_manager = ClimbReplayManager(climb_replay_store, LocalClipReplayAnalyzer())
    app.include_router(create_climb_replay_router(
        climb_replay_store,
        climb_replay_manager,
        route_lookup=photo_route_v2_store.get_route,
        route_reference_lookup=replay_route_reference,
        test_video_path=(Path(CLIMB_REPLAY_TEST_VIDEO_PATH)
                         if CLIMB_REPLAY_TEST_VIDEO_PATH else None),
        test_video_source_url=CLIMB_REPLAY_TEST_VIDEO_SOURCE_URL or None,
        test_video_cases=CLIMB_REPLAY_TEST_VIDEOS,
    ))
from core.photo_route_workflow import PhotoWorkflow, workflow_router
photo_workflow = PhotoWorkflow(photo_route_v2_store)
app.include_router(workflow_router(photo_workflow))
# Local application has no service settings or replay coaching/editing entry.
def prune_local_routes(router, prefix=''):
    retained = []
    for route in router.routes:
        child = getattr(route, 'original_router', None)
        if child is not None:
            prune_local_routes(child, prefix + route.include_context.prefix)
        path = prefix + getattr(route, 'path', '')
        removed = path.startswith('/api/settings/') or path.startswith('/api/climb-replay/') and any(
            part in path for part in ('/coaching','/template-video','/comparisons','/segments/',
                '/route-map/refresh','/actions/review'))
        if not removed:
            retained.append(route)
    router.routes[:] = retained
prune_local_routes(app.router)

@app.on_event('shutdown')
def shutdown_boulder():
    photo_workflow.close()
    photo_route_jobs.close()
    if climb_replay_manager is not None:climb_replay_manager.close()
