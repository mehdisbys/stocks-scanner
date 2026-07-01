#!/usr/bin/env python3
"""
Build a self-contained HTML dashboard from the scanner's CSV outputs.

Reads (daily):
  - base_div_sheet_daily.csv      (daily base + divergence watchlist)
  - recent_div_daily.csv          (recent divergences, no-base)
Reads (weekly, optional — tabs appear only if present/non-empty):
  - base_div_sheet.csv            (weekly base + divergence watchlist)
  - recent_div_weekly.csv         (weekly recent divergences, no-base)
Reads (backtest):
  - SP500_per_symbol_summary.csv

Writes:
  - dashboard.html  (single file, data baked in, opens in any browser)

Re-run this script anytime after a fresh scan to refresh the dashboard.
No live scan is performed here -- it only visualizes existing CSVs.
"""

import csv
import datetime as dt
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# key -> filename. The four watchlist keys share one renderer; backtest is its own.
FILES = {
    "base": "base_div_sheet_daily.csv",     # daily base+div
    "recent": "recent_div_daily.csv",       # daily recent (no-base)
    "wbase": "base_div_sheet.csv",          # weekly base+div
    "wrecent": "recent_div_weekly.csv",     # weekly recent (no-base)
    "backtest": "SP500_per_symbol_summary.csv",
}
WATCH_KEYS = ("base", "recent", "wbase", "wrecent")


def load_csv(name):
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        return [], None
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    mtime = dt.datetime.fromtimestamp(os.path.getmtime(path))
    return rows, mtime.strftime("%Y-%m-%d %H:%M")


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _score(label):
    """Leading integer of a '4/4 PASS' / '2/3' label; None for n/a/blank."""
    if not label or label == "n/a":
        return None
    try:
        return int(str(label).split("/")[0])
    except (ValueError, IndexError):
        return None


def main():
    data = {}
    meta = {}
    # Enrichment lookup files (fallback when the scan CSV lacks the columns).
    canslim = {}
    for r in load_csv("canslim.csv")[0]:
        canslim[r["symbol"]] = {"label": r.get("canslim", ""), "score": num(r.get("canslim_score"))}
    wdb = {}
    for r in load_csv("wdb.csv")[0]:
        wdb[r["symbol"]] = {"label": r.get("wdb", ""), "score": num(r.get("wdb_score"))}

    for key, fname in FILES.items():
        rows, mtime = load_csv(fname)
        if key in WATCH_KEYS:
            for r in rows:
                sym = r.get("symbol")
                # Prefer enriched columns emitted by the scan; else lookup files.
                cl = r.get("canslim")
                if cl:
                    r["canslim"], r["canslim_score"] = cl, _score(cl)
                else:
                    c = canslim.get(sym, {})
                    r["canslim"], r["canslim_score"] = c.get("label", ""), c.get("score")
                wl = r.get("wdb")
                if wl:
                    r["wdb"], r["wdb_score"] = wl, _score(wl)
                else:
                    w = wdb.get(sym, {})
                    r["wdb"], r["wdb_score"] = w.get("label", ""), w.get("score")
        data[key] = rows
        meta[key] = {"file": fname, "rows": len(rows), "updated": mtime}

    # Coerce numeric fields so JS can sort properly.
    for key in WATCH_KEYS:
        for r in data[key]:
            for col in ("close", "off_high", "range_position", "div_count"):
                if col in r:
                    r[col] = num(r[col])
    for r in data["backtest"]:
        for col in ("trades", "win_rate", "avg_return", "total_pnl_usd", "avg_bars_held"):
            if col in r:
                r[col] = num(r[col])

    has_weekly = bool(data["wbase"] or data["wrecent"])

    payload = {
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "meta": meta,
        "has_weekly": has_weekly,
        **{k: data[k] for k in FILES},
    }

    # Tabs / panels / boot calls — weekly only when present.
    tabs = [("base", "Base + Divergence (Daily)"), ("recent", "Recent Div (Daily)")]
    panels = _watch_panel("base", "base") + _watch_panel("recent", "recent")
    boot = "initWatch('base','base'); initWatch('recent','recent');"
    if has_weekly:
        tabs += [("wbase", "Base + Divergence (Weekly)"), ("wrecent", "Recent Div (Weekly)")]
        panels += _watch_panel("wbase", "base") + _watch_panel("wrecent", "recent")
        boot += " initWatch('wbase','base'); initWatch('wrecent','recent');"
    tabs.append(("backtest", "S&amp;P 500 Backtest"))
    panels += _BACKTEST_PANEL
    boot += " initBacktest();"

    tabs_html = "\n    ".join(
        f'<div class="tab{" active" if i == 0 else ""}" data-tab="{k}">{lbl}</div>'
        for i, (k, lbl) in enumerate(tabs))

    html = (HTML_TEMPLATE
            .replace("<!--__TABS__-->", tabs_html)
            .replace("<!--__PANELS__-->", panels)
            .replace("/*__BOOT__*/", boot)
            .replace("/*__DATA__*/", json.dumps(payload, separators=(",", ":"))))
    out = os.path.join(HERE, "dashboard.html")
    with open(out, "w") as f:
        f.write(html)
    print(f"Wrote {out}" + ("  (with weekly tabs)" if has_weekly else "  (daily only)"))
    for k, m in meta.items():
        print(f"  {k:9s} {m['rows']:4d} rows  ({m['file']}, updated {m['updated']})")


