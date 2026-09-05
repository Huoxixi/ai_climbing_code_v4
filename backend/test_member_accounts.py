import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
import main
from core.member_accounts import MemberAccounts
from core.pilot_access import PilotAccessError
from core.member_storage import member


class MemberTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.users = self.root / 'legacy.json'
        self.users.write_text(json.dumps({'users': {'ma-trial': {'password_hash': ''}, 'owner': {}}}))
        self.manager = MemberAccounts(database=self.root / 'accounts.sqlite3', users_file=str(self.users), audit_file=str(self.root / 'audit.jsonl'))
        self.public = self.root / 'saved_boards.json'
        self.public.write_text(json.dumps([{'saved_id':'shared', 'route_name':'公共岩板', 'placed_holds':[]}]))
        self.mapping = self.root / 'holds_mapping.json'
        self.mapping.write_text(json.dumps({'Jug': {'common': '/images/shared.png'}}))
        self.patches = [patch.object(main, 'pilot_access', self.manager), patch.object(main, 'PILOT_AUTH_ENABLED', True),
                        patch.object(main, 'PILOT_COOKIE_SECURE', True), patch.object(main, 'PILOT_QUICK_LOGIN_ENABLED', False),
                        patch.object(main, 'SAVED_BOARDS_FILE', str(self.public)), patch.object(main, 'HOLDS_MAPPING_FILE', str(self.mapping)),
                        patch.object(main, 'HOLDS_VECTORS_FILE', str(self.root/'holds_vectors.json')),
                        patch.object(main, 'HOLDS_METADATA_FILE', str(self.root/'hold_assets_meta.json'))]
        self.patches += [patch.object(main, 'HOLDS_IMAGES_DIR', str(self.root/'images')),
                         patch.object(main, 'PROCESSED_HOLDS_IMAGES_DIR', str(self.root/'processed'))]
        for p in self.patches: p.start()
        self.a = TestClient(main.app, base_url='https://testserver')
        self.b = TestClient(main.app, base_url='https://testserver')

    def tearDown(self):
        self.a.close(); self.b.close()
        for p in reversed(self.patches): p.stop()
        member.set(None)
        self.tmp.cleanup()

    def register(self, client, username):
        response = client.post('/api/auth/register', json={'username':username, 'display_name':username,
             'password':'test-password-long', 'invite_code':self.manager.create_invite()})
        self.assertEqual(response.status_code, 201, response.text)
        return response

    def test_registration_login_logout_and_legacy_disabled(self):
        self.assertTrue(self.a.get('/api/auth/session').json()['registration_enabled'])
        response = self.register(self.a, 'alice')
        self.assertTrue(self.a.get('/api/auth/session').json()['registration_enabled'])
        self.assertIn('HttpOnly', response.headers['set-cookie'])
        self.assertIn('Secure', response.headers['set-cookie'])
        self.a.post('/api/auth/logout')
        self.assertEqual(self.a.get('/api/my-boards').status_code, 401)
        self.assertEqual(self.a.post('/api/auth/login', json={'username':'alice','password':'test-password-long'}).status_code, 200)
        self.assertEqual(self.a.post('/api/auth/login', json={'username':'ma-trial','password':'old-password'}).status_code, 401)
        stored = self.manager._load_users()['alice']['password_hash']
        self.assertNotIn('test-password-long', stored)
        self.assertEqual(self.users.read_text(), json.dumps({'users': {'ma-trial': {'password_hash': ''}, 'owner': {}}}))

    def test_invite_single_use_atomic_and_expiry(self):
        invite = self.manager.create_invite()
        def attempt(name):
            try:
                return self.manager.register(name,name,'test-password-long',invite,name)[1].username
            except PilotAccessError: return None
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(attempt, ['alice','bobby']))
        self.assertEqual(sum(r is not None for r in results),1)
        invite = self.manager.create_invite()
        with self.manager.connect() as db: db.execute('UPDATE invites SET expires_at=0')
        with self.assertRaises(PilotAccessError): self.manager.register('carol','Carol','test-password-long',invite,'other')

    def test_public_read_only_private_isolation_and_copy(self):
        original = self.public.read_bytes()
        self.register(self.a,'alice'); self.register(self.b,'bobby')
        shared = self.a.get('/api/my-boards').json()[0]
        self.assertEqual(shared['visibility'],'public')
        self.assertEqual(self.a.put('/api/my-boards/shared',json={'route_name':'overwritten'}).status_code,403)
        self.assertEqual(self.a.delete('/api/my-boards/shared').status_code,403)
        created = self.a.post('/api/save-board',json={**shared,'route_name':'个人副本'}).json()
        self.assertEqual(created['visibility'],'private')
        self.assertEqual(len(self.a.get('/api/my-boards').json()),2)
        self.assertEqual(len(self.b.get('/api/my-boards').json()),1)
        self.assertEqual(self.b.put('/api/my-boards/'+created['saved_id'],json={'route_name':'steal'}).status_code,404)
        self.assertEqual(self.a.put('/api/my-boards/'+created['saved_id'],json={'route_name':'mine'}).status_code,200)
        self.assertEqual(self.public.read_bytes(),original)
        self.assertEqual(self.a.delete('/api/holds/Jug/common').status_code,403)
        self.assertTrue(self.a.get('/api/pilot/edit-lease').json()['owned_by_me'])
        self.assertTrue(self.b.get('/api/pilot/edit-lease').json()['owned_by_me'])

    def test_private_images_and_jobs_are_protected(self):
        self.register(self.a,'alice'); self.register(self.b,'bobby')
        import hashlib
        key='u-'+hashlib.sha256(b'alice').hexdigest()
        self.assertEqual(self.b.get('/images/processed/'+key+'/picture.png').status_code,404)
        main.task_owners['private-task']='alice'
        main.active_tasks['private-task']={'task_id':'private-task','status':'completed','result':{'secret':'private'}}
        try:
            self.assertEqual(self.a.get('/api/result/private-task').status_code,200)
            self.assertEqual(self.b.get('/api/result/private-task').status_code,404)
            self.assertEqual(self.b.post('/api/cancel/private-task').status_code,404)
        finally:
            main.task_owners.pop('private-task'); main.active_tasks.pop('private-task')

    def test_invalid_registration_does_not_echo_secrets(self):
        response=self.a.post('/api/auth/register',json={'username':3,'password':'do-not-echo-this-secret'})
        self.assertEqual(response.status_code,422)
        self.assertNotIn('do-not-echo',response.text)
        for i in range(5):
            self.a.post('/api/auth/register',json={'username':'alice','display_name':'Alice','password':'long-test-password','invite_code':'bad'})
        self.assertEqual(self.a.post('/api/auth/register',json={'username':'alice','display_name':'Alice','password':'long-test-password','invite_code':'bad'}).status_code,429)

    def test_private_hold_upload_and_origin_protection(self):
        import cv2
        import numpy as np
        self.register(self.a,'alice'); self.register(self.b,'bobby')
        picture=np.full((100,100,3),255,dtype=np.uint8)
        cv2.circle(picture,(50,50),25,(20,100,200),-1)
        encoded=cv2.imencode('.png',picture)[1].tobytes()
        response=self.a.post('/api/holds/upload',data={'hold_type':'Jug','variant':'personal'},files={'file':('hold.png',encoded,'image/png')})
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn('/u-',response.json()['image_path'])
        self.assertEqual(len(self.a.get('/api/holds/assets').json()),2)
        self.assertEqual(len(self.b.get('/api/holds/assets').json()),1)
        self.assertEqual(self.a.get('/api/holds/assets').headers['cache-control'],'no-store')
        self.assertEqual(self.b.get(response.json()['image_path']).status_code,404)
        self.assertEqual(self.a.post('/api/auth/register',headers={'Origin':'https://unrelated.example'},json={}).status_code,403)

if __name__ == '__main__': unittest.main()
