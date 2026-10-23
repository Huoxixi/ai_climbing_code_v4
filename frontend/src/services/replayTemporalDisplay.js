export const TEMPORAL_DISPLAY_VERSION='bidirectional-image-pose-consensus-v3'
const joints=new Set([7,8,9,10,13,14,15,16,17,18,19,20,21,22])

// Absolute coordinates derived from real neighbouring images. Raw observations
// remain intact; these values are used by drawing only, never contact or scores.
export function temporalDisplaySample(sample) {
  const payload=sample?.temporal_display, whole=sample?.wholebody
  if(payload?.version!==TEMPORAL_DISPLAY_VERSION || payload.source_frame_id!==sample.source_frame_id
    || payload.coordinates!=='source_image_normalized' || payload.kind!=='image_supported_temporal_inference'
    || whole?.coordinates!=='source_image_normalized' || whole?.kpts_xy?.length!==133)return sample
  const body=sample.kpts_xy.map(p=>[...p]), points=whole.kpts_xy.map(p=>[...p]), applied=[]
  for(const update of payload.updates || []) {
    const j=update.joint,p=update.xy
    if(!Number.isInteger(j)||!joints.has(j)||p?.length!==2
      ||!p.every(v=>Number.isFinite(v)&&v>0&&v<1)||whole.joint_eligibility?.[j]!==true)continue
    points[j]=[...p];if(j<17)body[j]=[...p];applied.push(j)
  }
  return {...sample,kpts_xy:body,wholebody:{...whole,kpts_xy:points},
    display_basis:{version:TEMPORAL_DISPLAY_VERSION,inferred_joints:applied,contact_evidence:false}}
}
