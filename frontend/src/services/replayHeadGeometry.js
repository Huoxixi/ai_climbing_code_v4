// Artwork only. Never feed these points back into pose, contacts or statistics.
export const HEAD_RENDER_VERSION = 'circle-head-display-v2'
export function headGeometry(sample, width, height) {
  if(!sample || sample.observed===false || !(width>0&&height>0))return null
  const xy=sample.kpts_xy,scores=sample.kpts_score,flags=sample.joint_eligibility
  if(xy?.length!==17||scores?.length!==17)return null
  if(flags!=null&&(flags.length!==17||!flags.every(v=>typeof v==='boolean')))return null
  const point=i=>{
    const p=xy[i],s=scores[i]
    return Number.isFinite(s)&&(flags!=null?flags[i]&&s>0:s>=.5&&s<=1)
      &&p?.length===2&&p.every(v=>Number.isFinite(v)&&v>0&&v<1)?[p[0]*width,p[1]*height]:null
  }
  const shoulders=[point(5),point(6)],hips=[point(11),point(12)].filter(Boolean),face=[0,1,2,3,4].map(point).filter(Boolean)
  if(shoulders.some(p=>!p)||!hips.length||face.length<2)return null
  const mean=points=>[0,1].map(j=>points.reduce((s,p)=>s+p[j],0)/points.length)
  const dist=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1])
  const neck=mean(shoulders),hip=mean(hips),up=neck.map((v,j)=>v-hip[j]),torso=Math.hypot(...up)
  if(torso<4||dist(...shoulders)>torso*1.5)return null
  const spread=Math.max(...face.flatMap(a=>face.map(b=>dist(a,b))))
  if(spread<.025*torso||spread>.8*torso)return null
  const median=values=>{const a=values.sort((a,b)=>a-b);return(a[Math.floor((a.length-1)/2)]+a[Math.floor(a.length/2)])/2}
  const faceCenter=[0,1].map(j=>median(face.map(p=>p[j]))),axis=faceCenter.map((v,j)=>v-neck[j]),distance=Math.hypot(...axis)
  if(distance<.15*torso||distance>1.05*torso||axis.reduce((s,v,j)=>s+v*up[j],0)<-.15*distance*torso)return null
  const u=axis.map(v=>v/distance),center=faceCenter.map((v,j)=>v+u[j]*torso*.04)
  const rx=.22*torso,ry=rx
  const outline=Array.from({length:40},(_,i)=>{const t=i*Math.PI*2/40;return[
    (center[0]+rx*Math.cos(t)*(-u[1])+ry*Math.sin(t)*u[0])/width,
    (center[1]+rx*Math.cos(t)*u[0]+ry*Math.sin(t)*u[1])/height]})
  return{center:[center[0]/width,center[1]/height],neck:[neck[0]/width,neck[1]/height],outline}
}
export function projectHead(geometry,project,pixelRatio=1){
  if(!geometry)return null
  const center=project(geometry.center),neck=project(geometry.neck),outline=geometry.outline.map(project)
  if(!center||!neck||outline.some(p=>!p))return null
  const dist=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]),radius=outline.reduce((sum,p)=>sum+dist(p,center),0)/outline.length
  if(!(radius>0&&Number.isFinite(radius)))return null
  const factor=Math.max(1,Math.min(1.6,7/Math.max(.01,pixelRatio)/radius))
  const enlarged=Array.from({length:40},(_,i)=>[center[0]+radius*factor*Math.cos(i*Math.PI*2/40),center[1]+radius*factor*Math.sin(i*Math.PI*2/40)])
  const direction=Math.atan2(neck[1]-center[1],neck[0]-center[0])
  const angle=p=>{const a=Math.atan2(p[1]-center[1],p[0]-center[0])-direction;return Math.abs(Math.atan2(Math.sin(a),Math.cos(a)))}
  const edge=enlarged.reduce((best,p)=>angle(p)<angle(best)?p:best)
  return{outline:enlarged,neck:dist(center,neck)>dist(center,edge)?[edge,neck]:[]}
}
export function drawHead(ctx,sample,width,height,project){
  const cssWidth=ctx.canvas?.getBoundingClientRect?.().width
  const pixelRatio=cssWidth>0?cssWidth/ctx.canvas.width:1
  const art=projectHead(headGeometry(sample,width,height),project,pixelRatio)
  if(!art)return
  ctx.save()
  const path=()=>{ctx.beginPath();art.outline.forEach((p,i)=>ctx[i?'lineTo':'moveTo'](...p));ctx.closePath()}
  path();ctx.fillStyle='rgba(241,233,202,.08)';ctx.fill()
  ctx.lineJoin='round';ctx.lineCap='round'
  for(const [color,stroke]of [['#1c1d18',4],['#f1e9ca',2]]){
    ctx.strokeStyle=color;ctx.lineWidth=stroke/pixelRatio
    if(art.neck.length){ctx.beginPath();ctx.moveTo(...art.neck[0]);ctx.lineTo(...art.neck[1]);ctx.stroke()}
    path();ctx.stroke()
  }
  ctx.restore()
}
