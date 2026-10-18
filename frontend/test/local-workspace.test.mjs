import test from 'node:test'
import assert from 'node:assert/strict'
import { isLocalWorkspace,localWorkspaceHash } from '../src/utils/localWorkspace.js'
import { appPageFromHash } from '../src/utils/photoWorkflowRoute.js'
test('local entry excludes setter deep links and keeps existing photo records',()=>{
  for(const host of ['localhost','127.0.0.1','[::1]'])assert.equal(isLocalWorkspace({location:{hostname:host}}),true)
  assert.equal(isLocalWorkspace({__AI_CLIMBING_DESKTOP__:true,location:{hostname:'desktop.invalid'}}),true)
  assert.equal(isLocalWorkspace({location:{hostname:'www.panyandingxian.cn'}}),false)
  for(const hash of ['','#/projects','#/dashboard','#/studio','#/boards','#/ai-lab'])assert.equal(localWorkspaceHash(hash),'#/photo-routes')
  assert.equal(localWorkspaceHash('#/my-records/route/saved-1'),'#/my-records/route/saved-1')
  assert.equal(localWorkspaceHash('#/account'),'#/settings')
  assert.equal(appPageFromHash('#/account',['photo-routes','settings']),'settings')
})
