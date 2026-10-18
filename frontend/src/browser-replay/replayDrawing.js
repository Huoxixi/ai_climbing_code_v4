import {drawHead} from '../services/replayHeadGeometry.js'
const links=[[5,6],[5,7],[7,9],[6,8],[8,10],[5,11],[6,12],[11,12],[11,13],[13,15],[12,14],[14,16]]

export function sampleAtTime(analysis,time){
  const fps=analysis.sample_fps,index=Math.round((time-analysis.start_seconds)*fps),sample=analysis.pose_samples[index]
  return sample?.observed&&Math.abs(sample.time_seconds-time)<=.6/fps?sample:null
}

export function drawSkeleton(ctx,sample,width,height){
  if(!sample?.observed)return
  const p=sample.kpts_xy,good=i=>sample.joint_eligibility?.[i]&&p?.[i]?.every(Number.isFinite),xy=i=>[p[i][0]*width,p[i][1]*height],scale=Math.max(1,width/700)
  ctx.save();ctx.lineCap='round'
  for(const [a,b]of links)if(good(a)&&good(b)){
    ctx.beginPath();ctx.moveTo(...xy(a));ctx.lineTo(...xy(b));ctx.lineWidth=5*scale;ctx.strokeStyle='#18241f';ctx.stroke();ctx.lineWidth=2.5*scale;ctx.strokeStyle='#f1d04b';ctx.stroke()
  }
  for(let i=5;i<17;i++)if(good(i)){ctx.beginPath();ctx.arc(...xy(i),3*scale,0,Math.PI*2);ctx.fillStyle='#fff4bf';ctx.fill()}
  drawHead(ctx,sample,width,height,p=>[p[0]*width,p[1]*height]);ctx.restore()
}
