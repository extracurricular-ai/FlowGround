import React from 'react';
import { RunClient, SERVER_DOWN_MSG } from './runClient.js';

export default class Flowground extends React.Component {
  constructor(props) {
    super(props);
    this.canvasRef = React.createRef();
    this.consoleRef = React.createRef();
    this.nid = 100; this.eid = 100; this.press = null;
    // Run-epoch counter (PROTOCOL.md "runId"): each start claims ++gen and sends
    // runId 'r'+gen; run-scoped server frames from any other epoch are dropped.
    this._runGen = 0;
    // Pending-start latch: gen of a start that has been sent (or queued behind the
    // WS handshake) but not yet answered by started/finished/error. While pending,
    // Run/Step clicks are ignored. Stored per-gen so a Reset (which bumps _runGen)
    // implicitly clears it.
    this._pendingStart = null;

    this.TYPES = {
      start: { label: 'Start', color: '#7FA284', glyph: '▶', desc: 'Begin the flow' },
      ask:   { label: 'Ask',   color: '#4E939B', glyph: '?', desc: 'Get a value from the user' },
      say:   { label: 'Say',   color: '#E8684A', glyph: '“', desc: 'Print a message' },
      set:   { label: 'Set variable', color: '#E2A23B', glyph: '=', desc: 'Remember a value' },
      iff:   { label: 'If',    color: '#B0708F', glyph: '◆', desc: 'Choose a path' },
      loop:  { label: 'Loop',  color: '#B65C3F', glyph: '↺', desc: 'Repeat steps' },
      fn:    { label: 'Function', color: '#8E7CC3', glyph: 'ƒ', desc: 'Use a mini-machine' },
      split: { label: 'Split', color: '#3B8EA5', glyph: '⑂', desc: 'Run two branches at once' },
      merge: { label: 'Merge', color: '#5B7F3B', glyph: '⑃', desc: 'Wait for every branch, then continue' },
      subgraph: { label: 'Subgraph', color: '#9A6B3F', glyph: '▣', desc: 'A whole mini-flow, packed into one block' },
      end:   { label: 'End',   color: '#8B8178', glyph: '■', desc: 'Finish the flow' }
    };
    this.ORDER = ['start','ask','say','set','iff','loop','fn','split','merge','subgraph','end'];
    // block -> required LoopGraph kind (PROTOCOL.md block table).
    this.KIND_OF = {iff:'SWITCH', loop:'SWITCH', end:'TERMINAL', merge:'AGGREGATE', subgraph:'SUBGRAPH'};
    this.SPEEDS = [{label:'0.5×',ms:1400},{label:'1×',ms:850},{label:'2×',ms:420}];
    this.ACHS = [
      {id:'tutorial', label:'Trained up',     desc:'Finished the tutorial'},
      {id:'wire',     label:'Wire wizard',    desc:'Connected two blocks'},
      {id:'run',      label:'First flight',   desc:'Ran a flow to the end'},
      {id:'decider',  label:'Decision maker', desc:'Ran an If block'},
      {id:'looper',   label:'Round tripper',  desc:'Completed a loop'}
    ];
    this.TUT = [
      {t:'Welcome to Flowground', b:'Programs are just flows: steps, decisions, and loops. Here you draw them — and then watch them actually run.', next:'Show me', pos:{left:'50%',top:'32%',transform:'translateX(-50%)'}},
      {t:'Your blocks', b:'Each block is one instruction. Drag any block onto the canvas — or just click it to drop one in.', next:'Next', pos:{left:'240px',top:'110px'}},
      {t:'Wire it up', b:'Every block has a dot underneath. Drag from a dot to another block to draw an arrow — that is the order things happen. Click a block to edit its words and numbers.', next:'Next', pos:{left:'46%',top:'40%',transform:'translateX(-50%)'}},
      {t:'Press Run', b:'Run walks through your flow one block at a time, lighting up the path it takes. Use Step to move one instruction at a time, and the speed switch to slow things down.', next:'Next', pos:{left:'50%',top:'72px',transform:'translateX(-50%)'}},
      {t:'Watch it think', b:'Variables show what the flow remembers, and the console tells the story of every step. Ready — press Run and watch the starter flow loop!', next:'Let’s go', pos:{right:'310px',top:'110px'}}
    ];

    let ach = {}; let tutDone = false;
    try { ach = JSON.parse(localStorage.getItem('flowground.ach') || '{}') || {}; } catch (e) {}
    try { tutDone = localStorage.getItem('flowground.tut') === '1'; } catch (e) {}

    this.state = {
      // Parallel run -> merge -> loop whose body is a subgraph node that is
      // itself a loop: exercises LoopGraph 0.5's fan-out (split), quorum
      // join (merge/AGGREGATE) and nested sub-workflow (subgraph) features.
      nodes: [
        {id:'n1',  type:'start',    x:360, y:40,   data:{}},
        {id:'n2',  type:'ask',      x:360, y:150,  data:{name:'name', value:'Ada'}},
        {id:'n3',  type:'say',      x:360, y:260,  data:{text:'Hello, {name}! Splitting into two branches…'}},
        {id:'n4',  type:'set',      x:360, y:370,  data:{name:'num', expr:'4'}},
        {id:'n5',  type:'split',    x:360, y:480,  data:{}},
        {id:'n6',  type:'say',      x:120, y:610,  data:{text:'Branch A: still {name}'}},
        {id:'n7',  type:'fn',       x:600, y:610,  data:{fn:'square', arg:'num', result:'squared'}},
        {id:'n8',  type:'merge',    x:360, y:740,  data:{}},
        {id:'n9',  type:'say',      x:360, y:850,  data:{text:'Merged! squared = {squared}'}},
        {id:'n10', type:'loop',     x:360, y:960,  data:{times:'2'}},
        {id:'n11', type:'subgraph', x:360, y:1070, data:{graph: JSON.stringify(this.defaultInnerLoopGraph('n11'))}},
        {id:'n12', type:'end',      x:650, y:960,  data:{}}
      ],
      edges: [
        {id:'e1',  from:{node:'n1',port:'out'},     to:'n2'},
        {id:'e2',  from:{node:'n2',port:'out'},     to:'n3'},
        {id:'e3',  from:{node:'n3',port:'out'},     to:'n4'},
        {id:'e4',  from:{node:'n4',port:'out'},     to:'n5'},
        {id:'e5',  from:{node:'n5',port:'a'},       to:'n6'},
        {id:'e6',  from:{node:'n5',port:'b'},       to:'n7'},
        {id:'e7',  from:{node:'n6',port:'out'},     to:'n8'},
        {id:'e8',  from:{node:'n7',port:'out'},     to:'n8'},
        {id:'e9',  from:{node:'n8',port:'out'},     to:'n9'},
        {id:'e10', from:{node:'n9',port:'out'},     to:'n10'},
        {id:'e11', from:{node:'n10',port:'repeat'}, to:'n11'},
        {id:'e12', from:{node:'n11',port:'out'},    to:'n10'},
        {id:'e13', from:{node:'n10',port:'done'},   to:'n12'}
      ],
      selNode: null, selEdge: null, ghost: null, pend: null,
      running: false, paused: false, curId: null, activeEdge: null,
      vars: {}, steps: 0, console: [],
      speedIx: 1, ach: ach, toast: null, tut: tutDone ? -1 : 0, exportOn: false, exportFmt: 'lg', copied: false
    };
  }

  componentDidMount() {
    this._mv = (e) => this.onDocMove(e);
    this._up = (e) => this.onDocUp(e);
    this._kd = (e) => this.onKey(e);
    document.addEventListener('mousemove', this._mv);
    document.addEventListener('mouseup', this._up);
    document.addEventListener('keydown', this._kd);
  }
  componentWillUnmount() {
    document.removeEventListener('mousemove', this._mv);
    document.removeEventListener('mouseup', this._up);
    document.removeEventListener('keydown', this._kd);
    if (this._rc) { this._rc.close(); this._rc = null; }
    clearTimeout(this._toastT); clearTimeout(this._copyT);
  }
  componentDidUpdate(pp, ps) {
    const el = this.consoleRef.current;
    if (el && ps && ps.console.length !== this.state.console.length) el.scrollTop = el.scrollHeight;
  }

  // A subgraph block has no nested-canvas editor — every subgraph node embeds
  // this fixed mini-loop (PROTOCOL.md "subgraph": a nested flowground.v1 flow,
  // JSON-encoded in config.graph). It's a real 2-round loop, compiled and run
  // by LoopGraph exactly like the top-level flow.
  // `prefix` MUST be unique per subgraph node instance — the backend requires
  // globally-unique ids across a flow and every nested body, at any depth, so
  // two subgraph blocks sharing the same inner ids fail to compile.
  defaultInnerLoopGraph(prefix) {
    const p = prefix + '_';
    const kindOf = (t) => this.KIND_OF[t] || 'TASK';
    const n = (id, block, config) => ({id: p + id, kind: kindOf(block), block, config: config || {}});
    return {
      format: 'flowground.v1',
      entry: p + 'start',
      nodes: [
        n('start', 'start'),
        n('loop', 'loop', {mode:'count', times:'2'}),
        n('say', 'say', {text:'Inner round — hi from inside the subgraph!'}),
        n('end', 'end')
      ],
      edges: [
        {source:p+'start', port:'out',    target:p+'loop'},
        {source:p+'loop',  port:'repeat', target:p+'say'},
        {source:p+'say',   port:'out',    target:p+'loop'},
        {source:p+'loop',  port:'done',   target:p+'end'}
      ]
    };
  }

