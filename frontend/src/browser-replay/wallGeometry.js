export const WALL_SCENE_VERSION='browser-empty-wall-v1'
export function projectWallPoint(point,matrix){
  if(!point?.every(Number.isFinite)||matrix?.length!==9||!matrix.every(Number.isFinite))return null
  const [x,y]=point,d=matrix[6]*x+matrix[7]*y+matrix[8]
  if(Math.abs(d)<1e-6)return null
  const p=[(matrix[0]*x+matrix[1]*y+matrix[2])/d,(matrix[3]*x+matrix[4]*y+matrix[5])/d]
  return p.every(Number.isFinite)?p:null
}
export function wallTransformAt(analysis,sample){
  const scene=analysis.wall_scene
  if(scene?.version!==WALL_SCENE_VERSION||scene.status!=='ready'||!sample)return null
  return scene.registrations?.find(r=>Math.abs(r.time_seconds-sample.time_seconds)<1e-6)?.matrix||null
}
export function validWallScene(scene){
  return scene?.version===WALL_SCENE_VERSION&&scene.status==='ready'&&scene.image instanceof Blob&&scene.image.size>0&&Array.isArray(scene.registrations)
}