def _watch_panel(key, style):
    """HTML for one watchlist tab. style is 'base' or 'recent'."""
    chart_a = "Most common divergence indicators" if style == "base" else "Confirmations by date"
    bt_select = ('<select id="bt-%s"><option value="">All base types</option></select>' % key
                 if style == "base" else "")
    footnote = ('<div class="footnote">off_high = drawdown from prior high · range_position = '
                'where price sits in its range (0=low,1=high) · div_count = confirmed divergence '
                'indicators · CANSLIM = price&gt;SMA20/50/200 &amp; RSI&gt;50 (daily) · '
                'WDB = P/E&lt;10, P/B&lt;1, Price/Cash&lt;3.</div>') if style == "base" else ""
    active = " active" if key == "base" else ""
    return f'''
  <div class="panel{active}" id="panel-{key}">
    <div class="cards" id="cards-{key}"></div>
    <div class="grid two">
      <div class="chartbox"><h3>{chart_a}</h3><canvas id="chart-{key}-a" height="150"></canvas></div>
      <div class="chartbox"><h3>By universe</h3><canvas id="chart-{key}-b" height="150"></canvas></div>
    </div>
    <div class="toolbar" style="margin-top:18px">
      <input type="search" id="q-{key}" placeholder="Filter by symbol…">
      <select id="u-{key}"><option value="">All universes</option><option>SP500</option><option>broader</option></select>
      {bt_select}
      <span class="count" id="count-{key}"></span>
    </div>
    <div class="tablewrap"><table id="t-{key}"></table></div>
    {footnote}
  </div>'''