  // ---------- helpers ----------
  acc() { return this.props.accent || '#E8684A'; }
  portsOf(type) {
    if (type === 'iff')   return [{port:'true',label:'yes',color:'#6E9A72'},{port:'false',label:'no',color:'#C4553B'}];
    if (type === 'loop')  return [{port:'repeat',label:'again',color:'#B65C3F'},{port:'done',label:'done',color:'#8B8178'}];
    if (type === 'split') return [{port:'a',label:'A',color:'#3B8EA5'},{port:'b',label:'B',color:'#2E6E80'}];
    if (type === 'end')   return [];
    return [{port:'out',label:'',color:this.TYPES[type].color}];
  }
  outAnchor(n, port) {
    const sz = this.boxSizeFor(n);
    const ps = this.portsOf(n.type);
    if (ps.length === 2) return {x: n.x + sz.w * (port === ps[0].port ? 0.197 : 0.803), y: n.y + sz.h};
    return {x: n.x + sz.w / 2, y: n.y + sz.h};
  }
  // A subgraph block renders its REAL inner structure (PROTOCOL.md: ticks
  // carry true inner-node ids, never remapped) rather than an opaque box, so
  // it needs a bigger, content-sized footprint. Every other block keeps the
  // original fixed chip size.
  boxSizeFor(n) {
    if (n.type === 'subgraph') {
      const L = this.miniLayoutFor(n);
      if (L) return {w: Math.max(188, L.width), h: Math.max(58, L.height)};
    }
    return {w: 188, h: 58};
  }
  miniLayoutFor(n) {
    try { return this.miniLayout(JSON.parse(n.data.graph)); } catch (e) { return null; }
  }
  // Layered top-to-bottom layout for a nested flowground.v1 flow: BFS from
  // `entry` over forward edges (to a not-yet-visited node) assigns each node
  // a row; an edge to an already-assigned node is a back-edge (a loop),
  // rendered as a curved return rather than a straight line down.
  miniLayout(graphDef) {
    const byId = {}; graphDef.nodes.forEach(function(gn){ byId[gn.id] = gn; });
    const out = {}; graphDef.nodes.forEach(function(gn){ out[gn.id] = []; });
    graphDef.edges.forEach(function(e){ (out[e.source] || (out[e.source] = [])).push(e); });
    const layer = {}; layer[graphDef.entry] = 0;
    const order = [graphDef.entry];
    const queue = [graphDef.entry];
    while (queue.length) {
      const id = queue.shift();
      (out[id] || []).forEach(function(e) {
        if (layer[e.target] == null) {
          layer[e.target] = layer[id] + 1;
          order.push(e.target);
          queue.push(e.target);
        }
      });
    }
    const rowH = 52, colW = 92, padX = 14, padTop = 32;
    const byLayer = {};
    order.forEach(function(id){ (byLayer[layer[id]] = byLayer[layer[id]] || []).push(id); });
    const pos = {};
    let maxCols = 1;
    Object.keys(byLayer).forEach(function(l) {
      const ids = byLayer[l];
      maxCols = Math.max(maxCols, ids.length);
      ids.forEach(function(id, i){ pos[id] = {x: padX + i * colW + 30, y: padTop + Number(l) * rowH}; });
    });
    const maxLayer = order.reduce(function(m, id){ return Math.max(m, layer[id]); }, 0);
    return {
      byId: byId, pos: pos, order: order,
      edges: graphDef.edges.map(function(e){
        return {source: e.source, port: e.port, target: e.target,
                back: layer[e.target] <= layer[e.source]};
      }),
      width: padX * 2 + maxCols * colW,
      height: padTop + (maxLayer + 1) * rowH + 12
    };
  }
  fmt(v, bare) {
    // JSON cannot carry non-finite numbers; the server encodes them as
    // {"__js": "NaN"|"Infinity"|"-Infinity"} (PROTOCOL.md "tick"). Render them
    // bare — NaN, not "NaN" — matching the prototype's String(NaN).
    if (v && typeof v === 'object' && typeof v.__js === 'string') return v.__js;
    if (typeof v === 'string') return bare ? v : '"' + v + '"';
    return String(v);
  }
  log(kind, text) { this.setState(function(s){ return {console: s.console.concat([{kind:kind, text:text}]).slice(-200)}; }); }

  // ---------- graph editing ----------
  addNode(type, x, y) {
    const id = 'n' + (this.nid++);
    // subgraph's inner ids are prefixed with this node's own id — every
    // subgraph instance needs globally-unique inner ids, or two of them on
    // one canvas collide (PROTOCOL.md: ids unique across all nesting).
    const d = {ask:{name:'age', value:'12'}, say:{text:'Hello, {name}!'}, set:{name:'count', expr:'1'},
               iff:{cond:'count > 3'}, loop:{mode:'count', times:'3', cond:'count < 4'}, fn:{fn:'double', arg:'count', result:'count'},
               subgraph:{graph: JSON.stringify(this.defaultInnerLoopGraph(id))}}[type] || {};
    const cnt = this.state.nodes.length;
    const nx = x != null ? x : 640 + ((cnt * 40) % 180);
    const ny = y != null ? y : 120 + ((cnt * 70) % 420);
    this.setState(function(s){ return {nodes: s.nodes.concat([{id:id, type:type, x:Math.max(8,nx), y:Math.max(8,ny), data:Object.assign({},d)}]), selNode:id, selEdge:null}; });
  }
  connect(from, toId) {
    if (from.node === toId) return;
    this.setState(function(s){
      const edges = s.edges.filter(function(e){ return !(e.from.node === from.node && e.from.port === from.port); });
      return {edges: edges.concat([{id:'e' + Math.random().toString(36).slice(2,8), from:from, to:toId}])};
    });
    this.unlock('wire');
  }
  hitNode(x, y, excludeId) {
    const self = this;
    return this.state.nodes.find(function(n){
      if (n.id === excludeId || n.type === 'start') return false;
      const sz = self.boxSizeFor(n);
      return x >= n.x - 8 && x <= n.x + sz.w + 8 && y >= n.y - 10 && y <= n.y + sz.h + 8;
    });
  }
  deleteNode(id) {
    this.setState(function(s){ return {nodes: s.nodes.filter(function(n){ return n.id !== id; }), edges: s.edges.filter(function(e){ return e.from.node !== id && e.to !== id; }), selNode:null}; });
  }

  // ---------- mouse ----------
  onPaletteDown(type, e) {
    e.preventDefault();
    this.press = {kind:'palette', type:type, moved:false, sx:e.clientX, sy:e.clientY};
    this.setState({ghost:{type:type, x:e.clientX, y:e.clientY}});
  }
  onNodeDown(id, e) {
    e.stopPropagation(); e.preventDefault();
    const r = this.canvasRef.current.getBoundingClientRect();
    const n = this.state.nodes.find(function(x){ return x.id === id; });
    this.press = {kind:'node', id:id, dx:e.clientX - r.left - n.x, dy:e.clientY - r.top - n.y, moved:false, sx:e.clientX, sy:e.clientY};
  }
  onPortDown(nodeId, port, e) {
    e.stopPropagation(); e.preventDefault();
    const r = this.canvasRef.current.getBoundingClientRect();
    this.press = {kind:'wire', from:{node:nodeId, port:port}};
    this.setState({pend:{from:{node:nodeId, port:port}, x:e.clientX - r.left, y:e.clientY - r.top}});
  }
  onDocMove(e) {
    const pr = this.press; if (!pr) return;
    if (pr.sx != null && Math.abs(e.clientX - pr.sx) + Math.abs(e.clientY - pr.sy) > 4) pr.moved = true;
    if (pr.kind === 'palette') this.setState({ghost:{type:pr.type, x:e.clientX, y:e.clientY}});
    if (pr.kind === 'node' && pr.moved) {
      const r = this.canvasRef.current.getBoundingClientRect();
      const x = Math.max(8, Math.min(1404, e.clientX - r.left - pr.dx));
      const y = Math.max(8, Math.min(1330, e.clientY - r.top - pr.dy));
      this.setState(function(s){ return {nodes: s.nodes.map(function(n){ return n.id === pr.id ? Object.assign({}, n, {x:x, y:y}) : n; })}; });
    }
    if (pr.kind === 'wire') {
      const r = this.canvasRef.current.getBoundingClientRect();
      this.setState({pend:{from:pr.from, x:e.clientX - r.left, y:e.clientY - r.top}});
    }
  }
  onDocUp(e) {
    const pr = this.press; if (!pr) return; this.press = null;
    if (pr.kind === 'palette') {
      const r = this.canvasRef.current.getBoundingClientRect();
      const inside = e.clientX >= r.left && e.clientX <= Math.min(r.right, window.innerWidth - 292) && e.clientY >= r.top;
      if (pr.moved && inside) this.addNode(pr.type, e.clientX - r.left - 94, e.clientY - r.top - 29);
      else if (!pr.moved) this.addNode(pr.type, null, null);
      this.setState({ghost:null});
    }
    if (pr.kind === 'node' && !pr.moved) this.setState({selNode:pr.id, selEdge:null});
    if (pr.kind === 'wire') {
      const p = this.state.pend;
      if (p) { const t = this.hitNode(p.x, p.y, pr.from.node); if (t) this.connect(pr.from, t.id); }
      this.setState({pend:null});
    }
  }
  onKey(e) {
    if (e.key !== 'Delete' && e.key !== 'Backspace') return;
    const ae = document.activeElement;
    if (ae && (ae.tagName === 'INPUT' || ae.tagName === 'SELECT' || ae.tagName === 'TEXTAREA')) return;
    if (this.state.selNode) { e.preventDefault(); this.deleteNode(this.state.selNode); }
    else if (this.state.selEdge) {
      e.preventDefault();
      const id = this.state.selEdge;
      this.setState(function(s){ return {edges: s.edges.filter(function(x){ return x.id !== id; }), selEdge:null}; });
    }
  }

