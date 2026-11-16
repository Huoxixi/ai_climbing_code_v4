import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,rmSync,copyFileSync,mkdirSync,symlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createApp} from './candidate/server.mjs';
import {DatabaseSync} from 'node:sqlite';
import {scryptSync} from 'node:crypto';
import {spawn} from 'node:child_process';

test('production CLI starts through the current release directory symlink',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'study-symlink-')),release=join(dir,'release'),current=join(dir,'current');mkdirSync(release);
 copyFileSync(new URL('./candidate/server.mjs',import.meta.url),join(release,'server.mjs'));symlinkSync(release,current,process.platform==='win32'?'junction':'dir');
 const child=spawn(process.execPath,[join(current,'server.mjs')],{env:{...process.env,PORT:'0',PUBLIC_ORIGIN:'',DATA_DIR:join(dir,'data')},stdio:['ignore','pipe','pipe']});let stderr='';child.stderr.on('data',chunk=>stderr+=chunk);
 try{
  const origin=await new Promise((resolve,reject)=>{let output='';const timeout=setTimeout(()=>reject(new Error('CLI did not listen: '+stderr)),8000);child.once('error',err=>{clearTimeout(timeout);reject(err);});child.once('exit',code=>{clearTimeout(timeout);reject(new Error('CLI exited before listening: '+code+' '+stderr));});child.stdout.on('data',chunk=>{output+=chunk;const match=output.match(/http:\/\/127\.0\.0\.1:(\d+)\/study\//);if(match){clearTimeout(timeout);resolve('http://127.0.0.1:'+match[1]);}});});
  assert.equal((await(await fetch(origin+'/study/api/health')).json()).ok,true);
 }finally{if(child.exitCode===null){const done=new Promise(resolve=>child.once('exit',resolve));child.kill();await done;}rmSync(dir,{recursive:true,force:true});}
});

test('legacy five-column account survives nickname migration',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'study-legacy-')),db=new DatabaseSync(join(dir,'study.sqlite')),password='legacy private password',salt='legacy-fixture-salt';
 db.exec('CREATE TABLE users(id TEXT PRIMARY KEY,username TEXT UNIQUE NOT NULL,password TEXT NOT NULL,role TEXT NOT NULL,created INTEGER NOT NULL)');
 const encoded=salt+':'+scryptSync(password,salt,64,{N:16384,r:8,p:1,maxmem:64*1024*1024}).toString('hex');
 db.prepare('INSERT INTO users VALUES(?,?,?,?,?)').run('legacy-user','legacy_test',encoded,'owner',123);db.close();
 const app=createApp({port:0,dataDir:dir});await new Promise(r=>app.server.listen(0,'127.0.0.1',r));
 try{
  const response=await fetch(app.origin+'/study/api/login',{method:'POST',headers:{Origin:app.origin,'Content-Type':'application/json','X-Study-Request':'1'},body:JSON.stringify({username:'legacy_test',password})});
  assert.equal(response.status,200);const result=await response.json();assert.equal(result.user.displayName,'legacy_test');assert.equal(result.user.owner,true);
  const saved=app.db.prepare('SELECT * FROM users WHERE id=?').get('legacy-user');assert.equal(saved.password,encoded);assert.equal(saved.created,123);assert.equal(saved.display_name,'');
 }finally{await app.close();rmSync(dir,{recursive:true,force:true});}
});

