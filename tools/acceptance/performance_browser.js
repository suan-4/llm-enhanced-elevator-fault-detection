/* Playwright CLI run-code function. Log in to the isolated 18083 API first.
 * URL query: performanceCase=all_fit|selected_risks|natural_language, exports=0|5.
 * No user inputs/tokens are stored in the resulting measurement artifact.
 */
async (page) => {
  const url = new URL(page.url());
  const name = url.searchParams.get('performanceCase') || 'all_fit';
  const repeat = Number(url.searchParams.get('exports') || '0');
  if (url.hostname !== '127.0.0.1' || url.port !== '18083' || !['all_fit','selected_risks','natural_language'].includes(name) || ![0,5].includes(repeat)) throw new Error('Isolated benchmark URL required');
  const installObserver = () => {
    if (window.__elevatorPerformanceInstalled) return;
    window.__elevatorPerformanceInstalled = true;
    window.__elevatorMeasurements = [];
    window.__elevatorClicks = {};
    document.addEventListener('click', event => {
      const label = event.target.closest?.('button')?.textContent?.trim();
      const key = {'校验并生成报告':'report_generate','导出 PDF':'export_pdf','导出 Word':'export_docx'}[label];
      if (key) window.__elevatorClicks[key] = performance.now();
    }, true);
    window.addEventListener('elevator:performance', event => {
      const detail = event.detail;
      const click = window.__elevatorClicks[detail.name];
      window.__elevatorMeasurements.push({...detail, click_to_visible_ms:click === undefined ? null : performance.now()-click});
    });
  };
  await page.addInitScript(installObserver);
  await page.evaluate(installObserver);
  await page.evaluate(()=>{
    window.__elevatorMeasurements=[];
    window.__elevatorClicks={};
  });
  const seeded = await page.evaluate(async name => {
    const headers = {Authorization:'Bearer '+localStorage.getItem('elevator_token'),'Content-Type':'application/json'};
    const request = async (path,method='GET',body) => {
      const response = await fetch(path,{method,headers,body:body===undefined?undefined:JSON.stringify(body)});
      if (!response.ok) throw new Error(`Seed failed ${response.status}`);
      return response.json();
    };
    const info = await request('/api/system/info');
    if (info.db.path !== '/userdata/releases/20261016-performance-33b51595/benchmark/performance-benchmark.db') throw new Error('Not the isolated DB');
    const catalog = (await request('/api/report/jte-items')).items;
    const items = catalog.map(item=>({no:item.no,result:'fit',reasons:[],other_text:''}));
    if (name!=='all_fit') {
      items.find(item=>item.no==='1.9').result='na';
      for (const [no,indices] of [['1.7',[0,1]],['16.1',[31]],['16.6',[12]]]) {
        Object.assign(items.find(item=>item.no===no),{result:'unfit',reasons:indices.map(index=>catalog.find(item=>item.no===no).opts[index])});
      }
      if (name==='natural_language') Object.assign(items.find(item=>item.no==='16.1'),{reasons:[],other_text:'控制柜的散热风道被灰尘堵住，电气元件温度升高。'});
    }
    const userName='性能浏览器_'+name+'_'+Date.now();
    const form={clientName:'性能测试委托单位',userName,deviceCategory:'曳引驱动电梯',productNo:'PERFORMANCE-BROWSER',instruments:'/',basis:'/'};
    const report=(await request('/api/reports','POST',{})).report;
    await request('/api/reports/'+report.id,'PUT',{form,items,version:report.version});
    return {id:report.id,userName};
  },name);
  const record={case:name,exports:[],status:'in_progress'};
  const artifact='output/playwright/performance-'+name+'.json';
  const persist=async()=>{
    const pendingDownload=page.waitForEvent('download');
    await page.evaluate(record=>{
      const link=document.createElement('a');
      const blob=URL.createObjectURL(new Blob([JSON.stringify(record,null,2)],{type:'application/json'}));
      link.href=blob;
      link.download='measurements.json';
      link.click();
      setTimeout(()=>URL.revokeObjectURL(blob),1000);
    },record);
    await (await pendingDownload).saveAs(artifact);
  };
  let stage='open_report';
  try {
  await page.goto(url.origin+'/?performanceCase='+name+'&exports='+repeat+'#/reports');
  await page.getByRole('row').filter({hasText:seeded.userName}).getByRole('button',{name:'继续编辑',exact:true}).click();
  stage='generate';
  const generation = page.waitForResponse(response=>response.url().endsWith('/api/reports/'+seeded.id+'/generate') && response.request().method()==='POST',{timeout:180000});
  await page.getByRole('button',{name:'校验并生成报告',exact:true}).click();
  const response = await generation;
  const data = await response.json();
  await page.waitForFunction(()=>window.__elevatorMeasurements?.some(item=>item.name==='report_generate'),{},{timeout:180000});
  Object.assign(record,{http_status:response.status(),llm_used:data.report?.provenance?.llm_used,
    score:data.report?.score,backend:data.report?.performance,
    generation:await page.evaluate(()=>window.__elevatorMeasurements.find(item=>item.name==='report_generate'))});
  await persist();
  if (response.ok() && data.report?.provenance?.assessment_complete) {
    for (let index=1;index<=repeat;index++) {
      for (const [format,label,event] of [['pdf','导出 PDF','export_pdf'],['docx','导出 Word','export_docx']]) {
        stage='export_'+format+'_'+index;
        const count = await page.evaluate(event=>window.__elevatorMeasurements.filter(item=>item.name===event).length,event);
        const pending = page.waitForResponse(response=>response.url().endsWith('/api/report/export') && response.request().method()==='POST',{timeout:120000});
        await page.getByRole('button',{name:label,exact:true}).click();
        if (data.report.provenance.other_matches?.length) await page.getByRole('button',{name:'确认并导出',exact:true}).click();
        const exported = await pending;
        const result = await exported.json();
        await page.waitForFunction(({event,count})=>window.__elevatorMeasurements.filter(item=>item.name===event).length>count,{event,count},{timeout:120000});
        record.exports.push({index,format,status:exported.status(),size:result.size,backend:result.performance,
          browser:await page.evaluate(event=>window.__elevatorMeasurements.filter(item=>item.name===event).at(-1),event)});
        await persist();
      }
    }
  }
  record.status='complete';
  await persist();
  } catch(error) {
    record.status='error';
    record.failure={stage,error_type:error?.name || 'Error'};
    await persist();
    throw error;
  }
  return {case:name,status:record.http_status,llm_used:record.llm_used,score:record.score,
    browser_ms:record.generation?.click_to_visible_ms,exports:record.exports.length,artifact};
}
