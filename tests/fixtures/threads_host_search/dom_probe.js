// A structural HTML-tree fixture adapter, not an extractor-output mock or browser claim.
const fs = require('fs'), vm = require('vm');
const payload = JSON.parse(process.argv[3]);
function matches(node, selector) {
  if (node.nodeType !== 1) return false;
  const m = selector.trim().match(/^([a-z0-9-]+)?(?:\[([a-z0-9-]+)(?:="([^"]*)")?\])?$/i);
  if (!m) throw Error('Unsupported fixture selector: ' + selector);
  return (!m[1] || node.tagName.toLowerCase() === m[1].toLowerCase()) &&
    (!m[2] || node.getAttribute(m[2]) !== null && (m[3] === undefined || node.getAttribute(m[2]) === m[3]));
}
class Element {
  constructor(tree, parent=null) {
    this.nodeType=tree.tag ? 1 : 3; this.tagName=(tree.tag||'').toUpperCase(); this.attrs=tree.attrs||{};
    this.nodeValue=tree.text||''; this.parentElement=parent;
    this.childNodes=(tree.children||[]).map(child=>new Element(child,this));
  }
  get textContent(){return this.nodeType===3?this.nodeValue:this.childNodes.map(x=>x.textContent).join('');}
  get innerText(){return this.textContent;}
  get href(){return new URL(this.getAttribute('href'), 'https://www.threads.com').href;}
  getAttribute(name){return Object.prototype.hasOwnProperty.call(this.attrs,name)?this.attrs[name]:null;}
  getClientRects(){return this.closest('[hidden]') || /display\s*:\s*none/.test(this.attrs.style||'')?[]:[1];}
  contains(node){for(let n=node;n;n=n.parentElement)if(n===this)return true;return false;}
  closest(selector){for(let n=this;n;n=n.parentElement)if(selector.split(',').some(s=>matches(n,s)))return n;return null;}
  querySelectorAll(selector){
    const all=[];const walk=node=>{for(const child of node.childNodes){if(child.nodeType===1)all.push(child);walk(child);}};walk(this);
    return all.filter(node=>selector.split(',').some(part=>{
      const pieces=part.trim().split(/\s+/); if(!matches(node,pieces.pop()))return false;
      let parent=node.parentElement; while(pieces.length){const target=pieces.pop();while(parent&&!matches(parent,target))parent=parent.parentElement;if(!parent)return false;parent=parent.parentElement;}return true;
    }));
  }
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
}
const fixed='2026-10-28T01:00:00.000Z';
class Clock extends Date { constructor(value){super(value===undefined?fixed:value);}static now(){return Date.parse(fixed);} }
const document={root:null,documentElement:{lang:payload.locale||'en'},querySelectorAll:s=>document.root.querySelectorAll(s)};
const context={document,location:{href:payload.url},URL,Date:Clock,Map,Set,globalThis:null};context.globalThis=context;
const extract=vm.runInNewContext('('+fs.readFileSync(process.argv[2],'utf8')+')',context);
let result;for(const tree of payload.frames){document.root=new Element(tree);result=extract({query_id:'q1',query:'synthetic query',result_limit:payload.limit||3});}
console.log(JSON.stringify(result));
