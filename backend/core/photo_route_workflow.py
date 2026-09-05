"""Durable, one-route-per-user workflow, independent of mounted UI pages."""
from __future__ import annotations
import hashlib
import json
import queue
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Literal

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from core.photo_route_analysis import analyze_board_photo, assess_capture_quality, _colour_name
from core.photo_route_processing import decode_photo
from core.photo_route_vision import review_objects, segment_point


def now(): return datetime.now(timezone.utc).isoformat()


class Change(BaseModel):
    version: int = Field(ge=1)
    request_id: str | None = Field(default=None,min_length=1,max_length=80)
    color: str | None = Field(default=None, max_length=40)
    member_ids: list[str] | None = Field(default=None,max_length=600)
    point: tuple[float,float] | None = None


class MemberNotes(BaseModel):
    object_id: str
    roles: list[Literal['start','end']] = Field(default_factory=list,max_length=2)
    tags: list[str] = Field(default_factory=list,max_length=30)
    note: str = Field(default='',max_length=2000)


class Notes(BaseModel):
    version: int = Field(ge=1)
    request_id: str | None = Field(default=None,min_length=1,max_length=80)
    name: str = Field(default='',max_length=120)
    difficulty: str = Field(default='',max_length=40)
    setter: str = Field(default='',max_length=80)
    notes: str = Field(default='',max_length=4000)
    members: list[MemberNotes] = Field(default_factory=list,max_length=600)


