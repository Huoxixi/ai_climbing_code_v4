// Reach an existing control through the workspace's presentation-only pagination.
export async function revealTool(page, target) {
  await target.waitFor({state:'attached'})
  await page.waitForTimeout(120)
  if(await target.isVisible())return target
  const panel=target.locator('xpath=ancestor::*[contains(concat(" ",normalize-space(@class)," ")," task-panel ")][1]')
  if(!await panel.count())return target
  const pager=panel.locator('.task-panel__pages')
  for(let i=0;i<30;i++){
    if(await target.isVisible())return target
    const next=pager.getByRole('button',{name:'下一页',exact:true})
    if(!await next.isVisible())break
    if(await next.isDisabled()){
      const previous=pager.getByRole('button',{name:'上一页',exact:true})
      while(await previous.isEnabled()){await previous.click();await page.waitForTimeout(40)}
    }else await next.click()
    await page.waitForTimeout(80)
  }
  return target
}

export async function replayFileAction(page, name) {
  const action=page.getByRole('button',{name,exact:true})
  if(!await action.isVisible())await page.getByRole('button',{name:'视频与资料',exact:true}).click()
  await action.click()
}
