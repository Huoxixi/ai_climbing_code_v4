import { centerOfMass } from './replayCenterOfMass.js'
import { drawHead, headGeometry, projectHead } from './replayHeadGeometry.js'
import { temporalDisplaySample } from './replayTemporalDisplay.js'
export const VISUAL_VERSION = 'registered-image-temporal-display-v15'

export function currentVisualization(saved, raw, trajectory) {
  if (saved?.version === VISUAL_VERSION) return saved
  // Derive only in memory. Old source data and exports remain immutable.
  if (raw?.pose_samples?.length && raw?.video?.width > 0 && raw?.video?.height > 0)
    return { ...saved, version:VISUAL_VERSION, pose_samples:registeredDisplayPoses(raw),
      center_of_mass_trajectory:trajectory || saved?.center_of_mass_trajectory }
  return saved || {pose_samples:[],center_of_mass_trajectory:trajectory}
}

const edges = [[5,6],[5,7],[7,9],[6,8],[8,10],[5,11],[6,12],[11,12],[11,13],[13,15],[12,14],[14,16]]
const colors = { left_hand:'#50c4eb',right_hand:'#ed5cc1',left_foot:'#ffb36a',right_foot:'#8fde57' }
const footIndices=[15,17,19,16,20,22]
const footEdges=[[0,1],[0,2],[3,4],[3,5]]
const sourcePoseCache=new WeakMap()
function sourcePoses(visualization){
  if(!visualization)return []
  if(!sourcePoseCache.has(visualization))sourcePoseCache.set(visualization,(visualization.pose_samples || []).map(p=>({...p,kpts_xy:p.source_kpts_xy,feet:p.source_feet,observed:p.observed && p.source_kpts_xy?.length===17})))
  return sourcePoseCache.get(visualization)
}
// Anatomical sides come from the saved observation, never screen ordering.
export function limbBadges(pose,width,height) {
  const radius=Math.max(7,Math.min(11,width/80)), badges=[]
  const head=projectHead(headGeometry(pose,width,height),p=>[p[0]*width,p[1]*height])
  const clearHead=p=>!head || p[0]<Math.min(...head.outline.map(q=>q[0]))-radius-3
    ||p[0]>Math.max(...head.outline.map(q=>q[0]))+radius+3
    ||p[1]<Math.min(...head.outline.map(q=>q[1]))-radius-3||p[1]>Math.max(...head.outline.map(q=>q[1]))+radius+3
  for(const [joint,text,side] of [[9,'左',-1],[10,'右',1],[15,'左',-1],[16,'右',1]]) {
    const xy=pose?.kpts_xy?.[joint]
    if(!(pose?.kpts_score?.[joint]>=.5) || xy?.length!==2 || !xy.every(v=>Number.isFinite(v)&&v>0&&v<1))continue
    const anchor=[xy[0]*width,xy[1]*height]
    const positions=[[side,0],[side,-1],[side,1],[-side,0],[-side,-1],[-side,1],[0,-2],[0,2]]
      .map(([dx,dy])=>[Math.max(radius+2,Math.min(width-radius-2,anchor[0]+dx*radius*1.8)),
        Math.max(radius+2,Math.min(height-radius-2,anchor[1]+dy*radius*1.8))])
    const clearBadges=p=>badges.every(b=>Math.hypot(p[0]-b.center[0],p[1]-b.center[1])>=radius*2+2)
    const center=positions.find(p=>clearHead(p)&&clearBadges(p)) || positions.find(clearHead) || positions.find(clearBadges) || positions[0]
    badges.push({joint,text,anchor,center,radius})
  }
  return badges
}
function registeredFeet(sample,m,width,height,valid,bodyPoints,bodyScores) {
  const whole=sample.wholebody
  if(!valid || whole?.schema!=='coco-wholebody-133' || whole.kpts_xy?.length!==133 || whole.kpts_score?.length!==133)return null
  if(!['source_image_normalized','wall_reference_image_normalized'].includes(whole.coordinates))return null
  const points=[],scores=[]
  for(const joint of footIndices){
    const xy=whole.kpts_xy[joint],score=whole.kpts_score[joint]
    let p=null
    const hasFlags=whole.joint_eligibility!=null
    const eligible=hasFlags ? whole.joint_eligibility?.length===133 && whole.joint_eligibility.every(v=>typeof v==='boolean') && whole.joint_eligibility[joint]===true && score>0 : score>=.5&&score<=1
    if(xy?.length===2 && xy.every(v=>Number.isFinite(v)&&v>0&&v<1) && Number.isFinite(score)&&eligible){
      const h=whole.coordinates==='source_image_normalized'?m.map(r=>r[0]*xy[0]*width+r[1]*xy[1]*height+r[2]):[xy[0]*width,xy[1]*height,1]
      if(h.every(Number.isFinite)&&Math.abs(h[2])>1e-6)p=[h[0]/h[2]/width,h[1]/h[2]/height]
    }
    const okay=p?.every(v=>Number.isFinite(v)&&v>0&&v<1)
    points.push(okay?p:[0,0]);scores.push(okay?(hasFlags?1:score):0)
  }
  for(const [i,joint] of [[0,15],[3,16]]){points[i]=bodyPoints[joint];scores[i]=bodyScores[joint]}
  return {kpts_xy:points,kpts_score:scores,basis:'model_observation_display_only'}
}
function interpolateFeet(a,b,alpha){
  if(!a||!b)return null
  const scores=a.kpts_score.map((s,i)=>Math.min(s,b.kpts_score[i]))
  return {kpts_xy:a.kpts_xy.map((p,i)=>scores[i]>=.5?p.map((v,j)=>v*(1-alpha)+b.kpts_xy[i][j]*alpha):[0,0]),
    kpts_score:scores,basis:'display_interpolation'}
}
export function displayedHoldColors(contacts, index, finished = false) {
  const active = new Map(), used = new Map()
  for(const c of contacts || []) {
    if(!colors[c.limb] || !Number.isFinite(c.start_source_frame) || !Number.isFinite(c.end_source_frame)
      || c.start_source_frame<0 || c.end_source_frame<c.start_source_frame || c.start_source_frame>index)continue
    used.set(String(c.hold_id),'#f1d04b')
    if(index<=c.end_source_frame && (!active.has(c.limb) || active.get(c.limb).start_source_frame<c.start_source_frame))active.set(c.limb,c)
  }
  return finished ? used : new Map([...active.values()].map(c=>[String(c.hold_id),colors[c.limb]]))
}
export function analysisFrame(video, selection = null) {
  if (!(video?.width > 0 && video?.height > 0)) return null
  const { width, height } = video
  if(selection) {
    const scene = selection.show_human || selection.show_skeleton
    const pane = selection.show_diagram ? [scene ? width : 0,0,width,height] : null
    return {width:width*(Number(scene)+Number(selection.show_diagram)),height,
      video:scene?[0,0,width,height]:null,panel:pane,map:pane,source:video}
  }
  return { width:width*2, height, video:[0,0,width,height], panel:[width,0,width,height], map:[width,0,width,height], source:video }
}