test('friend accounts, ownership, progress, sharing, backup and restart',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'study-friends-api-')),origin='http://study.test';let app=createApp({port:0,origin,dataDir:dir});await new Promise(r=>app.server.listen(0,'127.0.0.1',r));let base='http://127.0.0.1:'+app.server.address().port;
 const call=async(path,{method='GET',value,cookie,originHeader=origin}={})=>{const r=await fetch(base+'/study/api/'+path,{method,headers:{Origin:originHeader,'Content-Type':'application/json','X-Study-Request':'1',...(cookie?{Cookie:cookie}:{})},...(value===undefined?{}:{body:JSON.stringify(value)})});return {status:r.status,data:await r.json(),cookie:r.headers.get('set-cookie')?.split(';')[0],setCookie:r.headers.get('set-cookie')};};
 try{
 assert.equal((await call('documents')).status,401);assert.equal((await call('login',{method:'POST',value:{},originHeader:'http://evil.test'})).status,403);
 const password='test password with 25 chars';
 for(const username of ['a','a'.repeat(33)])assert.equal((await call('register',{method:'POST',value:{username,password:'12345678'}})).status,400);
 assert.equal((await call('register',{method:'POST',value:{username:'ab',password:'1234567'}})).status,400);
 const short=await call('register',{method:'POST',value:{username:'ab',password:'12345678'}});assert.equal(short.status,200);
 assert.equal((await call('password',{method:'POST',cookie:short.cookie,value:{current:'12345678',password:'7654321'}})).status,400);
 assert.equal((await call('password',{method:'POST',cookie:short.cookie,value:{current:'12345678',password:'87654321'}})).status,200);
 assert.equal((await call('login',{method:'POST',value:{username:'ab',password:'87654321'}})).status,200);
 const longest='z'.repeat(32);assert.equal((await call('register',{method:'POST',value:{username:longest,password:'12345678'}})).status,200);
 assert.equal((await call('login',{method:'POST',value:{username:longest+'z',password:'12345678'}})).status,400);
 let owner=await call('register',{method:'POST',value:{username:'owner_test',password,displayName:'测试账户'}});assert.equal(owner.status,200);assert.equal(owner.data.user.owner,false);assert.equal(owner.data.user.displayName,'测试账户');assert.match(owner.setCookie,/HttpOnly/);assert.match(owner.setCookie,/Path=\/study\//);const a=owner.cookie;
 assert.equal((await call('register',{method:'POST',value:{username:'owner_test',password}})).status,409);
 const user=await call('register',{method:'POST',value:{username:'friend_test',password}});assert.equal(user.status,200);assert.equal(user.data.user.owner,false);const b=user.cookie;
 assert.equal((await call('invites',{method:'POST',cookie:b,value:{}})).status,404);
 const html='<html><title>测试资料</title><body><button>试一试</button><script>localStorage.setItem("hello","world")</script></body></html>';
 const first=await call('documents',{method:'POST',cookie:a,value:{html,filename:'cards.html',course:'测试课'}});assert.equal(first.status,201);const did=first.data.document.id;
 assert.equal((await call('documents/'+did+'/content',{cookie:b})).status,404);assert.equal((await call('documents/'+did,{method:'DELETE',cookie:b})).status,404);
 assert.equal((await call('documents',{cookie:b})).data.documents.length,0);
 assert.equal((await call('documents',{method:'POST',cookie:a,value:{html,filename:'cards.html',course:'测试课'}})).data.duplicate,true);
 assert.equal((await call('documents/'+did+'/storage',{method:'PUT',cookie:a,value:{revision:0,storage:{hello:'我的学习记录'}}})).status,200);
 assert.equal((await call('documents/'+did+'/storage',{method:'PUT',cookie:a,value:{revision:0,storage:{hello:'过期设备'}}})).status,409);
 assert.equal((await call('documents/'+did+'/content',{cookie:a})).data.storage.hello,'我的学习记录');
 assert.equal((await call('documents/'+did+'/storage',{method:'PUT',cookie:a,value:{revision:1,storage:{bad:3}}})).status,400);
 const backup=(await call('documents/'+did+'/backup',{cookie:a})).data;assert.equal(backup.document.storage.hello,'我的学习记录');assert.equal(backup.document.html,html);
 const shared=(await call('documents/'+did+'/share',{method:'POST',cookie:a,value:{}})).data.url.split('#share/')[1];
 assert.equal((await call('shares/'+shared)).data.title,'测试资料');
 const claimed=await call('shares/'+shared+'/claim',{method:'POST',cookie:b,value:{}});assert.equal(claimed.status,201);const bdid=claimed.data.document.id;assert.deepEqual((await call('documents/'+bdid+'/content',{cookie:b})).data.storage,{});
 assert.equal((await call('shares/'+shared+'/claim',{method:'POST',cookie:b,value:{}})).data.document.id,bdid);
 await call('documents/'+did+'/share',{method:'DELETE',cookie:a});assert.equal((await call('shares/'+shared)).status,404);assert.equal((await call('documents/'+bdid+'/content',{cookie:b})).status,200);
 await call('documents/'+did,{method:'PUT',cookie:a,value:{html:html+'<!--updated-->'}});assert.equal((await call('documents/'+did+'/content',{cookie:a})).data.storage.hello,'我的学习记录');
 assert.equal((await call('password',{method:'POST',cookie:b,value:{current:'wrong password',password:'replacement password'}})).status,403);
 assert.equal((await call('password',{method:'POST',cookie:b,value:{current:password,password:'replacement password'}})).status,200);
 assert.equal((await call('documents',{cookie:b})).status,401);
 await app.close();app=createApp({port:0,origin,dataDir:dir});await new Promise(r=>app.server.listen(0,'127.0.0.1',r));base='http://127.0.0.1:'+app.server.address().port;
 const again=await call('login',{method:'POST',value:{username:'friend_test',password:'replacement password'}});assert.equal(again.status,200);assert.equal((await call('documents',{cookie:again.cookie})).data.documents.length,1);
 await call('logout',{method:'POST',cookie:again.cookie,value:{}});assert.equal((await call('documents',{cookie:again.cookie})).status,401);
 }finally{await app.close();rmSync(dir,{recursive:true,force:true});}
});
