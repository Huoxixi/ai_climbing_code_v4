"""Static browser-local replay and desktop download. No accounts or uploads."""
import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT=Path(__file__).resolve().parents[1]


def create_app(*,static_root=None,installer=None,installer_filename=None):
    static_root=Path(static_root or os.getenv('CLIMB_BROWSER_STATIC_DIR') or ROOT/'frontend/dist-browser')
    installer=Path(installer or os.getenv('CLIMB_BROWSER_INSTALLER') or ROOT.parents[1]/'public-releases/setup-build-20261018-c/ClimbingAssistant-Setup-0.1.18-local.20261018.exe')
    installer_filename=installer_filename or installer.name
    app=FastAPI(title='攀岩助手 · 浏览器本机复盘',docs_url=None,redoc_url=None,openapi_url=None)

    @app.middleware('http')
    async def response_headers(request,call_next):
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        path=request.url.path
        if path.startswith(('/browser-models/','/browser-fonts/','/assets/')) and response.status_code in (200,206):
            response.headers['Cache-Control']='public, max-age=31536000, immutable'
        elif path=='/' or path.endswith('.html') or path.startswith('/api/'):
            response.headers['Cache-Control']='no-store'
        return response

    @app.get('/downloads/climbing-assistant-windows.exe')
    def download():
        if not installer.is_file():
            raise HTTPException(404,'安装包暂不可用，请稍后重试。')
        return FileResponse(installer,filename=installer_filename,media_type='application/octet-stream',headers={'X-Content-Type-Options':'nosniff'})

    @app.get('/api/browser/health')
    def health():
        return {'status':'ok','compute':'browser-only','accounts':False,'media_uploads':False}

    @app.get('/api/health')
    def deployment_health():
        return {**health(),'status':'success','release_sha':os.getenv('RELEASE_SHA','development')}

    @app.api_route('/api/{path:path}',methods=['GET','HEAD','POST','PUT','PATCH','DELETE','OPTIONS'])
    def no_application_api(path:str):
        raise HTTPException(404,'网页版无需账号，视频和记录在本机处理。')

    if static_root.is_dir():
        @app.get('/')
        def home():
            return FileResponse(static_root/'browser-replay.html',headers={'Cache-Control':'no-cache'})
        app.mount('/',StaticFiles(directory=static_root,html=True),name='browser-static')
    return app
