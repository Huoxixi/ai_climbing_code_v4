"""Isolated HTTP fixture for real import/browser checks, never user app data."""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_replay_import_preview import app_fixture
import uvicorn

parser=argparse.ArgumentParser()
parser.add_argument('--root',type=Path,required=True)
parser.add_argument('--port',type=int,required=True)
args=parser.parse_args()
project=Path(__file__).resolve().parents[2]
root=args.root.resolve()
if not root.is_relative_to(project/'.tmp/video-preview-20261015'):
    raise RuntimeError('Import checks require an isolated test directory')
root.mkdir(parents=True,exist_ok=True)
os.environ['LOCAL_ONLY']='true'
client,store,manager=app_fixture(root)
app=client.app

@app.get('/api/health')
def health():return {'healthy':True,'isolated':True}

@app.get('/__test/stats')
def stats():return {'jobs':len(store.list('alice')),'prepared':len(store.prepared_previews.records)}

@app.post('/__test/close')
def close():
    store.prepared_previews.close()
    return {'prepared':len(store.prepared_previews.records)}

@app.on_event('shutdown')
def shutdown():manager.close()

uvicorn.run(app,host='127.0.0.1',port=args.port,access_log=False,log_level='error')