  // ---------- execution (server-driven, PROTOCOL.md) ----------
  runClient() {
    if (!this._rc) {
      const self = this;
      this._rc = new RunClient({
        onEvent: function(msg){ self.onServerEvent(msg); },
        onDisconnect: function(){ self.onServerLost(); }
      });
    }
    return this._rc;
  }
  serverDown() {
    this._pendingStart = null;
    this.setState(function(s){ return {
      console: s.console.concat([{kind:'err', text:SERVER_DOWN_MSG}]).slice(-200),
      running:false, paused:false, curId:null, activeEdges:{}
    }; });
  }
  onServerLost() {
    if (!this.state.running && !this.startPending()) return;
    this.serverDown();
  }
  startPending() {
    return this._pendingStart != null && this._pendingStart === this._runGen;
  }
  startRun(mode) {
    const start = this.state.nodes.find(function(n){ return n.type === 'start'; });
    if (!start) { this.log('err', 'Add a Start block first — every flow needs one.'); return; }
    const self = this;
    const gen = ++this._runGen;
    this._pendingStart = gen;
    const rc = this.runClient();
    rc.connect().then(function(){
      // Re-check the captured epoch: if the user hit Reset (or another start won
      // the race) during the WS handshake, this start is void — sending it would
      // silently revive a run the user just cancelled (send() on an opening
      // socket returns false, so the earlier Reset never reached the server).
      if (gen !== self._runGen) return;
      rc.send({type:'start', flow:self.buildFlow(), mode:mode, speed:self.state.speedIx, runId:'r' + gen});
      if (mode === 'step') rc.send({type:'step'});
    }, function(){
      if (self._pendingStart === gen) self._pendingStart = null;
      self.serverDown();
    });
  }
  onRunClick() {
    const s = this.state;
    if (!s.running) {
      // state.running only flips on the started round-trip; without this latch a
      // fast second click would send a second start that implicitly resets the first.
      if (this.startPending()) return;
      this.startRun('run');
    }
    else if (s.paused) { this.runClient().send({type:'resume'}); this.setState({paused:false}); }
    else { this.runClient().send({type:'pause'}); this.setState({paused:true}); }
  }
  onStepClick() {
    if (!this.state.running) {
      if (this.startPending()) return;
      this.startRun('step');
    }
    else { this.runClient().send({type:'step'}); this.setState({paused:true}); }
  }
  onResetClick() {
    // Bump the run epoch so any in-flight frames of the reset run (and any start
    // still queued behind the WS handshake) are invalidated.
    this._runGen++;
    this._pendingStart = null;
    if (this._rc) this._rc.send({type:'reset'});
    this.setState({running:false, paused:false, curId:null, activeEdges:{}, vars:{}, steps:0, console:[]});
  }
  unlocksFor(msg) {
    const unlocks = [];
    const n = this.state.nodes.find(function(x){ return x.id === msg.executed; });
    if (n) {
      // decider requires a non-null port: a failed condition eval sends port:null
      // and never actually decided (PROTOCOL.md "Achievements", prototype parity).
      if (n.type === 'iff' && msg.port != null) unlocks.push('decider');
      if (n.type === 'loop' && msg.port === 'done') unlocks.push('looper');
    }
    return unlocks;
  }
  // Drop any active edge whose TARGET is `reachedId` — execution has now
  // actually reached the far end of it, so it's been "consumed". Edges NOT
  // targeting `reachedId` (e.g. a split's other, still-pending branch, or a
  // merge's other still-in-flight input) are left untouched — they stay lit
  // until their own target is reached by a later tick. This is what lets a
  // fan-out show both branches active at once and a merge show both incoming
  // edges lit right up until it runs, instead of one clobbering the other.
  consumeEdgesInto(activeEdges, reachedId) {
    const next = {};
    Object.keys(activeEdges).forEach(function(k){ if (activeEdges[k] !== reachedId) next[k] = activeEdges[k]; });
    return next;
  }
  onServerEvent(msg) {
    const self = this;
    if (msg.type === 'error') {
      // Not run-scoped (no runId): protocol/validation errors are always shown.
      this._pendingStart = null;
      this.setState(function(s){ return {
        console: s.console.concat([{kind:'err', text:String(msg.message)}]).slice(-200),
        running: false, paused: false, curId: null, activeEdges: {}
      }; });
      return;
    }
    // started/tick/finished echo the runId sent with start. Drop frames from any
    // other epoch — stale events crossing a Reset or a rapid re-start on the wire
    // must not repopulate a UI the user just reset (PROTOCOL.md "runId").
    if (msg.runId !== 'r' + this._runGen) return;
    if (msg.type === 'started') {
      this._pendingStart = null;
      this.setState({
        running: true, paused: msg.mode === 'step',
        curId: msg.entry, activeEdges: {},
        console: (msg.logs || []).slice(-200),
        vars: {}, steps: 0
      });
    } else if (msg.type === 'tick') {
      const unlocks = this.unlocksFor(msg);
      // `executed`/`port`/`next` are always real node ids (PROTOCOL.md) —
      // including nested-subgraph ones — so this same edge-key scheme
      // (source>port) covers top-level AND a subgraph's own inner edges
      // uniformly; clients resolve which drawn edge a key belongs to at
      // render time (buildEdgesSvg / the subgraph's mini-edges), not here.
      this.setState(function(s){
        const activeEdges = self.consumeEdgesInto(s.activeEdges, msg.executed);
        if (msg.port != null) activeEdges[msg.executed + '>' + msg.port] = msg.next;
        return {
          console: s.console.concat(msg.logs || []).slice(-200),
          vars: msg.vars || {},
          curId: msg.next, activeEdges: activeEdges, steps: msg.step
        };
      });
      unlocks.forEach(function(u){ self.unlock(u); });
    } else if (msg.type === 'finished') {
      this._pendingStart = null;
      const unlocks = this.unlocksFor(msg);
      if (msg.reason === 'end') unlocks.push('run');
      this.setState(function(s){ return {
        console: s.console.concat(msg.logs || []).slice(-200),
        vars: msg.vars || {},
        running: false, paused: false, curId: null, activeEdges: {}, steps: msg.step
      }; });
      unlocks.forEach(function(u){ self.unlock(u); });
    }
  }

  // ---------- achievements / tutorial ----------
  unlock(id) {
    if (this.state.ach[id]) return;
    const ach = Object.assign({}, this.state.ach); ach[id] = true;
    try { localStorage.setItem('flowground.ach', JSON.stringify(ach)); } catch (e) {}
    const def = this.ACHS.find(function(a){ return a.id === id; });
    this.setState({ach:ach, toast:def});
    clearTimeout(this._toastT);
    const self = this;
    this._toastT = setTimeout(function(){ self.setState({toast:null}); }, 3200);
  }
  finishTut(complete) {
    try { localStorage.setItem('flowground.tut', '1'); } catch (e) {}
    this.setState({tut:-1});
    if (complete) this.unlock('tutorial');
  }

