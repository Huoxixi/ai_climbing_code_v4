
export const limbNames = { left_hand: '左手', right_hand: '右手', left_foot: '左脚', right_foot: '右脚', body: '身体' }

export function actionEventRows(groups) {
  return groups.map(group => {
    const important = group.important_action
    const components = important?.quality?.status === 'observed' && important?.commentary
      ? [{limb:important.limb,text:important.commentary,ai:important.commentary_basis==='vision_evidence'}] : []
    return { id: group.id, group_id: group.id, start_seconds: group.start_seconds, end_seconds: group.end_seconds,
      title: important?.title || '重要动作', components,
      description: components.map(c => c.text).join(' '), ai: components.some(c => c.ai) }
  }).filter(row => row.components.length && Number.isFinite(row.start_seconds) && Number.isFinite(row.end_seconds) && row.end_seconds > row.start_seconds)
    .sort((a, b) => a.start_seconds - b.start_seconds || a.end_seconds - b.end_seconds)
}
