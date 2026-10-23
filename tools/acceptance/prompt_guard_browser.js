/* CLI run-code function. Log in to isolated 18084 and generate a valid report first. */
async (page) => {
  if (new URL(page.url()).origin !== 'http://127.0.0.1:18084') throw new Error('Isolated candidate required');
  const health=await (await page.request.get('http://127.0.0.1:18084/api/health')).json();
  if (health.benchmark_db !== '/userdata/releases/20261018-prompt-guard-01/benchmark/performance-benchmark.db') throw new Error('Wrong database');
  const errors = [];
  page.on('pageerror', error => errors.push(error.name));
  await page.locator('.model-status:visible').waitFor({timeout:120000});
  if ((await page.locator('.model-status:visible').innerText()).includes('已保存的预览')) {
    await page.locator('.sidebar li').filter({hasText:'评估报告录入'}).click();
    await page.getByRole('button',{name:'校验并生成报告',exact:true}).click();
    await page.locator('.model-status:visible').waitFor({timeout:120000});
  }
  const notice = await page.locator('.model-status:visible').innerText();
  if (!notice.includes('模型概况已生成') || notice.includes('已保存的预览')) throw new Error('Fresh model notice incorrect');
  const paperNotices = await page.locator('.paper .model-status').count();
  if (paperNotices) throw new Error('Operator status leaked into report paper');
  const meta = await page.locator('.report-meta').innerText();
  const number = meta.match(/GDSEI-JTE-\d{8}-\d+/)?.[0];
  if (!number) throw new Error('Expected generated report number');
  await page.screenshot({path:'output/playwright/prompt-guard-fresh.png'});
  await page.goto('http://127.0.0.1:18084/#/reports');
  const row = page.getByRole('row').filter({hasText:number});
  await row.getByRole('button',{name:'查看',exact:true}).click();
  await page.locator('.model-status:visible').waitFor();
  const saved = await page.locator('.model-status:visible').innerText();
  if (!saved.includes('已保存的预览') || !saved.includes('未重新调用模型')) throw new Error('Saved preview notice incorrect');
  await page.screenshot({path:'output/playwright/prompt-guard-saved.png'});
  const bounds = await page.locator('.model-status:visible').evaluate(node=>{
    const box=node.getBoundingClientRect();
    return {left:box.left,right:box.right,width:innerWidth};
  });
  if (bounds.left < 0 || bounds.right > bounds.width+1) throw new Error('Notice outside viewport');
  // Real blocked report, not a mocked success/degradation banner.
  const seeded = await page.evaluate(async () => {
    const headers = {Authorization:'Bearer '+localStorage.getItem('elevator_token'),'Content-Type':'application/json'};
    const request = async (path,method='GET',body) => {
      const response=await fetch(path,{method,headers,body:body===undefined?undefined:JSON.stringify(body)});
      if (!response.ok) throw new Error('Candidate fixture request failed');
      return response.json();
    };
    const health = await request('/api/health');
    if (health.benchmark_db !== '/userdata/releases/20261018-prompt-guard-01/benchmark/performance-benchmark.db') throw new Error('Wrong database');
    const catalog=(await request('/api/report/jte-items')).items;
    const report=(await request('/api/reports','POST',{})).report;
    const userName='浏览器预算保护验收-'+Date.now();
    await request('/api/reports/'+report.id,'PUT',{
      version:report.version,
      form:{clientName:'隔离委托单位',userName,deviceCategory:'曳引驱动电梯',productNo:'UI-GUARD',instruments:'/',basis:'/'},
      items:catalog.map(item=>({no:item.no,result:item.opts.length?'unfit':'fit',reasons:item.opts,other_text:''})),
    });
    return {id:report.id,userName};
  });
  await page.goto('http://127.0.0.1:18084/#/reports');
  await page.getByRole('row').filter({hasText:seeded.userName}).getByRole('button',{name:'继续编辑',exact:true}).click();
  const pending=page.waitForResponse(response=>response.url().endsWith('/api/reports/'+seeded.id+'/generate'));
  await page.getByRole('button',{name:'校验并生成报告',exact:true}).click();
  const generated=(await (await pending).json()).report;
  if (generated.provenance.llm_error_code !== 'context_budget_exceeded') throw new Error('Expected token guard');
  if (generated.performance.model_calls.some(call=>call.http_status!==null)) throw new Error('Oversize input reached model HTTP');
  await page.locator('.model-status:visible').waitFor();
  const degraded=await page.locator('.model-status:visible').innerText();
  if (!degraded.includes('规则摘要') || !degraded.includes('输入超过模型预算')) throw new Error('Degradation reason missing');
  if (await page.locator('.paper .model-status').count()) throw new Error('Status entered paper');
  await page.screenshot({path:'output/playwright/prompt-guard-degraded.png'});
  if (errors.length) throw new Error('Browser page errors');
  return {fresh:true,saved:true,degraded:true,no_model_http_on_oversize:true,
    notice_outside_paper:paperNotices===0,bounds,page_errors:errors.length};
}