  // ---------- export ----------
  buildFlow() {
    const st = this.state, self = this;
    const kindOf = function(t){ return self.KIND_OF[t] || 'TASK'; };
    const start = st.nodes.find(function(n){ return n.type === 'start'; });
    return {
      format: 'flowground.v1',
      entry: start ? start.id : null,
      nodes: st.nodes.map(function(n){ return {id:n.id, kind:kindOf(n.type), block:n.type, config:n.data, position:{x:n.x, y:n.y}}; }),
      edges: st.edges.map(function(e){ return {source:e.from.node, port:e.from.port, target:e.to}; })
    };
  }
  buildExport() {
    return JSON.stringify(this.buildFlow(), null, 2);
  }
  pyFor(node, edges) {
    const id = node.id, d = node.data || {};
    const out = function(port){ const e = edges.find(function(e){ return e.from.node === id && e.from.port === port; }); return e ? e.to : null; };
    const py = function(s){ return String(s || '').replace(/===/g, '==').replace(/!==/g, '!=').replace(/&&/g, ' and ').replace(/\|\|/g, ' or ').replace(/!(?![=])/g, 'not ').replace(/\btrue\b/g, 'True').replace(/\bfalse\b/g, 'False'); };
    const q = function(s){ return JSON.stringify(String(s == null ? '' : s)); };
    const route = function(t){ return t ? q(t) : 'None  # not connected'; };
    const EV = ', {"__builtins__": {}}, dict(payload))';
    const L = ['async def ' + id + '(payload):'];
    switch (node.type) {
      case 'ask':
        L.push('    # ask: save answer as ' + d.name);
        L.push('    payload[' + q(d.name) + '] = input(' + q(d.name + '? ') + ')');
        L.push('    return payload'); break;
      case 'say':
        L.push('    # say');
        L.push('    print(' + q(d.text) + '.format(**payload))');
        L.push('    return payload'); break;
      case 'set':
        L.push('    # set: ' + d.name + ' = ' + d.expr);
        L.push('    try:');
        L.push('        payload[' + q(d.name) + '] = eval(' + q(py(d.expr)) + EV);
        L.push('    except Exception:');
        L.push('        payload[' + q(d.name) + '] = ' + q(d.expr) + '.format(**payload)');
        L.push('    return payload'); break;
      case 'iff': {
        const t = out('true'), f = out('false');
        L.push('    # if: ' + d.cond + '  -> yes: ' + t + ', no: ' + f);
        L.push('    return ' + route(t) + ' if eval(' + q(py(d.cond)) + EV + ' else ' + route(f)); break; }
      case 'loop': {
        const r = out('repeat'), dn = out('done');
        if ((d.mode || 'count') === 'while') {
          L.push('    # while: ' + d.cond + '  -> again: ' + r + ', done: ' + dn);
          L.push('    return ' + route(r) + ' if eval(' + q(py(d.cond)) + EV + ' else ' + route(dn));
        } else {
          const key = '_loop_' + id, t = Math.max(0, Math.floor(Number(d.times) || 0));
          L.push('    # loop ' + t + ' times  -> again: ' + r + ', done: ' + dn);
          L.push('    c = payload.get(' + q(key) + ', 0)');
          L.push('    if c < ' + t + ':');
          L.push('        payload[' + q(key) + '] = c + 1');
          L.push('        return ' + route(r));
          L.push('    payload[' + q(key) + '] = 0');
          L.push('    return ' + route(dn));
        } break; }
      case 'fn': {
        const expr = d.fn === 'double' ? 'payload[' + q(d.arg) + '] * 2'
          : d.fn === 'square' ? 'payload[' + q(d.arg) + '] ** 2'
          : 'str(payload[' + q(d.arg) + ']).upper()';
        L.push('    # function: ' + d.result + ' = ' + d.fn + '(' + d.arg + ')');
        L.push('    payload[' + q(d.result) + '] = ' + expr);
        L.push('    return payload'); break; }
      case 'split':
        L.push('    # split (TASK): a non-SWITCH node activates ALL of its');
        L.push('    # out-edges — both ' + q(out('a')) + ' and ' + q(out('b')) + ' run.');
        L.push('    return payload'); break;
      case 'merge':
        L.push('    # merge (AGGREGATE): waits for every incoming edge, then');
        L.push('    # fires once. payload here is the LIST of upstream results.');
        L.push('    return payload'); break;
      case 'subgraph':
        L.push('    # subgraph (SUBGRAPH): LoopGraph runs its own child graph —');
        L.push('    # this node has no handler; see its config["graph"].');
        L.push('    raise NotImplementedError  # exported for reference only'); break;
      default:
        L.push('    # ' + this.TYPES[node.type].label.toLowerCase());
        L.push('    return payload');
    }
    return L.join('\n');
  }
  buildExportLG() {
    const st = this.state, self = this;
    const kindOf = function(t){ return self.KIND_OF[t] || 'TASK'; };
    const start = st.nodes.find(function(n){ return n.type === 'start'; });
    const registry = {};
    st.nodes.forEach(function(n){ registry[n.id] = self.pyFor(n, st.edges); });
    return JSON.stringify({
      format: 'loopgraph.v1',
      entry: start ? start.id : null,
      nodes: st.nodes.map(function(n){ return {id:n.id, kind:kindOf(n.type)}; }),
      edges: st.edges.map(function(e){ return {source:e.from.node, target:e.to}; }),
      function_registry: registry
    }, null, 2);
  }
  currentExport() { return this.state.exportFmt === 'lg' ? this.buildExportLG() : this.buildExport(); }
  downloadExport() {
    try {
      const blob = new Blob([this.currentExport()], {type:'application/json'});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = this.state.exportFmt === 'lg' ? 'flow.loopgraph.json' : 'flow.json'; document.body.appendChild(a); a.click();
      setTimeout(function(){ document.body.removeChild(a); URL.revokeObjectURL(url); }, 200);
    } catch (e) {}
  }
  copyExport() {
    const self = this; const txt = this.currentExport();
    const done = function(){ self.setState({copied:true}); clearTimeout(self._copyT); self._copyT = setTimeout(function(){ self.setState({copied:false}); }, 1800); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(done, function(){ done(); });
    else done();
  }

  // ---------- svg edges ----------
  pathBetween(p1, p2) {
    const x1 = p1.x, y1 = p1.y, x2 = p2.x, y2 = p2.y;
    const square = (this.props.edgeStyle || 'curved') === 'square';
    if (square) {
      if (y2 > y1 + 24) { const m = (y1 + y2) / 2; return {d:'M ' + x1 + ' ' + y1 + ' L ' + x1 + ' ' + m + ' L ' + x2 + ' ' + m + ' L ' + x2 + ' ' + y2, mid:[(x1 + x2) / 2, m]}; }
      const s = x1 <= x2 ? Math.max(24, Math.min(x1, x2) - 120) : Math.max(x1, x2) + 120;
      return {d:'M ' + x1 + ' ' + y1 + ' L ' + x1 + ' ' + (y1 + 22) + ' L ' + s + ' ' + (y1 + 22) + ' L ' + s + ' ' + (y2 - 24) + ' L ' + x2 + ' ' + (y2 - 24) + ' L ' + x2 + ' ' + y2, mid:[s, (y1 + y2) / 2]};
    }
    if (y2 > y1 - 10) { const dd = Math.max(38, (y2 - y1) / 2); return {d:'M ' + x1 + ' ' + y1 + ' C ' + x1 + ' ' + (y1 + dd) + ', ' + x2 + ' ' + (y2 - dd) + ', ' + x2 + ' ' + y2, mid:[(x1 + x2) / 2, (y1 + y2) / 2]}; }
    const s = x1 <= x2 ? Math.max(24, Math.min(x1, x2) - 130) : Math.max(x1, x2) + 130;
    const my = (y1 + y2) / 2;
    return {d:'M ' + x1 + ' ' + y1 + ' C ' + x1 + ' ' + (y1 + 66) + ', ' + s + ' ' + (y1 + 50) + ', ' + s + ' ' + my + ' C ' + s + ' ' + (y2 - 50) + ', ' + x2 + ' ' + (y2 - 64) + ', ' + x2 + ' ' + y2, mid:[s, my]};
  }
  buildEdgesSvg() {
    const st = this.state, self = this, acc = this.acc();
    const mk = function(id, c) {
      return React.createElement('marker', {id:id, key:id, viewBox:'0 0 10 10', refX:8, refY:5, markerWidth:6.5, markerHeight:6.5, orient:'auto-start-reverse'},
        React.createElement('path', {d:'M 1 1 L 9 5 L 1 9', fill:'none', stroke:c, strokeWidth:2, strokeLinecap:'round', strokeLinejoin:'round'}));
    };
    const kids = [React.createElement('defs', {key:'defs'}, mk('ahd', '#C9B99F'), mk('aha', acc), mk('ahs', '#43382E'))];
    const byId = {}; st.nodes.forEach(function(n){ byId[n.id] = n; });
    st.edges.forEach(function(e) {
      const a = byId[e.from.node], b = byId[e.to]; if (!a || !b) return;
      const back = b.y < a.y + 30;
      const p1 = self.outAnchor(a, e.from.port);
      const p2 = {x: b.x + self.boxSizeFor(b).w / 2 + (back ? 36 : 0), y: b.y - 2};
      const pb = self.pathBetween(p1, p2);
      const active = st.running && st.activeEdges[e.from.node + '>' + e.from.port] === e.to;
      const sel = st.selEdge === e.id;
      const col = active ? acc : (sel ? '#43382E' : '#C9B99F');
      const marker = active ? 'aha' : (sel ? 'ahs' : 'ahd');
      const g = [
        React.createElement('path', {key:'hit', d:pb.d, stroke:'transparent', strokeWidth:16, fill:'none',
          style:{pointerEvents:'stroke', cursor:'pointer'},
          onClick:function(ev){ ev.stopPropagation(); self.setState({selEdge:e.id, selNode:null}); }}),
        React.createElement('path', {key:'vis', d:pb.d, stroke:col, strokeWidth:2.5, fill:'none', markerEnd:'url(#' + marker + ')',
          strokeLinecap:'round', strokeDasharray: active ? '8 6' : null,
          style: active ? {animation:'flowdash .55s linear infinite'} : null})
      ];
      if (sel) {
        g.push(React.createElement('g', {key:'del', style:{pointerEvents:'auto', cursor:'pointer'},
          onClick:function(ev){ ev.stopPropagation(); self.setState(function(s){ return {edges:s.edges.filter(function(x){ return x.id !== e.id; }), selEdge:null}; }); }},
          React.createElement('circle', {cx:pb.mid[0], cy:pb.mid[1], r:9, fill:'#C4553B'}),
          React.createElement('line', {x1:pb.mid[0]-3.2, y1:pb.mid[1]-3.2, x2:pb.mid[0]+3.2, y2:pb.mid[1]+3.2, stroke:'#FFF', strokeWidth:2, strokeLinecap:'round'}),
          React.createElement('line', {x1:pb.mid[0]+3.2, y1:pb.mid[1]-3.2, x2:pb.mid[0]-3.2, y2:pb.mid[1]+3.2, stroke:'#FFF', strokeWidth:2, strokeLinecap:'round'})));
      }
      kids.push(React.createElement('g', {key:e.id}, g));
    });
    if (st.pend) {
      const a = byId[st.pend.from.node];
      if (a) {
        const p1 = this.outAnchor(a, st.pend.from.port);
        const pb = this.pathBetween(p1, {x:st.pend.x, y:st.pend.y});
        kids.push(React.createElement('g', {key:'pend'},
          React.createElement('path', {d:pb.d, stroke:acc, strokeWidth:2.5, fill:'none', strokeDasharray:'6 6', strokeLinecap:'round'}),
          React.createElement('circle', {cx:st.pend.x, cy:st.pend.y, r:5, fill:acc})));
      }
    }
    return React.createElement('svg', {width:1600, height:1400,
      style:{position:'absolute', left:0, top:0, pointerEvents:'none', zIndex:1, overflow:'visible'}}, kids);
  }

  // ---------- render values ----------
  renderVals() {
    const st = this.state, self = this, acc = this.acc();

    const chip = function(color, size) {
      return {width:size, height:size, borderRadius:Math.round(size*0.3), background:color, color:'#FFF',
        display:'grid', placeItems:'center', font:"800 " + Math.round(size*0.47) + "px 'Nunito',sans-serif", flexShrink:0};
    };

    const palette = this.ORDER.map(function(t) {
      const T = self.TYPES[t];
      return {label:T.label, desc:T.desc, glyph:T.glyph, chipStyle:chip(T.color, 30),
        onMouseDown:function(e){ self.onPaletteDown(t, e); }};
    });

    const subOf = function(n) {
      const d = n.data;
      switch (n.type) {
        case 'ask':  return d.name + ' ← "' + d.value + '"';
        case 'say':  return '"' + d.text + '"';
        case 'set':  return d.name + ' = ' + d.expr;
        case 'iff':  return d.cond + ' ?';
        case 'loop': return (d.mode === 'while') ? 'while ' + d.cond : d.times + '× around';
        case 'fn':   return d.result + ' = ' + d.fn + '(' + d.arg + ')';
        case 'start':return 'entry point';
        case 'split':return 'run both branches';
        case 'merge':return 'wait for both, then continue';
        case 'subgraph': {
          let times = '2';
          try { times = (JSON.parse(d.graph).nodes.find(function(x){ return x.block === 'loop'; }) || {}).config.times || times; } catch (e) {}
          return 'nested ' + times + '× loop';
        }
        case 'end':  return 'all done';
        default: return '';
      }
    };

    // A subgraph block shows its REAL inner nodes/edges (PROTOCOL.md: ticks
    // carry true inner ids, never remapped to the block's own id) instead of
    // an opaque box, so the run can be watched inside it with the same
    // fidelity as the main canvas.
    const buildMini = function(n) {
      let graphDef; try { graphDef = JSON.parse(n.data.graph); } catch (e) { return null; }
      const L = self.miniLayout(graphDef);
      const HEAD = 30;
      const miniNodes = L.order.map(function(id) {
        const gn = L.byId[id];
        const mt = self.TYPES[gn.block] || {glyph:'?', color:'#8B8178'};
        const p = L.pos[id];
        const on = st.running && st.curId === id;
        return {
          id: id, label: mt.glyph, title: gn.id,
          style: {position:'absolute', left:p.x - 26, top:p.y + HEAD - 15, width:52, height:30,
            borderRadius:8, background:'#FFFDF8', display:'grid', placeItems:'center',
            border:'1.5px solid ' + (on ? acc : mt.color + '80'),
            boxShadow: on ? '0 0 0 3px ' + acc + '38' : 'none',
            font:"800 13px 'Nunito',sans-serif", color: mt.color, zIndex:2,
            transition:'box-shadow .2s, border-color .2s'}
        };
      });
      const miniEdges = L.edges.map(function(e, i) {
        const p1 = L.pos[e.source], p2 = L.pos[e.target];
        const on = st.running && st.activeEdges[e.source + '>' + e.port] === e.target;
        // A back-edge (loop-back) points to an EARLIER layer — connect the
        // two nodes' right sides with a rightward bulge, instead of the
        // straight top-to-bottom line forward edges use.
        const d = e.back
          ? 'M ' + (p1.x + 26) + ' ' + (p1.y + HEAD) + ' C ' + (p1.x + 66) + ' ' + (p1.y + HEAD) + ', '
              + (p2.x + 66) + ' ' + (p2.y + HEAD) + ', ' + (p2.x + 26) + ' ' + (p2.y + HEAD)
          : 'M ' + p1.x + ' ' + (p1.y + HEAD + 15) + ' L ' + p2.x + ' ' + (p2.y + HEAD - 15);
        return {key:'me' + i, d:d, stroke: on ? acc : '#D8C7AE', strokeWidth: on ? 2.5 : 1.75,
          dash: on ? '7 5' : null, animate: on};
      });
      return {width:L.width, height:L.height + HEAD, headerH:HEAD, order:L.order,
        nodes:miniNodes, edges:miniEdges};
    };

    const nodes = st.nodes.map(function(n) {
      const T = self.TYPES[n.type];
      const sel = st.selNode === n.id;
      const mini = n.type === 'subgraph' ? buildMini(n) : null;
      const sz = self.boxSizeFor(n);
      const active = st.running && (st.curId === n.id || (mini && mini.order.indexOf(st.curId) !== -1));
      const ps = self.portsOf(n.type);
      return {
        id: n.id, glyph: T.glyph, title: T.label, sub: subOf(n), mini: mini,
        chipStyle: chip(T.color, 30),
        wrapStyle: {position:'absolute', left:n.x, top:n.y, width:sz.w, height:sz.h, boxSizing:'border-box',
          display: mini ? 'block' : 'flex', alignItems:'center', gap:10,
          padding: mini ? 0 : '0 12px', background: mini ? '#FBF6ED' : '#FFFDF8',
          border:'1.5px solid ' + (active ? acc : (sel ? '#43382E' : T.color + '59')), borderRadius:14,
          cursor:'grab', userSelect:'none', zIndex: sel || active ? 3 : 2,
          boxShadow: active ? '0 0 0 4px ' + acc + '40, 0 8px 20px rgba(120,70,30,.2)'
                            : (sel ? '0 6px 16px rgba(90,60,30,.16)' : '0 2px 6px rgba(120,80,40,.08)'),
          transition:'box-shadow .2s, border-color .2s'},
        headerStyle: {position:'absolute', left:0, top:0, right:0, height:mini ? mini.headerH : 0,
          display:'flex', alignItems:'center', gap:7, padding:'0 10px', borderBottom:'1.5px dashed ' + T.color + '40'},
        miniAreaStyle: {position:'absolute', left:0, top:0, right:0, bottom:0},
        portRowStyle: {position:'absolute', top:sz.h - 7, left:0, right:0, display:'flex',
          justifyContent: ps.length === 2 ? 'space-between' : 'center', padding: ps.length === 2 ? '0 30px' : 0, pointerEvents:'none'},
        ports: ps.map(function(p) {
          return {label:p.label,
            dotStyle:{width:14, height:14, borderRadius:'50%', background:'#FFFDF8', border:'2.5px solid ' + p.color,
              cursor:'crosshair', boxSizing:'border-box', pointerEvents:'auto'},
            labelStyle:{font:"800 9px 'Nunito',sans-serif", textTransform:'uppercase', letterSpacing:'.06em', color:p.color},
            onMouseDown:function(e){ self.onPortDown(n.id, p.port, e); }};
        }),
        onMouseDown:function(e){ self.onNodeDown(n.id, e); }
      };
    });

    // inspector
    const selN = st.nodes.find(function(n){ return n.id === st.selNode; });
    let inspFields = [], inspHint = '', inspTitle = '', inspGlyph = '', inspChipStyle = null;
    if (selN) {
      const T = this.TYPES[selN.type];
      inspTitle = T.label + ' block'; inspGlyph = T.glyph; inspChipStyle = chip(T.color, 28);
      const field = function(key, label) {
        return {label:label, isText:true, isSelect:false, value:String(selN.data[key] == null ? '' : selN.data[key]),
          onChange:function(ev){ const v = ev.target.value;
            self.setState(function(s){ return {nodes: s.nodes.map(function(n){ return n.id === selN.id ? Object.assign({}, n, {data:Object.assign({}, n.data, (function(){ const o = {}; o[key] = v; return o; })())}) : n; })}; }); }};
      };
      const selectField = function(key, label, options) {
        const f = field(key, label); f.isText = false; f.isSelect = true; f.options = options; return f;
      };
      switch (selN.type) {
        case 'ask': inspFields = [field('name', 'Save answer as'), field('value', 'Sample answer')];
          inspHint = 'In a real app the user types the answer — here you choose it in advance.'; break;
        case 'say': inspFields = [field('text', 'Message')];
          inspHint = 'Wrap a variable in {curly braces} to drop it into your sentence.'; break;
        case 'set': inspFields = [field('name', 'Variable name'), field('expr', 'Value')];
          inspHint = 'Math (lap + 1), text (hello or hi {name}), or true / false.'; break;
        case 'iff': inspFields = [field('cond', 'Question to ask')];
          inspHint = 'Try: count > 3   or   name == "Ada". Yes goes left, no goes right.'; break;
        case 'loop': {
          const mode = selN.data.mode || 'count';
          const mf = selectField('mode', 'Loop kind', ['count', 'while']); mf.value = mode;
          mf.onChange = function(ev){ const v = ev.target.value;
            self.setState(function(s){ return {nodes: s.nodes.map(function(n){ if (n.id !== selN.id) return n;
              const d = Object.assign({}, n.data, {mode:v});
              if (v === 'while' && !d.cond) d.cond = 'lap < 4';
              if (v === 'count' && !d.times) d.times = '3';
              return Object.assign({}, n, {data:d}); })}; }); };
          inspFields = mode === 'while' ? [mf, field('cond', 'Keep going while')] : [mf, field('times', 'Times around')];
          inspHint = mode === 'while' ? 'A real while-loop: repeats as long as this is true. Change a variable inside the loop — or it never stops!'
                                      : 'A for-loop: goes around a fixed number of times. Wire the last block of the loop back into this one.';
          break; }
        case 'fn': inspFields = [selectField('fn', 'Mini-machine', ['double', 'square', 'shout']), field('arg', 'Give it'), field('result', 'Save result as')];
          inspHint = 'double ×2 · square x·x · shout MAKES IT LOUD'; break;
        case 'start': inspHint = 'Every flow begins here. There is nothing to set.'; break;
        case 'split': inspHint = 'Both of its arrows fire at once — LoopGraph runs branch A and branch B, one after the other, before anything downstream of both can continue.'; break;
        case 'merge': inspHint = 'Waits for every branch that arrows into it to finish, then continues once — wire both branches of a Split here to join them back up.'; break;
        case 'subgraph': inspHint = 'A whole mini-flow packed into one block — this one contains its own 2× loop, run by LoopGraph as a real nested sub-workflow. Nested editing isn’t supported yet, so its inside is fixed.'; break;
        case 'end': inspHint = 'When the flow reaches this block, it stops.'; break;
      }
    }

    // console + vars
    const KIND = {
      info:   {c:'#8A7B6B', g:'·',  gc:'#C9B99F', w:600},
      step:   {c:'#5F5346', g:'▸',  gc:'#C0A87E', w:600},
      out:    {c:'#43382E', g:'»',  gc:acc,       w:800},
      branch: {c:'#8A5B74', g:'◆',  gc:'#B0708F', w:700},
      loop:   {c:'#9A5335', g:'↺',  gc:'#B65C3F', w:700},
      ok:     {c:'#4F7A54', g:'✓',  gc:'#6E9A72', w:800},
      err:    {c:'#C4553B', g:'!',  gc:'#C4553B', w:700},
      warn:   {c:'#A1751F', g:'!',  gc:'#D9A521', w:700}
    };
    const consoleLines = st.console.map(function(l) {
      const k = KIND[l.kind] || KIND.info;
      return {text:l.text, glyph:k.g,
        style:{display:'flex', gap:8, padding:'2.5px 0', font:k.w + " 12px ui-monospace,Menlo,monospace", color:k.c, lineHeight:1.45},
        glyphStyle:{width:12, textAlign:'center', color:k.gc, flexShrink:0}};
    });
    const varsList = Object.keys(st.vars).map(function(k){ return {name:k, value:self.fmt(st.vars[k])}; });

    // header
    const achs = this.ACHS.map(function(a) {
      const on = !!st.ach[a.id];
      return {title: a.label + ' — ' + a.desc + (on ? '' : ' (locked)'),
        style:{width:26, height:26, borderRadius:'50%', display:'grid', placeItems:'center', fontSize:11.5, cursor:'default',
          background: on ? '#F2B63C' : '#F4EBDC', color: on ? '#7A5A12' : '#D3C3A9',
          border: on ? '1.5px solid #D99C22' : '1.5px dashed #D8C7AE', boxSizing:'border-box'}};
    });
    const speeds = this.SPEEDS.map(function(sp, i) {
      const on = st.speedIx === i;
      return {label:sp.label,
        style:{border:'none', borderRadius:8, padding:'4px 9px', cursor:'pointer',
          font:"800 11.5px 'Nunito',sans-serif", background: on ? '#FFFDF8' : 'transparent',
          color: on ? '#43382E' : '#A08F79', boxShadow: on ? '0 1px 3px rgba(90,60,30,.15)' : 'none'},
        onClick:function(){ self.setState({speedIx:i}, function(){ if (self.state.running && self._rc) self._rc.send({type:'set_speed', speed:i}); }); }};
    });

    // texture
    const tex = this.props.canvasTexture || 'dots';
    const textureStyle = {position:'absolute', inset:0, pointerEvents:'none', zIndex:0,
      backgroundImage: tex === 'dots' ? 'radial-gradient(#E3D3BB 1.2px, transparent 1.2px)'
        : tex === 'grid' ? 'linear-gradient(#F0E3CD 1px, transparent 1px), linear-gradient(90deg, #F0E3CD 1px, transparent 1px)' : 'none',
      backgroundSize:'26px 26px'};

    // ghost
    const g = st.ghost;
    const gT = g ? this.TYPES[g.type] : null;

    // tutorial
    const tut = st.tut >= 0 ? this.TUT[st.tut] : null;
    const tutDots = this.TUT.map(function(_, i) {
      return {style:{width: st.tut === i ? 16 : 6, height:6, borderRadius:3, background: st.tut === i ? acc : '#E4D5BF', transition:'all .2s'}};
    });

    return {
      canvasRef: this.canvasRef, consoleRef: this.consoleRef,
      palette: palette, nodes: nodes, edgesSvg: this.buildEdgesSvg(), textureStyle: textureStyle,
      onCanvasDown: function(e){ if (e.target === self.canvasRef.current) self.setState({selNode:null, selEdge:null}); },

      inspectorOpen: !!selN, inspTitle: inspTitle, inspGlyph: inspGlyph, inspChipStyle: inspChipStyle,
      inspFields: inspFields, inspHint: inspHint,
      onDeleteNode: function(){ if (selN) self.deleteNode(selN.id); },

      runLabel: !st.running ? '▶  Run' : (st.paused ? '▶  Resume' : '❚❚  Pause'),
      runBtnStyle: {background:acc, border:'none', borderRadius:11, padding:'8px 18px', font:"800 13px 'Nunito',sans-serif",
        color:'#FFF', cursor:'pointer', boxShadow:'0 3px 10px ' + acc + '55', minWidth:104},
      onRun: function(){ self.onRunClick(); },
      onStep: function(){ self.onStepClick(); },
      onReset: function(){ self.onResetClick(); },
      speeds: speeds,
      runStatus: st.running ? ('step ' + st.steps + (st.paused ? ' · paused' : '')) : '',

      achs: achs,
      onTutorial: function(){ self.setState({tut:0}); },

      exportOn: st.exportOn,
      exportJson: st.exportOn ? this.currentExport() : '',
      exportTabs: [{id:'lg', label:'LoopGraph + Python'}, {id:'fg', label:'Flowground'}].map(function(t) {
        const on = st.exportFmt === t.id;
        return {label:t.label,
          style:{border:'none', borderRadius:8, padding:'5px 12px', cursor:'pointer',
            font:"800 12px 'Nunito',sans-serif", background: on ? '#FFFDF8' : 'transparent',
            color: on ? '#43382E' : '#A08F79', boxShadow: on ? '0 1px 3px rgba(90,60,30,.15)' : 'none'},
          onClick:function(){ self.setState({exportFmt:t.id, copied:false}); }};
      }),
      exportDesc: st.exportFmt === 'lg'
        ? 'Graph for the LoopGraph engine (nodes, edges, entry) plus a function_registry table — real async Python handlers, one per block. If and Loop blocks become SWITCH routers.'
        : 'Flowground’s own format: blocks with config, ports and canvas positions.',
      onExport: function(){ self.setState({exportOn:true, copied:false}); },
      onExportClose: function(){ self.setState({exportOn:false}); },
      onExportCopy: function(){ self.copyExport(); },
      onExportDownload: function(){ self.downloadExport(); },
      copyLabel: st.copied ? 'Copied!' : 'Copy',

      varsList: varsList, varsEmpty: varsList.length === 0,
      consoleLines: consoleLines, consoleEmpty: consoleLines.length === 0,

      ghost: !!g,
      ghostStyle: g ? {position:'fixed', left:g.x + 12, top:g.y + 8, zIndex:70, display:'flex', alignItems:'center', gap:8,
        padding:'8px 12px', background:'#FFFDF8', border:'1.5px solid #E4D5BF', borderRadius:12,
        boxShadow:'0 10px 24px rgba(90,60,30,.22)', pointerEvents:'none'} : null,
      ghostChipStyle: gT ? chip(gT.color, 24) : null,
      ghostGlyph: gT ? gT.glyph : '', ghostLabel: gT ? gT.label : '',

      toast: !!st.toast,
      toastTitle: st.toast ? st.toast.label : '', toastDesc: st.toast ? st.toast.desc : '',

      tutOn: !!tut,
      tutStyle: tut ? Object.assign({position:'fixed', width:330, background:'#FFFDF8', borderRadius:18, padding:'18px 18px 12px',
        zIndex:51, boxShadow:'0 24px 60px rgba(50,30,10,.4)', display:'flex', flexDirection:'column', gap:7, animation:'fadein .25s'}, tut.pos) : null,
      tutStepLabel: tut ? ('Tip ' + (st.tut + 1) + ' of ' + this.TUT.length) : '',
      tutTitle: tut ? tut.t : '', tutBody: tut ? tut.b : '',
      tutNextLabel: tut ? tut.next : '',
      tutNextStyle: {background:acc, border:'none', borderRadius:10, padding:'8px 16px', font:"800 12.5px 'Nunito',sans-serif", color:'#FFF', cursor:'pointer'},
      tutDots: tutDots,
      onTutNext: function(){ if (st.tut >= self.TUT.length - 1) self.finishTut(true); else self.setState({tut:st.tut + 1}); },
      onTutSkip: function(){ self.finishTut(false); }
    };
  }

  // ---------- render ----------
  render() {
    const v = this.renderVals();
    return (
      <div style={{height:'100vh',display:'grid',gridTemplateRows:'56px minmax(0,1fr)',overflow:'hidden'}} data-screen-label="Playground">

        <div style={{display:'flex',alignItems:'center',gap:16,padding:'0 16px',background:'#FFFDF8',borderBottom:'1.5px solid #EADCC8',zIndex:10}}>
          <div style={{display:'flex',alignItems:'center',gap:10,minWidth:210}}>
            <div style={{width:32,height:32,borderRadius:10,background:'#E8684A',display:'grid',placeItems:'center',color:'#FFF',font:"900 15px 'Nunito',sans-serif",boxShadow:'0 3px 8px rgba(232,104,74,.35)'}}>⌁</div>
            <div style={{display:'flex',flexDirection:'column',lineHeight:1.15}}>
              <span style={{font:"900 15px 'Nunito',sans-serif",color:'#43382E'}}>Flowground</span>
              <span style={{font:"700 10.5px 'Nunito',sans-serif",color:'#B3A186'}}>learn logic by drawing it</span>
            </div>
          </div>
          <div style={{flex:1}}></div>
          <div style={{display:'flex',alignItems:'center',gap:8}} data-screen-label="Run controls">
            <button onClick={v.onRun} style={v.runBtnStyle}>{v.runLabel}</button>
            <button onClick={v.onStep} style={{background:'#FFFDF8',border:'1.5px solid #E4D5BF',borderRadius:11,padding:'7px 14px',font:"800 13px 'Nunito',sans-serif",color:'#5F5346',cursor:'pointer'}}>Step</button>
            <button onClick={v.onReset} style={{background:'#FFFDF8',border:'1.5px solid #E4D5BF',borderRadius:11,padding:'7px 14px',font:"800 13px 'Nunito',sans-serif",color:'#5F5346',cursor:'pointer'}}>Reset</button>
            <div style={{display:'flex',background:'#F1E7D6',borderRadius:11,padding:3,gap:2}}>
              {v.speeds.map((s, i) => (
                <button key={i} onClick={s.onClick} style={s.style}>{s.label}</button>
              ))}
            </div>
            <span style={{font:"700 12px 'Nunito',sans-serif",color:'#A08F79',minWidth:84}}>{v.runStatus}</span>
          </div>
          <div style={{flex:1}}></div>
          <div style={{display:'flex',gap:6,alignItems:'center'}} data-screen-label="Achievements">
            <button onClick={v.onExport} title="Export this flow as JSON" style={{background:'#FFFDF8',border:'1.5px solid #E4D5BF',borderRadius:11,padding:'7px 14px',font:"800 13px 'Nunito',sans-serif",color:'#5F5346',cursor:'pointer',marginRight:6}}>Export JSON</button>
            {v.achs.map((a, i) => (
              <div key={i} title={a.title} style={a.style}>★</div>
            ))}
            <button onClick={v.onTutorial} title="Replay the tutorial" style={{width:28,height:28,marginLeft:6,borderRadius:'50%',border:'1.5px solid #E4D5BF',background:'#FFFDF8',color:'#A08F79',font:"800 13px 'Nunito',sans-serif",cursor:'pointer'}}>?</button>
          </div>
        </div>

        <div style={{display:'grid',gridTemplateColumns:'222px minmax(0,1fr) 292px',minHeight:0}}>

          <div data-screen-label="Block palette" style={{background:'#FFFDF8',borderRight:'1.5px solid #EADCC8',padding:'14px 12px',display:'flex',flexDirection:'column',gap:7,overflowY:'auto'}}>
            <div style={{font:"800 11px 'Nunito',sans-serif",letterSpacing:'.12em',textTransform:'uppercase',color:'#A08F79',marginBottom:3}}>Blocks</div>
            {v.palette.map((b, i) => (
              <div key={i} className="pal-item" onMouseDown={b.onMouseDown} title="Drag onto the canvas, or click to add" style={{display:'flex',gap:10,alignItems:'center',padding:'8px 10px',background:'#FFF',border:'1.5px solid #EFE3D0',borderRadius:12,cursor:'grab',userSelect:'none'}}>
                <div style={b.chipStyle}>{b.glyph}</div>
                <div style={{display:'flex',flexDirection:'column',lineHeight:1.2,minWidth:0}}>
                  <span style={{font:"800 13px 'Nunito',sans-serif",color:'#43382E'}}>{b.label}</span>
                  <span style={{font:"600 10.5px 'Nunito',sans-serif",color:'#A5947C',whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}}>{b.desc}</span>
                </div>
              </div>
            ))}
            <div style={{marginTop:'auto',padding:10,background:'#FBF4E7',borderRadius:12,font:"600 11.5px/1.5 'Nunito',sans-serif",color:'#A5947C'}}>Drag from the dot under a block to another block to draw an arrow.</div>
          </div>

          <div style={{position:'relative',minWidth:0,minHeight:0}} data-screen-label="Canvas">
            <div style={{position:'absolute',inset:0,overflow:'auto'}}>
              <div ref={v.canvasRef} onMouseDown={v.onCanvasDown} style={{position:'relative',width:1600,height:1400,background:'#FBF6ED'}}>
                <div style={v.textureStyle}></div>
                {v.edgesSvg}
                {v.nodes.map((n) => (
                  <div key={n.id} onMouseDown={n.onMouseDown} style={n.wrapStyle}>
                    {n.mini ? (
                      <React.Fragment>
                        <div style={n.headerStyle}>
                          <div style={n.chipStyle}>{n.glyph}</div>
                          <span style={{font:"800 12px 'Nunito',sans-serif",color:'#43382E',whiteSpace:'nowrap'}}>{n.title}</span>
                        </div>
                        <svg width={n.mini.width} height={n.mini.height} style={{position:'absolute',left:0,top:0,pointerEvents:'none',overflow:'visible'}}>
                          {n.mini.edges.map((e) => (
                            <path key={e.key} d={e.d} stroke={e.stroke} strokeWidth={e.strokeWidth} fill="none"
                              strokeDasharray={e.dash} strokeLinecap="round"
                              style={e.animate ? {animation:'flowdash .55s linear infinite'} : null}></path>
                          ))}
                        </svg>
                        {n.mini.nodes.map((mn) => (
                          <div key={mn.id} title={mn.title} style={mn.style}>{mn.label}</div>
                        ))}
                      </React.Fragment>
                    ) : (
                      <React.Fragment>
                        <div style={n.chipStyle}>{n.glyph}</div>
                        <div style={{display:'flex',flexDirection:'column',gap:1,minWidth:0,flex:1}}>
                          <div style={{font:"800 13px 'Nunito',sans-serif",color:'#43382E',whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}}>{n.title}</div>
                          {n.sub ? (
                            <div style={{font:'600 10.5px ui-monospace,Menlo,monospace',color:'#93826D',whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}}>{n.sub}</div>
                          ) : null}
                        </div>
                      </React.Fragment>
                    )}
                    <div style={n.portRowStyle}>
                      {n.ports.map((p, i) => (
                        <div key={i} style={{display:'flex',flexDirection:'column',alignItems:'center',gap:1}}>
                          <div onMouseDown={p.onMouseDown} title="Drag to connect" style={p.dotStyle}></div>
                          {p.label ? (
                            <span style={p.labelStyle}>{p.label}</span>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {v.inspectorOpen ? (
              <div data-screen-label="Block inspector" style={{position:'absolute',top:14,right:14,width:252,background:'#FFFDF8',border:'1.5px solid #E7D9C4',borderRadius:16,boxShadow:'0 12px 32px rgba(90,60,30,.16)',padding:14,zIndex:6,display:'flex',flexDirection:'column',gap:10,animation:'fadein .18s'}}>
                <div style={{display:'flex',alignItems:'center',gap:9}}>
                  <div style={v.inspChipStyle}>{v.inspGlyph}</div>
                  <div style={{font:"800 14px 'Nunito',sans-serif",color:'#43382E'}}>{v.inspTitle}</div>
                </div>
                {v.inspFields.map((f, i) => (
                  <div key={i} style={{display:'flex',flexDirection:'column',gap:4}}>
                    <label style={{font:"800 10.5px 'Nunito',sans-serif",letterSpacing:'.08em',textTransform:'uppercase',color:'#A08F79'}}>{f.label}</label>
                    {f.isSelect ? (
                      <select value={f.value} onChange={f.onChange} style={{border:'1.5px solid #E7D9C4',borderRadius:10,padding:'7px 9px',font:'700 12.5px ui-monospace,Menlo,monospace',color:'#43382E',background:'#FFF'}}>
                        {f.options.map((o) => (<option key={o} value={o}>{o}</option>))}
                      </select>
                    ) : null}
                    {f.isText ? (
                      <input value={f.value} onChange={f.onChange} spellCheck={false} style={{border:'1.5px solid #E7D9C4',borderRadius:10,padding:'7px 9px',font:'700 12.5px ui-monospace,Menlo,monospace',color:'#43382E',background:'#FFF',minWidth:0}} />
                    ) : null}
                  </div>
                ))}
                {v.inspHint ? (
                  <div style={{font:"600 11px/1.5 'Nunito',sans-serif",color:'#A5947C',background:'#FBF4E7',borderRadius:10,padding:'8px 10px'}}>{v.inspHint}</div>
                ) : null}
                <button onClick={v.onDeleteNode} style={{background:'#FFF6F2',border:'1.5px solid #EFC7B8',borderRadius:10,padding:7,font:"800 12px 'Nunito',sans-serif",color:'#C4553B',cursor:'pointer'}}>Remove block</button>
              </div>
            ) : null}
          </div>

          <div data-screen-label="Run panel" style={{background:'#FFFDF8',borderLeft:'1.5px solid #EADCC8',display:'grid',gridTemplateRows:'auto minmax(0,1fr)',minHeight:0}}>
            <div style={{padding:'14px 14px 12px',borderBottom:'1.5px solid #F0E4D2',display:'flex',flexDirection:'column',gap:9}}>
              <div style={{font:"800 11px 'Nunito',sans-serif",letterSpacing:'.12em',textTransform:'uppercase',color:'#A08F79'}}>Variables</div>
              {v.varsEmpty ? (
                <div style={{font:"600 12px 'Nunito',sans-serif",color:'#C0B09A'}}>Nothing remembered yet — run the flow.</div>
              ) : null}
              <div style={{display:'flex',flexWrap:'wrap',gap:6}}>
                {v.varsList.map((vr) => (
                  <div key={vr.name} style={{display:'flex',alignItems:'center',gap:5,background:'#FBF4E7',border:'1.5px solid #EFDFC6',borderRadius:9,padding:'4px 9px',font:'700 12px ui-monospace,Menlo,monospace'}}>
                    <span style={{color:'#8A6D3B'}}>{vr.name}</span><span style={{color:'#C9B99F'}}>=</span><span style={{color:'#43382E',fontWeight:800}}>{vr.value}</span>
                  </div>
                ))}
              </div>
            </div>
            <div style={{display:'grid',gridTemplateRows:'auto minmax(0,1fr)',minHeight:0}}>
              <div style={{padding:'12px 14px 8px',font:"800 11px 'Nunito',sans-serif",letterSpacing:'.12em',textTransform:'uppercase',color:'#A08F79'}}>Console</div>
              <div ref={v.consoleRef} style={{overflowY:'auto',padding:'0 14px 14px',display:'flex',flexDirection:'column'}}>
                {v.consoleEmpty ? (
                  <div style={{font:"600 12px/1.6 'Nunito',sans-serif",color:'#C0B09A'}}>Press Run and watch your flow think out loud.</div>
                ) : null}
                {v.consoleLines.map((l, i) => (
                  <div key={i} style={l.style}><span style={l.glyphStyle}>{l.glyph}</span><span style={{minWidth:0}}>{l.text}</span></div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {v.ghost ? (
          <div style={v.ghostStyle}>
            <div style={v.ghostChipStyle}>{v.ghostGlyph}</div>
            <span style={{font:"800 12.5px 'Nunito',sans-serif",color:'#43382E'}}>{v.ghostLabel}</span>
          </div>
        ) : null}

        {v.toast ? (
          <div style={{position:'fixed',bottom:26,left:'50%',transform:'translateX(-50%)',zIndex:60,display:'flex',alignItems:'center',gap:11,background:'#43382E',borderRadius:14,padding:'11px 16px',boxShadow:'0 14px 34px rgba(50,30,10,.35)',animation:'toastin .3s ease-out'}}>
            <div style={{width:30,height:30,borderRadius:'50%',background:'#F2B63C',display:'grid',placeItems:'center',color:'#7A5A12',fontSize:14}}>★</div>
            <div style={{display:'flex',flexDirection:'column',lineHeight:1.25}}>
              <span style={{font:"700 10.5px 'Nunito',sans-serif",letterSpacing:'.1em',textTransform:'uppercase',color:'#C9B99F'}}>Achievement unlocked</span>
              <span style={{font:"800 13.5px 'Nunito',sans-serif",color:'#FFFDF8'}}>{v.toastTitle} — {v.toastDesc}</span>
            </div>
          </div>
        ) : null}

        {v.exportOn ? (
          <React.Fragment>
            <div onClick={v.onExportClose} style={{position:'fixed',inset:0,background:'rgba(52,36,22,.42)',zIndex:55,animation:'fadein .2s'}}></div>
            <div data-screen-label="Export JSON" style={{position:'fixed',left:'50%',top:'50%',transform:'translate(-50%,-50%)',width:520,maxWidth:'90vw',background:'#FFFDF8',borderRadius:18,padding:18,zIndex:56,boxShadow:'0 24px 60px rgba(50,30,10,.4)',display:'flex',flexDirection:'column',gap:10,animation:'fadein .2s'}}>
              <div style={{display:'flex',alignItems:'center',gap:8}}>
                <div style={{font:"900 16px 'Nunito',sans-serif",color:'#43382E',flex:1}}>Export flow as JSON</div>
                <button onClick={v.onExportClose} style={{background:'none',border:'none',font:"800 15px 'Nunito',sans-serif",color:'#A08F79',cursor:'pointer',padding:'4px 8px'}}>✕</button>
              </div>
              <div style={{display:'flex',background:'#F1E7D6',borderRadius:11,padding:3,gap:2,alignSelf:'flex-start'}}>
                {v.exportTabs.map((t, i) => (
                  <button key={i} onClick={t.onClick} style={t.style}>{t.label}</button>
                ))}
              </div>
              <div style={{font:"600 12px/1.5 'Nunito',sans-serif",color:'#A5947C'}}>{v.exportDesc}</div>
              <textarea readOnly value={v.exportJson} style={{width:'100%',boxSizing:'border-box',height:260,resize:'vertical',border:'1.5px solid #E7D9C4',borderRadius:12,padding:10,font:'600 11.5px/1.5 ui-monospace,Menlo,monospace',color:'#43382E',background:'#FBF6ED'}}></textarea>
              <div style={{display:'flex',gap:8,justifyContent:'flex-end'}}>
                <button onClick={v.onExportCopy} style={{background:'#FFFDF8',border:'1.5px solid #E4D5BF',borderRadius:11,padding:'8px 16px',font:"800 13px 'Nunito',sans-serif",color:'#5F5346',cursor:'pointer',minWidth:88}}>{v.copyLabel}</button>
                <button onClick={v.onExportDownload} style={v.runBtnStyle}>Download .json</button>
              </div>
            </div>
          </React.Fragment>
        ) : null}

        {v.tutOn ? (
          <React.Fragment>
            <div style={{position:'fixed',inset:0,background:'rgba(52,36,22,.42)',zIndex:50,animation:'fadein .25s'}}></div>
            <div data-screen-label="Tutorial" style={v.tutStyle}>
              <div style={{font:"800 10.5px 'Nunito',sans-serif",letterSpacing:'.12em',textTransform:'uppercase',color:'#C4553B'}}>{v.tutStepLabel}</div>
              <div style={{font:"900 17px 'Nunito',sans-serif",color:'#43382E'}}>{v.tutTitle}</div>
              <div style={{font:"600 13px/1.55 'Nunito',sans-serif",color:'#6E6152'}}>{v.tutBody}</div>
              <div style={{display:'flex',alignItems:'center',gap:5,marginTop:6}}>
                {v.tutDots.map((d, i) => (<div key={i} style={d.style}></div>))}
                <div style={{flex:1}}></div>
                <button onClick={v.onTutSkip} style={{background:'none',border:'none',font:"800 12.5px 'Nunito',sans-serif",color:'#A08F79',cursor:'pointer',padding:'8px 10px'}}>Skip</button>
                <button onClick={v.onTutNext} style={v.tutNextStyle}>{v.tutNextLabel}</button>
              </div>
            </div>
          </React.Fragment>
        ) : null}
      </div>
    );
  }
}
