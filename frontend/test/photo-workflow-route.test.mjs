import test from 'node:test'
import assert from 'node:assert/strict'
import { appPageFromHash, parsePhotoWorkflowHash, photoWorkflowHash, photoWorkflowScreen } from '../src/utils/photoWorkflowRoute.js'

const pages=['dashboard','photo-routes','settings']

test('nested photo links still resolve to the photo routes app page',()=>{
  assert.equal(appPageFromHash('#/photo-routes/library',pages),'photo-routes')
  assert.equal(appPageFromHash('#/photo-routes/route/route-1',pages),'photo-routes')
})

test('photo workflow screens have stable direct links',()=>{
  assert.deepEqual(parsePhotoWorkflowHash('#/photo-routes'),{screen:'home'})
  assert.deepEqual(parsePhotoWorkflowHash('#/photo-routes/confirm'),{screen:'confirm'})
  assert.deepEqual(parsePhotoWorkflowHash('#/photo-routes/library'),{screen:'library'})
  assert.deepEqual(parsePhotoWorkflowHash('#/photo-routes/route/route%201'),{screen:'route',routeId:'route 1'})
  assert.equal(photoWorkflowHash('route','route 1'),'#/photo-routes/route/route%201')
})

test('server workflow states map to replaceable page links',()=>{
  assert.equal(photoWorkflowScreen({pending:{}}),'confirm')
  assert.equal(photoWorkflowScreen({session:{status:'awaiting_color'}}),'select-color')
  assert.equal(photoWorkflowScreen({session:{status:'processing'}}),'processing')
  assert.equal(photoWorkflowScreen({session:{status:'failed'}}),'recovery')
  assert.equal(photoWorkflowScreen({session:{status:'ready'}}),'review')
})