export function registeredDisplayPoses(result) {
  const {width,height} = result?.video || {}
  if (!(width>0 && height>0)) return []
  return (result?.pose_samples || []).map(sample => {
    sample=temporalDisplaySample(sample)
    const m=sample.wall_reference_transform, diagnostics=sample.wall_alignment_diagnostics || sample.motion_registration || {}
    const determinant=m?.length===3 && m.every(r=>r?.length===3) ? m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])-m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])+m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]) : 0
    const valid=sample.observed && ['aligned','reference'].includes(sample.wall_alignment)
      && Number.isFinite(determinant) && Math.abs(m[2][2])>1e-12 && Math.abs(determinant / m[2][2]**3)>=1e-9
      && m?.length===3 && m.every(r=>r?.length===3 && r.every(Number.isFinite))
      && sample.kpts_xy?.length===17 && sample.kpts_score?.length===17
      && (diagnostics.median_error_px == null || Number.isFinite(diagnostics.median_error_px) && diagnostics.median_error_px<=3)
      && (diagnostics.inliers == null || Number.isFinite(diagnostics.inliers) && diagnostics.inliers>=12)
    const points=[], scores=[]
    for(let i=0;i<17;i++) {
      const xy=sample.kpts_xy?.[i], score=sample.kpts_score?.[i]
      const hasFlags=sample.joint_eligibility!=null
      const eligible=hasFlags ? sample.joint_eligibility?.length===17 && sample.joint_eligibility.every(v=>typeof v==='boolean') && sample.joint_eligibility[i]===true && score>0 : score>=.5 && score<=1
      const p=valid && xy?.length===2 && xy.every(v=>Number.isFinite(v)&&v>0&&v<1) && Number.isFinite(score) && eligible
        ? m.map(r=>r[0]*xy[0]*width+r[1]*xy[1]*height+r[2]) : null
      const okay=p?.every(Number.isFinite) && Math.abs(p[2])>1e-6
        && [p[0]/p[2]/width,p[1]/p[2]/height].every(v=>v>0&&v<1)
      points.push(okay ? [p[0]/p[2]/width,p[1]/p[2]/height] : [0,0]); scores.push(okay?(hasFlags?1:score):0)
    }
    return {source_frame_id:sample.source_frame_id,time_seconds:sample.time_seconds,observed:Boolean(valid),kpts_xy:points,kpts_score:scores,
      ...(sample.display_basis?{display_basis:sample.display_basis}:{}),
      source_kpts_xy:sample.kpts_xy,
      source_feet:registeredFeet(sample,[[1,0,0],[0,1,0],[0,0,1]],width,height,valid,sample.kpts_xy,scores),
      feet:registeredFeet(sample,m,width,height,valid,points,scores)}
  }).sort((a,b)=>a.source_frame_id-b.source_frame_id)
}

