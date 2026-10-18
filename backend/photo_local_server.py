"""Full application with an isolated, persistent local development directory."""
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
DATA=Path(os.getenv('PHOTO_LOCAL_DATA_DIR', str(ROOT/'.local/photo-development')))
from dotenv import load_dotenv
# Explicit local-only secret file; never load the application's production .env.
load_dotenv(ROOT/'.local/photo-vision.env',override=False)
(DATA/'data/holds_images').mkdir(parents=True,exist_ok=True)
(DATA/'data/holds_images_processed').mkdir(parents=True,exist_ok=True)
os.chdir(DATA)
os.environ['PHOTO_ROUTE_DATA_DIR']=str(DATA/'data/photo_routes')
os.environ['PYTHON_DOTENV_DISABLED']='1'
os.environ['LOCAL_ONLY']='true'
os.environ['APP_ENV']='development'
os.environ['PILOT_AUTH_ENABLED']='false'
os.environ['PILOT_USERS_FILE']=str(DATA/'data/pilot_users.json')
os.environ['PILOT_AUDIT_FILE']=str(DATA/'data/pilot_audit.jsonl')
from boulder_local_app import app