class PhotoWorkflow:
    def __init__(self, store, *, start=True):
        self.store=store; self.stop=threading.Event(); self.queue=queue.Queue(); self.thread=None
        with store.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS photo_work_sessions(
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
              status TEXT NOT NULL, board_id TEXT NOT NULL, source_id TEXT NOT NULL,
              color TEXT, route_id TEXT, progress INTEGER NOT NULL DEFAULT 0,
              stage TEXT NOT NULL, ai_json TEXT NOT NULL DEFAULT '{}', point_json TEXT,
              error TEXT, viewed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
              CREATE UNIQUE INDEX IF NOT EXISTS one_photo_work_per_owner ON photo_work_sessions(owner)
              WHERE status NOT IN ('saved','abandoned');
              CREATE TABLE IF NOT EXISTS photo_work_receipts(
                session_id TEXT NOT NULL, request_id TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(session_id,request_id));''')
        if start:
            self.thread=threading.Thread(target=self._run,daemon=True,name='photo-workflow'); self.thread.start()
            with store.connect() as db:
                for row in db.execute("SELECT id FROM photo_work_sessions WHERE status='processing'"): self.queue.put(row[0])

    def close(self):
        self.stop.set(); self.queue.put(None)
        if self.thread: self.thread.join(2)

    def _row(self, db, sid, owner):
        row=db.execute('SELECT * FROM photo_work_sessions WHERE id=? AND owner=?',(sid,owner)).fetchone()
        if not row: raise HTTPException(404,'未找到当前线路')
        return dict(row)

    def get(self, sid, owner):
        with self.store.connect() as db: row=self._row(db,sid,owner)
        row['ai']=json.loads(row.pop('ai_json')); row.pop('point_json')
        row['board']=self.store.get_board(row['board_id'],owner)
        row['route']=self.store.get_route(row['route_id'],owner) if row['route_id'] else None
        row['colors']=list(dict.fromkeys(obj['color_group'] for obj in row['board']['objects']))
        return row

    def current(self, owner):
        with self.store.connect() as db:
            row=db.execute("SELECT id FROM photo_work_sessions WHERE owner=? AND status NOT IN ('saved','abandoned') ORDER BY created_at DESC LIMIT 1",(owner,)).fetchone()
        return self.get(row[0],owner) if row else None

    def _board(self, db, owner, asset, quality, *, source=None):
        bid=uuid.uuid4().hex; timestamp=now()
        number=1
        if source: number=db.execute('SELECT COALESCE(MAX(board_version_no),0)+1 FROM board_versions WHERE owner=? AND board_key=?',(owner,source['board_key'])).fetchone()[0]
        db.execute('INSERT INTO board_versions(id,owner,board_key,board_version_no,version,status,original_asset,width,height,quality_json,calibration_json,model_version,input_fingerprint,created_at,updated_at,archived_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)',
          (bid,owner,source['board_key'] if source else uuid.uuid4().hex,number,1,'processing',self.store._json(asset),asset['width'],asset['height'],self.store._json(quality),None,None,asset['sha256'],timestamp,timestamp))
        return bid

    def upload(self, owner, sid, filename, data):
        if not sid or len(sid)>80: raise HTTPException(422,'无效的上传请求')
        with self.store.connect() as db:
            existing=db.execute('SELECT owner,board_id FROM photo_work_sessions WHERE id=?',(sid,)).fetchone()
        if existing:
            if existing['owner']!=owner: raise HTTPException(409,'上传请求已被使用')
            previous=self.get(sid,owner)
            if previous['board']['input_fingerprint']!=hashlib.sha256(data).hexdigest(): raise HTTPException(409,'请重新选择照片')
            return previous
        image=decode_photo(data); quality=assess_capture_quality(image)
        if not quality.accepted: raise HTTPException(422,'；'.join(quality.issues))
        # Store original bytes; decoding does not change the user's original.
        suffix=filename.rsplit('.',1)[-1].lower()
        if suffix not in {'jpg','jpeg','png','webp'}: suffix='jpg'
        asset=self.store.save_asset(data,suffix,image.shape[1],image.shape[0])
        try:
            with self.store.transaction() as db:
                repeated=db.execute('SELECT owner FROM photo_work_sessions WHERE id=?',(sid,)).fetchone()
                if repeated:
                    if repeated['owner']!=owner: raise HTTPException(409,'上传请求已被使用')
                    previous=self.get(sid,owner)
                    if previous['board']['input_fingerprint']!=asset['sha256']: raise HTTPException(409,'请重新选择照片')
                    return previous
                if db.execute("SELECT 1 FROM photo_work_sessions WHERE owner=? AND status NOT IN ('saved','abandoned')",(owner,)).fetchone(): raise HTTPException(409,'请先保存或放弃当前线路')
                bid=self._board(db,owner,asset,{'accepted':True,'issues':[],'metrics':quality.metrics})
                db.execute('INSERT INTO photo_work_sessions(id,owner,status,board_id,source_id,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                    (sid,owner,'processing',bid,bid,'正在分析照片颜色',now(),now()))
        except sqlite3.IntegrityError:
            previous=self.current(owner)
            if previous and previous['id']==sid: return previous
            raise HTTPException(409,'请先保存或放弃当前线路')
        self.queue.put(sid)
        return self.get(sid,owner)

    def select(self, sid, owner, change):
        current=self.get(sid,owner)
        with self.store.transaction() as db:
            row=self._row(db,sid,owner)
            fingerprint=self.store._json({'action':'color',**change.model_dump()})
            if change.request_id:
                receipt=db.execute('SELECT payload FROM photo_work_receipts WHERE session_id=? AND request_id=?',(sid,change.request_id)).fetchone()
                if receipt:
                    if receipt[0]!=fingerprint: raise HTTPException(409,'请求编号已用于其他修改')
                    return current
            if change.color not in current['colors']: raise HTTPException(422,'请选择照片中的一种颜色')
            if row['version']!=change.version or row['status']!='awaiting_color': raise HTTPException(409,'线路状态已变化，请刷新当前进度')
            bid=self._board(db,owner,current['board']['original_asset'],current['board']['quality'],source=current['board'])
            db.execute("UPDATE photo_work_sessions SET board_id=?,color=?,status='processing',progress=0,stage='准备提取线路',version=version+1,updated_at=? WHERE id=?",(bid,change.color,now(),sid))
            if change.request_id: db.execute('INSERT INTO photo_work_receipts VALUES(?,?,?)',(sid,change.request_id,fingerprint))
        self.queue.put(sid); return self.get(sid,owner)

    def update(self, sid, owner, change, action):
        current=self.get(sid,owner)
        with self.store.transaction() as db:
            row=self._row(db,sid,owner)
            fingerprint=self.store._json({'action':action,**change.model_dump()})
            if change.request_id:
                receipt=db.execute('SELECT payload FROM photo_work_receipts WHERE session_id=? AND request_id=?',(sid,change.request_id)).fetchone()
                if receipt:
                    if receipt[0]!=fingerprint: raise HTTPException(409,'请求编号已用于其他修改')
                    return current
            if row['version']!=change.version: raise HTTPException(409,'线路已有更新，请重新打开以免覆盖新进度')
            if row['status'] in {'saved','abandoned'}: raise HTTPException(409,'当前任务已结束')
            if action=='abandon':
                db.execute("UPDATE photo_work_sessions SET status='abandoned',version=version+1,stage='已放弃',updated_at=? WHERE id=?",(now(),sid))
            elif action=='viewed':
                db.execute('UPDATE photo_work_sessions SET viewed=1 WHERE id=?',(sid,))
            elif action=='retry':
                if row['status'] not in {'failed','ready'}: raise HTTPException(409,'任务仍在进行')
                db.execute("UPDATE photo_work_sessions SET status='processing',error=NULL,stage='准备重试',version=version+1,updated_at=? WHERE id=?",(now(),sid))
            elif action=='add':
                if row['status']!='ready' or not change.point or any(not np.isfinite(v) or not 0<=v<=1 for v in change.point): raise HTTPException(422,'请在照片中选择要补加的岩点')
                db.execute("UPDATE photo_work_sessions SET status='processing',point_json=?,stage='正在补加岩点',version=version+1,updated_at=? WHERE id=?",(json.dumps(change.point),now(),sid))
            elif action in {'members','save'}:
                if row['status']!='ready': raise HTTPException(409,'请等待提取完成')
                ids=change.member_ids if change.member_ids is not None else [m['object_id'] for m in current['route']['members']]
                valid={obj['id'] for obj in current['board']['objects']}
                if len(set(ids))!=len(ids) or not set(ids)<=valid: raise HTTPException(422,'所选岩点不属于当前照片')
                if action=='save' and not ids: raise HTTPException(422,'请至少保留一个岩点')
                old={m['object_id']:m for m in current['route']['members']}
                db.execute('DELETE FROM route_members WHERE route_id=?',(row['route_id'],))
                for index,oid in enumerate(ids):
                    m=old.get(oid,{})
                    db.execute('INSERT INTO route_members VALUES(?,?,?,?,?,?)',(row['route_id'],oid,json.dumps(m.get('roles',[])),json.dumps(m.get('tags',[])),m.get('note',''),index))
                db.execute('UPDATE routes SET version=version+1,updated_at=? WHERE id=?',(now(),row['route_id']))
                if action=='save':
                    db.execute("UPDATE routes SET status='completed' WHERE id=?",(row['route_id'],))
                    route=dict(db.execute('SELECT * FROM routes WHERE id=?',(row['route_id'],)).fetchone())
                    snapshot=self.store._row_route(db,route)
                    db.execute('INSERT INTO route_revisions VALUES(?,?,?,?,?)',(uuid.uuid4().hex,row['route_id'],route['version'],self.store._json(self.store._snapshot(snapshot)),now()))
                db.execute('UPDATE photo_work_sessions SET status=?,version=version+1,updated_at=? WHERE id=?',('saved' if action=='save' else 'ready',now(),sid))
            else: raise HTTPException(404,'未知操作')
            if change.request_id:
                db.execute('INSERT INTO photo_work_receipts VALUES(?,?,?)',(sid,change.request_id,fingerprint))
        if action in {'retry','add'}: self.queue.put(sid)
        return self.get(sid,owner)

    def notes(self, rid, owner, payload):
        with self.store.transaction() as db:
            route=db.execute('SELECT * FROM routes WHERE id=? AND owner=?',(rid,owner)).fetchone()
            if not route: raise HTTPException(404,'未找到线路')
            fingerprint=self.store._json(payload.model_dump())
            if payload.request_id:
                receipt=db.execute('SELECT payload FROM photo_work_receipts WHERE session_id=? AND request_id=?',('notes:'+rid,payload.request_id)).fetchone()
                if receipt:
                    if receipt[0]!=fingerprint: raise HTTPException(409,'请求编号已用于其他备注')
                    return self.store._row_route(db,route)
            if route['version']!=payload.version: raise HTTPException(409,'线路备注已有更新')
            if route['status']!='completed': raise HTTPException(409,'请先保存线路')
            valid={r[0] for r in db.execute('SELECT object_id FROM route_members WHERE route_id=?',(rid,))}
            for entry in payload.members:
                member=entry.model_dump()
                if member.get('object_id') not in valid or set(member.get('roles',[]))-{'start','end'} or any(not isinstance(t,str) or len(t)>40 for t in member.get('tags',[])) or len(member.get('note',''))>2000: raise HTTPException(422,'备注内容无效')
                db.execute('UPDATE route_members SET roles_json=?,tags_json=?,note=? WHERE route_id=? AND object_id=?',(json.dumps(member.get('roles',[])),json.dumps(member.get('tags',[])),member.get('note',''),rid,member['object_id']))
            db.execute('UPDATE routes SET name=?,difficulty=?,setter=?,notes=?,version=version+1,updated_at=? WHERE id=?',(payload.name.strip() or route['name'],payload.difficulty,payload.setter,payload.notes,now(),rid))
            snapshot=self.store._row_route(db,db.execute('SELECT * FROM routes WHERE id=?',(rid,)).fetchone())
            db.execute('INSERT INTO route_revisions VALUES(?,?,?,?,?)',(uuid.uuid4().hex,rid,snapshot['version'],self.store._json(self.store._snapshot(snapshot)),now()))
            if payload.request_id: db.execute('INSERT INTO photo_work_receipts VALUES(?,?,?)',('notes:'+rid,payload.request_id,fingerprint))
        return self.store.get_route(rid,owner)

    def _cancelled(self,sid):
        if self.stop.is_set(): return True
        with self.store.connect() as db:
            row=db.execute('SELECT status FROM photo_work_sessions WHERE id=?',(sid,)).fetchone()
        return not row or row[0]!='processing'

    def _progress(self,sid,stage,value):
        with self.store.transaction() as db:
            db.execute("UPDATE photo_work_sessions SET stage=?,progress=?,updated_at=? WHERE id=? AND status='processing'",(stage,value,now(),sid))

    def _seed(self,source,color):
        image=decode_photo(self.store.asset_path(source['original_asset']['filename']).read_bytes())
        hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
        candidates=sorted((obj for obj in source['objects'] if obj['color_group']==color),key=lambda o:o['source_bbox_px'][2]*o['source_bbox_px'][3],reverse=True)
        for obj in candidates:
            mask=np.zeros(image.shape[:2],np.uint8)
            cv2.fillPoly(mask,[np.array(obj['contour'],np.int32)],255)
            mask[((hsv[:,:,1]<80)|(hsv[:,:,2]<45))]=0
            if np.count_nonzero(mask)<50: continue
            _,distance,_,(x,y)=cv2.minMaxLoc(cv2.distanceTransform(mask,cv2.DIST_L2,5))
            if distance>=4: return (x/image.shape[1],y/image.shape[0])
        return None

    def process(self,sid):
        with self.store.connect() as db:
            row=db.execute('SELECT * FROM photo_work_sessions WHERE id=?',(sid,)).fetchone()
        if not row or row['status']!='processing': return
        row=dict(row); owner=row['owner']; board=self.store.get_board(row['board_id'],owner)
        source=self.store.get_board(row['source_id'],owner)
        path=self.store.asset_path(source['original_asset']['filename']); cancelled=lambda:self._cancelled(sid)
        if row['point_json']:
            point=json.loads(row['point_json'])
            px,py=point[0]*board['width'],point[1]*board['height']
            existing=next((obj for obj in board['objects'] if cv2.pointPolygonTest(np.array(obj['contour'],np.float32),(px,py),False)>=0),None)
            if existing:
                with self.store.transaction() as db:
                    if self._row(db,sid,owner)['status']!='processing': return
                    index=db.execute('SELECT COUNT(*) FROM route_members WHERE route_id=?',(row['route_id'],)).fetchone()[0]
                    db.execute('INSERT OR IGNORE INTO route_members VALUES(?,?,?,?,?,?)',(row['route_id'],existing['id'],'[]','[]','',index))
                    db.execute('UPDATE routes SET version=version+1,updated_at=? WHERE id=?',(now(),row['route_id']))
                    db.execute("UPDATE photo_work_sessions SET point_json=NULL,status='ready',stage='岩点已加入线路',version=version+1,updated_at=? WHERE id=?",(now(),sid))
                return
            image=decode_photo(path.read_bytes()); contour=segment_point(image,point)
            if cancelled(): return
            # Asset files are content addressed. Object, membership and completion
            # must commit together so a restart cannot duplicate a manual addition.
            x,y,right,bottom,cutout,mask=self.store._render_contour_assets(board,contour)
            with self.store.transaction() as db:
                if self._row(db,sid,owner)['status']!='processing': return
                if db.execute('SELECT version FROM board_versions WHERE id=?',(board['id'],)).fetchone()[0]!=board['version']:
                    raise ValueError('照片已有更新，请重试补点')
                oid=uuid.uuid4().hex; timestamp=now()
                db.execute('INSERT INTO board_objects VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (oid,board['id'],'hold',row['color'],self.store._json(contour),self.store._json([x,y,right-x,bottom-y]),
                     self.store._json(cutout),self.store._json(mask),0,0,0,1,.5,'needs_review',1,timestamp,timestamp))
                index=db.execute('SELECT COUNT(*) FROM route_members WHERE route_id=?',(row['route_id'],)).fetchone()[0]
                db.execute('INSERT INTO route_members VALUES(?,?,?,?,?,?)',(row['route_id'],oid,'[]','[]','',index))
                db.execute('UPDATE board_versions SET version=version+1,updated_at=? WHERE id=?',(timestamp,board['id']))
                db.execute('UPDATE routes SET version=version+1,updated_at=? WHERE id=?',(timestamp,row['route_id']))
                db.execute("UPDATE photo_work_sessions SET point_json=NULL,status='ready',stage='岩点已补加',version=version+1,updated_at=? WHERE id=?",(now(),sid))
            return
        if board['status']=='processing':
            seed=self._seed(source,row['color']) if row['color'] else None
            result=analyze_board_photo(path,self.store.root,cancelled=cancelled,deadline=time.monotonic()+180,
                seed=seed,color_group=row['color'],coarse_only=not bool(row['color']),
                calibration=source['calibration'] if row['color'] else None,
                progress=lambda stage,p:self._progress(sid,stage,min(p,70)))
            if row['color']: result['objects']=[obj for obj in result['objects'] if obj['color_group']==row['color']]
            if cancelled(): return
            self.store.set_analysis_result(board['id'],result)
            board=self.store.get_board(board['id'],owner)
        if not row['color']:
            if not board['objects']: raise ValueError('暂未找到线路颜色，请更换清晰照片')
            with self.store.transaction() as db:
                db.execute("UPDATE photo_work_sessions SET status='awaiting_color',stage='请选择一种线路颜色',progress=100,version=version+1,updated_at=? WHERE id=? AND status='processing'",(now(),sid))
            return
        if not board['objects']: raise ValueError('未找到该颜色的可靠岩点，请放弃后更换照片或颜色')
        self._progress(sid,'AI 正在复核线路',78)
        image=decode_photo(path.read_bytes())
        from core.photo_route_settings import get_visual_key
        ai=review_objects(image,board['objects'],self.store.asset_path,key=get_visual_key(self.store.root,owner))
        if cancelled(): return
        # Missing points require an actual local segmentation before inclusion.
        if ai['status']=='completed' and not row['route_id']:
            from core.photo_route_v2 import ObjectCreate
            for point in ai['missing']:
                if cancelled(): return
                px,py=point[0]*image.shape[1],point[1]*image.shape[0]
                if any(cv2.pointPolygonTest(np.array(o['contour'],np.float32),(px,py),False)>=0 for o in board['objects']): continue
                try:
                    contour=segment_point(image,point,color=row['color'])
                    board=self.store.add_object(board['id'],owner,ObjectCreate(expected_version=board['version'],color_group=row['color'],contour=contour))
                except ValueError: continue
        with self.store.transaction() as db:
            if self._row(db,sid,owner)['status']!='processing': return
            rid=row['route_id'] or 'work-'+sid
            if not row['route_id']:
                db.execute('INSERT INTO routes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL)',(rid,owner,board['id'],row['color']+'线路',row['color'],'','','','draft',1,now(),now()))
                for index,obj in enumerate(o for o in board['objects'] if o['id'] not in ai['rejected']):
                    db.execute('INSERT INTO route_members VALUES(?,?,?,?,?,?)',(rid,obj['id'],'[]','[]','',index))
            db.execute("UPDATE photo_work_sessions SET route_id=?,ai_json=?,status='ready',stage='线路已提取，进度已保存',progress=100,viewed=0,error=NULL,version=version+1,updated_at=? WHERE id=?",(rid,json.dumps(ai,ensure_ascii=False),now(),sid))

    def _run(self):
        while not self.stop.is_set():
            sid=self.queue.get()
            if sid is None: break
            try: self.process(sid)
            except Exception as exc:
                if self.stop.is_set(): continue
                message=str(exc) if isinstance(exc,ValueError) else '处理暂时失败，照片和已有结果已保留，请重试'
                with self.store.transaction() as db:
                    db.execute("UPDATE photo_work_sessions SET status='failed',error=?,stage='处理未完成',version=version+1,updated_at=? WHERE id=? AND status='processing'",(message[:300],now(),sid))


def workflow_router(workflow):
    router=APIRouter(prefix='/api/photo-routes/workflow')
    def owner(request): return request.state.pilot_user.username
    @router.get('/current')
    def current(request:Request): return workflow.current(owner(request))
    @router.get('/{sid}')
    def get(sid:str,request:Request): return workflow.get(sid,owner(request))
    @router.post('/upload')
    async def upload(request:Request,photo:UploadFile=File(...),request_id:str=Form(...)):
        from core.photo_route_processing import MAX_UPLOAD_BYTES
        data=await photo.read(MAX_UPLOAD_BYTES+1)
        try: return workflow.upload(owner(request),request_id,photo.filename or 'photo.jpg',data)
        except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    @router.post('/{sid}/color')
    def color(sid:str,change:Change,request:Request): return workflow.select(sid,owner(request),change)
    @router.post('/{sid}/{action}')
    def update(sid:str,action:str,change:Change,request:Request): return workflow.update(sid,owner(request),change,action)
    @router.put('/routes/{rid}/notes')
    def notes(rid:str,payload:Notes,request:Request): return workflow.notes(rid,owner(request),payload)
    return router