_BACKTEST_PANEL = '''
  <div class="panel" id="panel-backtest">
    <div class="cards" id="cards-backtest"></div>
    <div class="grid two">
      <div class="chartbox"><h3>Top 15 by total PnL (USD)</h3><canvas id="chart-bt-pnl" height="180"></canvas></div>
      <div class="chartbox"><h3>Win-rate distribution</h3><canvas id="chart-bt-wr" height="180"></canvas></div>
    </div>
    <div class="toolbar" style="margin-top:18px">
      <input type="search" id="q-backtest" placeholder="Filter by symbol…">
      <span class="count" id="count-backtest"></span>
    </div>
    <div class="tablewrap"><table id="t-backtest"></table></div>
    <div class="footnote">Per-symbol results from the 10-year S&amp;P 500 backtest (costs applied, no look-ahead).</div>
  </div>'''


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crypto &amp; Stock Scanner — Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root{
    --bg:#0d1117; --panel:#161b22; --panel2:#1c2230; --border:#2a3344;
    --text:#e6edf3; --muted:#8b949e; --accent:#3b82f6; --green:#26a17b;
    --red:#e5484d; --amber:#d29922; --chip:#21304a;
  }
  *{box-sizing:border-box}
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
       background:var(--bg);color:var(--text);font-size:14px;}
  header{padding:20px 28px 8px;border-bottom:1px solid var(--border);}
  h1{margin:0;font-size:20px;font-weight:650;letter-spacing:-.01em;}
  .sub{color:var(--muted);font-size:12.5px;margin-top:4px;}
  .wrap{padding:18px 28px 60px;max-width:1280px;margin:0 auto;}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0 22px;}
  .card{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:14px 16px;}
  .card .k{color:var(--muted);font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;}
  .card .v{font-size:24px;font-weight:650;margin-top:4px;}
  .card .v.green{color:var(--green)} .card .v.red{color:var(--red)} .card .v.amber{color:var(--amber)}
  .tabs{display:flex;gap:4px;border-bottom:1px solid var(--border);margin-bottom:16px;flex-wrap:wrap;}
  .tab{padding:9px 16px;cursor:pointer;color:var(--muted);border-bottom:2px solid transparent;
       font-weight:550;font-size:13.5px;}
  .tab:hover{color:var(--text)}
  .tab.active{color:var(--text);border-bottom-color:var(--accent);}
  .panel{display:none}.panel.active{display:block}
  .toolbar{display:flex;gap:10px;align-items:center;margin-bottom:12px;flex-wrap:wrap;}
  input[type=search],select{background:var(--panel2);border:1px solid var(--border);color:var(--text);
       padding:7px 10px;border-radius:8px;font-size:13px;outline:none;}
  input[type=search]{min-width:220px}
  .count{color:var(--muted);font-size:12.5px;margin-left:auto;}
  .grid{display:grid;grid-template-columns:1fr;gap:18px;}
  @media(min-width:900px){.grid.two{grid-template-columns:1.4fr 1fr;}}
  .chartbox{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:14px;}
  .chartbox h3{margin:0 0 10px;font-size:13px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;}
  table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--border);
        border-radius:10px;overflow:hidden;}
  th,td{padding:8px 11px;text-align:left;border-bottom:1px solid var(--border);white-space:nowrap;}
  th{background:var(--panel2);font-size:11.5px;text-transform:uppercase;letter-spacing:.03em;color:var(--muted);
     cursor:pointer;user-select:none;position:sticky;top:0;}
  th:hover{color:var(--text)}
  th.sorted::after{content:" ▾";color:var(--accent)}
  th.sorted.asc::after{content:" ▴"}
  tbody tr:hover{background:#1a2130}
  td.num{text-align:right;font-variant-numeric:tabular-nums;}
  .sym{font-weight:650}
  a.tv{color:var(--accent);text-decoration:none;font-size:12px;}
  a.tv:hover{text-decoration:underline}
  .chip{display:inline-block;background:var(--chip);border-radius:5px;padding:1px 6px;margin:1px 2px 1px 0;
        font-size:11px;color:#9db4dd;}
  .badge{padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600;}
  .badge.sp{background:#1f2d4d;color:#86a8f0}
  .badge.broader{background:#3a2a16;color:#e0b066}
  .pos{color:var(--green)}.neg{color:var(--red)}
  .tablewrap{max-height:70vh;overflow:auto;border-radius:10px;}
  .footnote{color:var(--muted);font-size:11.5px;margin-top:10px;}
</style>
</head>
<body>
<header>
  <h1>Crypto &amp; Stock Scanner — Dashboard</h1>
  <div class="sub" id="subline"></div>
</header>
<div class="wrap">
  <div class="tabs" id="tabs">
    <!--__TABS__-->
  </div>
<!--__PANELS__-->
</div>

<script>
const DATA = /*__DATA__*/;
const $ = s => document.querySelector(s);

(function(){
  const m = DATA.meta;
  let s = `Generated ${DATA.generated} · daily base ${m.base.rows} (${m.base.updated||'—'}) · recent ${m.recent.rows}`;
  if(DATA.has_weekly) s += ` · weekly base ${m.wbase.rows} / recent ${m.wrecent.rows}`;
  s += ` · backtest ${m.backtest.rows} symbols · static view (no live scan)`;
  document.getElementById('subline').textContent = s;
})();

/* ---------- tabs ---------- */
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');
  document.getElementById('panel-'+t.dataset.tab).classList.add('active');
});

/* ---------- helpers ---------- */
const pct = v => v==null? '' : (v*100).toFixed(1)+'%';
const fix = (v,d=2) => v==null? '' : v.toFixed(d);
const usd = v => v==null? '' : '$'+Math.round(v).toLocaleString();
const chips = s => !s? '' : s.split('|').map(x=>`<span class="chip">${x}</span>`).join('');
const canslimCell = (v,r) => { const s=r.canslim_score; if(s==null) return '';
  const col = s>=4?'var(--green)':(s>=3?'var(--amber)':'var(--muted)');
  return `<span style="color:${col};font-weight:${s>=4?'650':'500'}">${v||''}</span>`; };
const wdbCell = (v,r) => { const s=r.wdb_score; if(v==null||v==='') return ''; if(v==='n/a') return '<span style="color:var(--muted)">n/a</span>';
  const col = s>=3?'var(--green)':(s>=2?'var(--amber)':'var(--muted)');
  return `<span style="color:${col};font-weight:${s>=3?'650':'500'}">${v}</span>`; };
const AI_PROMPT = sym => 'Act as an equity research analyst and give a detailed analysis of the stock with ticker '
  + sym + '. Structure it with clear sections: a short company overview; the core bear case; the bull case and any '
  + 'turnaround or growth strategy; a financial snapshot table of key metrics (revenue, net income, margins, free cash '
  + 'flow) with latest full-year and most recent quarter figures; the current technical setup and key price levels to '
  + 'watch; a valuation-versus-risk discussion; and a summary recommendation framework for different investor types '
  + '(value/contrarian versus income/risk-averse). Use the most recent available data and finish by offering a deeper follow-up.';
const aiUrl = sym => 'https://www.google.com/search?udm=50&q=' + encodeURIComponent(AI_PROMPT(sym));
const ubadge = u => u==='SP500'? '<span class="badge sp">SP500</span>' : `<span class="badge broader">${u}</span>`;
function signed(v,d=1){ if(v==null) return ''; const c=v>=0?'pos':'neg'; return `<span class="${c}">${v>0?'+':''}${v.toFixed(d)}</span>`; }

/* ---------- generic sortable table ---------- */
function makeTable(tableId, rows, cols, state){
  const tbl = document.getElementById(tableId);
  function render(){
    let r = rows.filter(state.filter);
    const sc = state.sortCol;
    if(sc){
      r = r.slice().sort((a,b)=>{
        let x=a[sc], y=b[sc];
        if(typeof x==='number' || typeof y==='number'){ x=x??-Infinity; y=y??-Infinity; return state.asc? x-y : y-x; }
        x=(x||'').toString(); y=(y||'').toString();
        return state.asc? x.localeCompare(y) : y.localeCompare(x);
      });
    }
    const thead = '<thead><tr>'+cols.map(c=>
      `<th data-c="${c.key}" class="${sc===c.key?'sorted '+(state.asc?'asc':''):''}">${c.label}</th>`).join('')+'</tr></thead>';
    const tbody = '<tbody>'+r.map(row=>'<tr>'+cols.map(c=>
      `<td class="${c.num?'num':''}">${c.fmt? c.fmt(row[c.key],row): (row[c.key]??'')}</td>`).join('')+'</tr>').join('')+'</tbody>';
    tbl.innerHTML = thead+tbody;
    tbl.querySelectorAll('th').forEach(th=>th.onclick=()=>{
      const c=th.dataset.c;
      if(state.sortCol===c) state.asc=!state.asc; else {state.sortCol=c; state.asc=false;}
      render();
    });
    if(state.onCount) state.onCount(r.length, rows.length);
  }
  state.render = render;
  render();
}

/* ---------- shared watchlist columns ---------- */
function watchCols(){ return [
  {key:'symbol',label:'Symbol',fmt:(v)=>`<span class="sym">${v}</span>`},
  {key:'universe',label:'Univ',fmt:ubadge},
  {key:'close',label:'Close',num:1,fmt:v=>fix(v,2)},
  {key:'off_high',label:'Off High',num:1,fmt:v=>signed(v*100,1)+'%'},
  {key:'range_position',label:'Range Pos',num:1,fmt:v=>fix(v,2)},
  {key:'base_type',label:'Base Type'},
  {key:'div_count',label:'Div #',num:1},
  {key:'canslim',label:'CANSLIM',fmt:canslimCell},
  {key:'wdb',label:'WDB',fmt:wdbCell},
  {key:'div_indicators',label:'Indicators',fmt:chips},
  {key:'div_last',label:'Last Conf.'},
  {key:'tradingview_chart',label:'Chart',fmt:(v)=>v?`<a class="tv" href="${v}" target="_blank">TV ↗</a>`:''},
  {key:'symbol',label:'AI',fmt:(v)=>`<a class="tv" href="${aiUrl(v)}" target="_blank">AI ↗</a>`},
];}

/* ---------- one renderer for all four watchlist tabs ---------- */
function initWatch(key, style){
  const rows = DATA[key] || [];
  const sp = rows.filter(r=>r.universe==='SP500').length;
  if(style==='base'){
    const strong = rows.filter(r=>r.div_count>=7).length;
    const avgOff = rows.reduce((a,r)=>a+(r.off_high||0),0)/(rows.length||1);
    $('#cards-'+key).innerHTML = card('Names',rows.length)+card('SP500 / Broader',`${sp} / ${rows.length-sp}`)
      +card('Strong (≥7 div)',strong,'green')+card('Avg off high',(avgOff*100).toFixed(0)+'%','red');
    barChart('chart-'+key+'-a', topIndicators(rows));
  } else {
    $('#cards-'+key).innerHTML = card('Names',rows.length)+card('SP500 / Broader',`${sp} / ${rows.length-sp}`)
      +card('Avg div #',(rows.reduce((a,r)=>a+(r.div_count||0),0)/(rows.length||1)).toFixed(1),'green')
      +card('With base type',rows.filter(r=>r.base_type).length,'amber');
    lineChart('chart-'+key+'-a', byDate(rows));
  }
  donut('chart-'+key+'-b', countBy(rows,'universe'));
  const btSel = $('#bt-'+key);
  if(btSel){
    const bts=[...new Set(rows.map(r=>r.base_type).filter(Boolean))].sort();
    btSel.insertAdjacentHTML('beforeend', bts.map(b=>`<option>${b}</option>`).join(''));
  }
  const state={sortCol: style==='base'?'div_count':'div_last',asc:false,filter:r=>{
    const q=$('#q-'+key).value.toLowerCase(), u=$('#u-'+key).value, bt=btSel?btSel.value:'';
    return (!q||r.symbol.toLowerCase().includes(q)) && (!u||r.universe===u) && (!bt||r.base_type===bt);
  },onCount:(n,t)=>$('#count-'+key).textContent=`${n} of ${t}`};
  makeTable('t-'+key, rows, watchCols(), state);
  (['q-'+key,'u-'+key].concat(btSel?['bt-'+key]:[])).forEach(id=>$('#'+id).oninput=state.render);
}

/* ===================== BACKTEST ===================== */
function initBacktest(){
  const rows = DATA.backtest;
  const cols=[
    {key:'symbol',label:'Symbol',fmt:v=>`<span class="sym">${v}</span>`},
    {key:'trades',label:'Trades',num:1},
    {key:'win_rate',label:'Win %',num:1,fmt:v=>fix(v,1)},
    {key:'avg_return',label:'Avg Ret %',num:1,fmt:v=>signed(v,2)},
    {key:'total_pnl_usd',label:'Total PnL',num:1,fmt:v=>v==null?'':`<span class="${v>=0?'pos':'neg'}">${v>=0?'+':'-'}$${Math.abs(Math.round(v)).toLocaleString()}</span>`},
    {key:'avg_bars_held',label:'Avg Bars',num:1,fmt:v=>fix(v,0)},
  ];
  const totPnl=rows.reduce((a,r)=>a+(r.total_pnl_usd||0),0);
  const wAvg=rows.reduce((a,r)=>a+(r.win_rate||0),0)/(rows.length||1);
  const profitable=rows.filter(r=>r.total_pnl_usd>0).length;
  $('#cards-backtest').innerHTML = card('Symbols',rows.length)
    +card('Total PnL',usd(totPnl), totPnl>=0?'green':'red')
    +card('Profitable',`${profitable} / ${rows.length}`,'green')
    +card('Avg win rate',wAvg.toFixed(1)+'%');
  const top=rows.slice().sort((a,b)=>(b.total_pnl_usd||0)-(a.total_pnl_usd||0)).slice(0,15);
  hbar('chart-bt-pnl', top.map(r=>r.symbol), top.map(r=>r.total_pnl_usd));
  hist('chart-bt-wr', rows.map(r=>r.win_rate).filter(v=>v!=null));
  const state={sortCol:'total_pnl_usd',asc:false,filter:r=>{
    const q=$('#q-backtest').value.toLowerCase(); return !q||r.symbol.toLowerCase().includes(q);
  },onCount:(n,t)=>$('#count-backtest').textContent=`${n} of ${t}`};
  makeTable('t-backtest',rows,cols,state);
  $('#q-backtest').oninput=state.render;
}

/* ---------- small builders ---------- */
function card(k,v,cls=''){return `<div class="card"><div class="k">${k}</div><div class="v ${cls}">${v}</div></div>`;}
function countBy(rows,key){const m={};rows.forEach(r=>{const k=r[key]||'—';m[k]=(m[k]||0)+1;});return m;}
function topIndicators(rows){const m={};rows.forEach(r=>(r.div_indicators||'').split('|').forEach(i=>{if(i)m[i]=(m[i]||0)+1;}));
  return Object.entries(m).sort((a,b)=>b[1]-a[1]);}
function byDate(rows){const m={};rows.forEach(r=>{if(r.div_last)m[r.div_last]=(m[r.div_last]||0)+1;});
  return Object.entries(m).sort((a,b)=>a[0].localeCompare(b[0]));}

/* ---------- charts (all guarded: a missing/blocked Chart.js never breaks tables) ---------- */
const AX={color:'#8b949e'}, GRID={color:'#2a3344'};
const baseOpts={responsive:true,plugins:{legend:{display:false}},
  scales:{x:{ticks:AX,grid:GRID},y:{ticks:AX,grid:GRID}}};
const CHARTS_OK = (typeof Chart !== 'undefined');
function chartGuard(id){
  if(CHARTS_OK) return true;
  const c=$('#'+id); if(c){const b=c.closest('.chartbox'); if(b) b.style.display='none';}
  return false;
}
function safeChart(id, cfg){ if(!chartGuard(id)) return; try{ new Chart($('#'+id), cfg); }catch(e){ console.error('chart',id,e); } }
function barChart(id,entries){safeChart(id,{type:'bar',
  data:{labels:entries.map(e=>e[0]),datasets:[{data:entries.map(e=>e[1]),backgroundColor:'#3b82f6'}]},
  options:baseOpts});}
function hbar(id,labels,vals){safeChart(id,{type:'bar',
  data:{labels,datasets:[{data:vals,backgroundColor:vals.map(v=>v>=0?'#26a17b':'#e5484d')}]},
  options:{indexAxis:'y',responsive:true,plugins:{legend:{display:false}},
    scales:{x:{ticks:AX,grid:GRID},y:{ticks:AX,grid:GRID}}}});}
function lineChart(id,entries){safeChart(id,{type:'line',
  data:{labels:entries.map(e=>e[0]),datasets:[{data:entries.map(e=>e[1]),borderColor:'#3b82f6',
    backgroundColor:'rgba(59,130,246,.15)',fill:true,tension:.25,pointRadius:2}]},options:baseOpts});}
function donut(id,map){safeChart(id,{type:'doughnut',
  data:{labels:Object.keys(map),datasets:[{data:Object.values(map),
    backgroundColor:['#3b82f6','#d29922','#26a17b','#e5484d','#8957e5']}]},
  options:{responsive:true,plugins:{legend:{position:'right',labels:{color:'#e6edf3'}}}}});}
function hist(id,vals){const bins=Array(10).fill(0);vals.forEach(v=>{let i=Math.min(9,Math.floor(v/10));if(i<0)i=0;bins[i]++;});
  safeChart(id,{type:'bar',
    data:{labels:bins.map((_,i)=>`${i*10}-${i*10+10}`),datasets:[{data:bins,backgroundColor:'#8957e5'}]},
    options:baseOpts});}

/* ---------- boot (after all helpers + constants are defined) ---------- */
/*__BOOT__*/
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
