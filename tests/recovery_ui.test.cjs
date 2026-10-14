// Execute the shipped draft controls; real browser coverage is in browser_six_review.py.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function page({action='archive', dirty=true, code=200, save=true, unrelated=false, network=false}={}) {
  function node() {return {children:[],disabled:false,dataset:{},_text:'',
    set textContent(v){this._text=v;this.children=[];},get textContent(){return this._text;},append(n){this.children.push(n);}};}
  const root=node(), status=node(), button=node(), input=node(); input.value='42';
  root.dataset={id:'10',version:'3',actor:'1',store:'2'};
  button.dataset.draftAction=action;root.querySelectorAll=()=>[button];
  const ids={'draft-tools':root,'draft-tools-status':status};
  const saved=JSON.stringify({draftId:unrelated?99:10,draftVersion:3,items:[{reason:'unsaved',quantity:42}]});
  const data=new Map([['system2-ordering:1:2',saved]]),calls=[];
  const sessionStorage={getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)};
  const location={href:'/store/ordering?draft_id=10',reload(){this.reloaded=true;}};
  const document={getElementById:id=>ids[id]||null,createElement:node,querySelectorAll:()=>[button,input,...status.children]};
  const window={confirm:()=>true,system2DraftEditor:{busy:()=>false,dirty:()=>dirty,save:async()=>{if(save)root.dataset.version='4';return save;}}};
  const fetch=async(url,options)=>{calls.push({url,options});if(url.endsWith('/csrf'))return {ok:true,json:async()=>({csrf_token:'x'})};if(network)throw Error('network failed');return {ok:code===200,status:code,json:async()=>code===200?{id:11}:{error:{message:'failed'}}};};
  vm.runInNewContext(fs.readFileSync('app/static/js/draft-tools.js','utf8'),{document,window,sessionStorage,location,fetch});
  return {root,status,button,input,data,calls,saved,location,choose:label=>status.children.find(n=>n.textContent===label).onclick()};
}
for(const action of ['archive','rebuild']) {
  test(`${action}: cancel retains unsaved quantity and storage without a request`,async()=>{
    const p=page({action});p.button.onclick();await p.choose('取消');assert.equal(p.calls.length,0);assert.equal(p.input.value,'42');assert.equal([...p.data.values()][0],p.saved);
  });
  for(const choice of ['儲存後繼續','放棄未儲存修改並繼續']) {
    test(`${action}: ${choice} uses the displayed version and clears after success`,async()=>{
      const p=page({action});p.button.onclick();await p.choose(choice);
      const post=p.calls.find(c=>c.options?.method==='POST');assert.equal(JSON.parse(post.options.body).expected_version,choice==='儲存後繼續'?4:3);
      assert.equal(p.calls.some(c=>c.url==='/api/order-drafts/10'),false);assert.equal(p.data.size,0);
      assert.equal(p.location.href,action==='archive'?'/?store_id=2':'/store/ordering?store_id=2&draft_id=11');
    });
  }
  for(const options of [{code:409},{code:500},{network:true},{save:false}]) {
    test(`${action}: failure ${JSON.stringify(options)} retains inputs, storage and navigation`,async()=>{
      const p=page({action,...options});p.button.onclick();await p.choose(options.save===false?'儲存後繼續':'放棄未儲存修改並繼續');
      assert.equal([...p.data.values()][0],p.saved);assert.equal(p.input.value,'42');assert.equal(p.input.disabled,false);
      assert.equal(p.location.href,'/store/ordering?draft_id=10');assert.match(p.status.textContent,/保留/);
      if(options.code===409)assert.ok(p.status.children.some(n=>n.textContent==='另開視窗比對伺服器草稿'));
      if(options.save===false)assert.equal(p.calls.length,0);
    });
  }
  test(`${action}: another draft's storage survives a successful action`,async()=>{
    const p=page({action,dirty:false,unrelated:true});p.button.onclick();await p.choose('使用已儲存內容繼續');assert.equal([...p.data.values()][0],p.saved);
  });
}
