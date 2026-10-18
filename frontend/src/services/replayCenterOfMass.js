// Matches replay_center_of_mass.py. 2D estimate with head/wrist/ankle proxies.
export const massModelVersion = 'projected-segment-mass-mean-v1'
const parameters = {head:[.0681],trunk:[.43015,.5051],upper_arm:[.0263,.5763],forearm:[.015,.45665],
  hand:[.00585],thigh:[.1447,.38535],shank:[.0457,.44375],foot:[.0133]}
export function centerOfMass(sample) {
  if (!sample || sample.observed === false) return null
  const points=sample.kpts_xy || [],scores=sample.kpts_score || []
  const valid=i=>points[i]?.length===2 && points[i].every(v=>Number.isFinite(v)&&v>0&&v<1)
    && Number.isFinite(scores[i]) && scores[i]>=.5 && scores[i]<=1
  if (!Array.from({length:12},(_,i)=>i+5).every(valid)) return null
  const head=[0,3,4].filter(valid)
  if(!head.length)return null
  const mean=ids=>[0,1].map(axis=>ids.reduce((s,i)=>s+points[i][axis],0)/ids.length)
  const blend=(a,b,r)=>a.map((v,axis)=>v+r*(b[axis]-v))
  const segments=[['head',mean(head)],['trunk',blend(mean([5,6]),mean([11,12]),parameters.trunk[1])]]
  for(const [shoulder,elbow,wrist,hip,knee,ankle] of [[5,7,9,11,13,15],[6,8,10,12,14,16]]) {
    for(const [name,a,b] of [['upper_arm',shoulder,elbow],['forearm',elbow,wrist],['thigh',hip,knee],['shank',knee,ankle]])
      segments.push([name,blend(points[a],points[b],parameters[name][1])])
    segments.push(['hand',points[wrist]],['foot',points[ankle]])
  }
  const total=segments.reduce((s,[name])=>s+parameters[name][0],0)
  return [0,1].map(axis=>segments.reduce((s,[name,xy])=>s+parameters[name][0]*xy[axis],0)/total)
}
