const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const benchmark=vm.runInThisContext('('+readFileSync(__dirname+'/performance_browser.js','utf8')+')');
(async()=>{
  const listeners={};
  global.window={addEventListener:(name,listener)=>{listeners[name]=listener}};
  global.document={addEventListener:()=>{}};
  const page={url:()=> 'http://127.0.0.1:18083/?performanceCase=all_fit&exports=0#/reports',
    addInitScript:async()=>{},
    evaluate:async(fn,arg)=>{
      if(arg==='all_fit') throw new Error('stop before seeding');
      return fn(arg);
    }};
  await assert.rejects(()=>benchmark(page),/stop before seeding/);
  assert.equal(typeof listeners['elevator:performance'],'function','Install observer in current document before hash navigation');
  console.log('PASS current-document observer installed without new navigation');
  window.__elevatorMeasurements=[{name:'report_generate',click_to_visible_ms:999}];
  await assert.rejects(()=>benchmark(page),/stop before seeding/);
  assert.deepEqual(window.__elevatorMeasurements,[],'Rerunning in the same document must not reuse previous measurements');
  const snapshots=[];
  let requests=0;
  const action={click:async()=>{},filter:()=>action,getByRole:()=>action};
  const failurePage={url:()=> 'http://127.0.0.1:18083/?performanceCase=natural_language&exports=5#/',
    addInitScript:async()=>{},goto:async()=>{},getByRole:()=>action,
    waitForFunction:async()=>{},waitForEvent:async()=>({saveAs:async()=>{}}),
    waitForResponse:async()=>{
      const index=++requests;
      return {ok:()=>true,status:()=>200,json:async()=>{
        if(index===3) throw new SyntaxError('non JSON export failure');
        return index===1 ? {report:{score:0,provenance:{llm_used:true,assessment_complete:true}}} : {size:1200};
      }};
    },
    evaluate:async(fn,arg)=>{
      if(arg==='natural_language') return {id:'synthetic',userName:'synthetic'};
      if(arg?.case) {snapshots.push(structuredClone(arg));return;}
      if(typeof arg==='string') return 0;
      return {name:'report_generate',status:'ok',click_to_visible_ms:1};
    }};
  await assert.rejects(()=>benchmark(failurePage),/non JSON export failure/);
  assert.equal(snapshots.at(-1).status,'error');
  assert.equal(snapshots.at(-1).exports.length,1,'Keep previous successful export');
  assert.equal(snapshots.at(-1).failure.stage,'export_docx_1');
  assert(snapshots.some(record=>record.exports.length===0),'Generation persisted before exporting');
  console.log('PASS partial browser measurements survive a later export failure');
})().catch(error=>{console.error(error);process.exitCode=1});
