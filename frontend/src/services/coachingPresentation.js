export function reportFocus(report) {
  const first = report?.improvements?.[0]
  if (report?.result_status === 'try' && first?.adjustment && first?.verification && first?.independent_review?.status === 'verified') {
    return { kind: 'adjustment', item: first, text: first.adjustment, reason: first.goal_relation, verification: first.verification }
  }
  const next = report?.next_attempt
  const item = report?.observations?.find(row => row.id === next?.observation_id)
  if (report?.result_status === 'review' && next?.kind === 'review' && next.reason && item?.evidence?.length && Number.isFinite(item.start_seconds)) {
    return { kind: 'review', item, text: item.title, reason: next.reason, verification: next.verification }
  }
  return null
}

const reasonLabels = {
  no_approved_knowledge: '没有通过审核与验收的适用知识，本次不能生成技术建议。',
  no_approved_claims: '没有通过审核与验收的适用知识，本次不能生成技术建议。',
  not_visible: '关键部位看不清，无法核对这段动作。',
  insufficient_sampling: '关键时刻的画面不足，无法确认动作过程。',
  record_conflict: '画面与动作记录存在冲突，需要先核对记录。',
  unknown_conditions: '建议所需的适用条件尚未确认。',
  review_rejected: '候选现象未通过独立画面复核。',
}

export function noAdviceReasons(report) {
  const explicit = (report?.no_advice_reasons || []).map(row => typeof row === 'string' ? row : row?.message).filter(Boolean)
  if (explicit.length) return [...new Set(explicit)]
  const mapped = (report?.reason_codes || []).map(code => reasonLabels[code]).filter(Boolean)
  if (mapped.length) return [...new Set(mapped)]
  if (report?.knowledge_status?.eligible_advice_claims === 0 || report?.knowledge_status?.eligible_advice_units === 0) return [reasonLabels.no_approved_knowledge]
  return ['这份报告没有提供通过复核的画面事实与适用条件，暂不能提出技术建议。']
}

export function reportIsCurrent(envelope, mediaAvailable = true) {
  return mediaAvailable && !envelope?.stale && !envelope?.legacy && envelope?.status === 'succeeded'
    && ['try', 'review', 'insufficient'].includes(envelope?.report?.result_status)
}

export function costLabel(cost) {
  if (cost?.status === 'partial') return Number.isFinite(cost.known_amount) && cost.known_amount >= 0 ? `¥${cost.known_amount.toFixed(4)}（已知部分）` : '暂无法估算'
  if (!cost || !['estimated', 'range', 'partial'].includes(cost.status)) return '暂无法估算'
  const low = cost.amount_min, high = cost.amount_max
  if (!Number.isFinite(low) || !Number.isFinite(high) || low < 0 || high < low) return '暂无法估算'
  const format = value => `¥${value.toFixed(4)}`
  return low === high ? format(low) : `${format(low)}–${format(high)}`
}

export function poseCost(job) {
  const run = [...(job?.analysis_runs || [])].reverse().find(row => row.attempt === (job?.attempt || 1))
  const value = (job?.result?.analysis || run?.analysis)?.cost
  if (value?.currency !== 'CNY' || !Number.isFinite(value?.estimated_amount) || value.estimated_amount < 0) return null
  return { ...value, status: 'estimated', amount_min: value.estimated_amount, amount_max: value.estimated_amount }
}

export function combinedCost(first, second) {
  if ([first, second].some(cost => !['estimated', 'range'].includes(cost?.status) || costLabel(cost) === '暂无法估算')) return null
  return { status: 'range', amount_min: first.amount_min + second.amount_min, amount_max: first.amount_max + second.amount_max }
}

export function annotationDependent(item) {
  return /标注为|标注显示|骨架显示|根据.{0,8}标注/.test(item?.observation || '')
}

export function evidenceLabel(item) {
  if (annotationDependent(item)) return '引用了视频标注，需重新核对'
  if (typeof item?.evidence_status === 'string' && item.evidence_status.trim()) return item.evidence_status
  return item?.evidence?.length >= 2 && item.end_seconds > item.start_seconds
    ? '有前后画面，现象仍待核实' : '单帧记录，不能证明动作过程'
}

export function readableObservation(text) {
  return String(text || '').replace(/(\d+\.\d{2,})\s*秒/g, (_, value) => `${Number(value).toFixed(1)} 秒`)
}