export function displayPoseAt(samples, frame, fps) {
  if (!samples?.length || !(fps>0)) return null
  let low=0,high=samples.length-1
  while(low<=high) {const mid=(low+high)>>1;if(samples[mid].source_frame_id<frame)low=mid+1;else high=mid-1}
  const b=samples[low],a=samples[low-1]
  if(b?.source_frame_id===frame)return b.observed?b:null
  // Keep interpolation inside adjacent observations; never bridge a missing pose.
  if(!a?.observed || !b?.observed || (b.source_frame_id-a.source_frame_id)/fps>.6)return null
  const alpha=(frame-a.source_frame_id)/(b.source_frame_id-a.source_frame_id)
  return {observed:true,kpts_xy:a.kpts_xy.map((p,i)=>p.map((v,j)=>v*(1-alpha)+b.kpts_xy[i][j]*alpha)),
    feet:interpolateFeet(a.feet,b.feet,alpha),render_mode:'interpolated',
    kpts_score:a.kpts_score.map((s,i)=>Math.min(s,b.kpts_score[i]))}
}

export function drawAnalysisView(ctx, video, frame, holds, contacts, visualization, time, selection = null, background = null, backgroundInfo = null) {
  const f=frame, fps=f.source.fps || 30, index=Math.floor(time*fps+1e-6)
  ctx.fillStyle='#0e100f';ctx.fillRect(0,0,f.width,f.height)
  // All image pixels on the left come directly from the original video.
  if(!selection || selection.show_human) {
    if(f.video)ctx.drawImage(video,0,0,video.videoWidth,video.videoHeight,...f.video)
  } else if(selection.show_skeleton && background && f.video) {
    ctx.drawImage(background,...f.video)
  }
  if(selection?.show_skeleton && f.video) {
    const samples=selection.show_human ? sourcePoses(visualization) : visualization?.pose_samples
    const pose=displayPoseAt(samples,index,fps)
    const matrix=selection.show_human ? [[1,0,0],[0,1,0],[0,0,1]] : backgroundInfo?.reference_to_background
    if(pose && matrix?.length===3 && (selection.show_human || background)) {
      const point=(xy,inside=true)=>{
        const p=matrix.map(r=>r[0]*xy[0]*f.source.width+r[1]*xy[1]*f.source.height+r[2])
        if(!p.every(Number.isFinite)||Math.abs(p[2])<1e-8)return null
        const x=p[0]/p[2]/f.source.width,y=p[1]/p[2]/f.source.height
        return !inside||x>0&&x<1&&y>0&&y<1?[f.video[0]+x*f.video[2],f.video[1]+y*f.video[3]]:null
      }
      ctx.save();ctx.beginPath();ctx.rect(...f.video);ctx.clip()
      drawHead(ctx,pose,f.source.width,f.source.height,xy=>point(xy,false))
      ctx.strokeStyle='#e8de90';ctx.lineWidth=Math.max(2,Math.round(Math.min(f.video[2],f.video[3])/220))
      const bones=(xy,scores,links)=>{for(const[a,b]of links)if(Math.min(scores[a],scores[b])>=.5){const pa=point(xy[a]),pb=point(xy[b]);if(pa&&pb){ctx.beginPath();ctx.moveTo(...pa);ctx.lineTo(...pb);ctx.stroke()}}}
      bones(pose.kpts_xy,pose.kpts_score,edges)
      if(pose.feet)bones(pose.feet.kpts_xy,pose.feet.kpts_score,footEdges)
      ctx.restore()
    }
  }
  if(!f.panel)return
  ctx.save();ctx.beginPath();ctx.rect(...f.panel);ctx.clip()
  const project=p=>[f.map[0]+p[0]*f.map[2],f.map[1]+p[1]*f.map[3]]
  const line=points=>{ctx.beginPath();points.forEach((p,i)=>ctx[i?'lineTo':'moveTo'](...project(p)))}
  const finished=video.ended || f.source.frame_count>0 && index>=f.source.frame_count-1
  const occupied=displayedHoldColors(contacts,index,finished)
  for(const hold of holds || []) {
    if(!hold.polygon?.length || hold.polygon.length<3)continue
    line(hold.polygon);ctx.closePath();ctx.strokeStyle=occupied.get(String(hold.id))||'#818780';ctx.lineWidth=Math.max(2,f.source.width/240)
    if(occupied.has(String(hold.id))){ctx.fillStyle=ctx.strokeStyle;ctx.fill()}ctx.stroke()
  }
  ctx.strokeStyle='#75e7ee';ctx.lineWidth=Math.max(2,f.source.width/240)
  for(const run of visualization?.center_of_mass_trajectory?.segments || []) {
    const shown=run.filter(p=>p.time_seconds<=time && p.xy?.length===2 && p.xy.every(Number.isFinite))
    if(shown.length>=2){line(shown.map(p=>p.xy));ctx.stroke()}
  }
  const pose=displayPoseAt(visualization?.pose_samples,index,fps)
  if(pose) {
    drawHead(ctx,pose,f.source.width,f.source.height,project)
    ctx.strokeStyle='#e8de90';ctx.lineWidth=Math.max(2,f.source.width/220)
    for(const [a,b]of edges)if(Math.min(pose.kpts_score[a],pose.kpts_score[b])>=.5){line([pose.kpts_xy[a],pose.kpts_xy[b]]);ctx.stroke()}
    if(pose.feet)for(const [a,b]of footEdges)if(Math.min(pose.feet.kpts_score[a],pose.feet.kpts_score[b])>=.5){line([pose.feet.kpts_xy[a],pose.feet.kpts_xy[b]]);ctx.stroke()}
    const center=centerOfMass(pose)
    if(center){const p=project(center);ctx.beginPath();ctx.arc(...p,Math.max(4,f.source.width/110),0,Math.PI*2);ctx.fillStyle='#fff';ctx.fill()}
    const badges=limbBadges(pose,f.map[2],f.map[3])
    ctx.save();ctx.font=`500 ${Math.round(badges[0]?.radius*1.35 || 10)}px "Microsoft YaHei", sans-serif`
    ctx.textAlign='center';ctx.textBaseline='middle'
    for(const badge of badges) {
      const [x,y]=badge.center.map((v,i)=>v+f.map[i]),[ax,ay]=badge.anchor.map((v,i)=>v+f.map[i])
      ctx.strokeStyle='#ddd9b9';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(ax,ay);ctx.lineTo(x,y);ctx.stroke()
      ctx.beginPath();ctx.arc(x,y,badge.radius,0,Math.PI*2);ctx.fillStyle='rgba(14,16,15,.82)';ctx.fill();ctx.stroke()
      ctx.fillStyle='#eee9d4';ctx.fillText(badge.text,x,y)
    }
    ctx.restore()
  }
  ctx.restore()
}
