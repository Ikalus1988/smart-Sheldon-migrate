#!/usr/bin/env python3
"""
从 scan_results.json + knowledge_graph_stats.json 提取摘要数据，
生成一个自包含 HTML 可视化页面。
"""
import json
from pathlib import Path
from collections import Counter, defaultdict

OUTPUT = Path('/mnt/c/Users/hp/Desktop/文件迁移工具/output')

# 加载
print('加载数据...')
with open(OUTPUT/'scan_results.json', 'r', encoding='utf-8') as f:
    scan = json.load(f)
with open(OUTPUT/'knowledge_graph_stats.json', 'r', encoding='utf-8') as f:
    stats = json.load(f)
with open(OUTPUT/'dedup_simhash_report.json', 'r', encoding='utf-8') as f:
    dedup = json.load(f)

files = scan['files']

# 按项目聚合
proj_data = defaultdict(lambda: {'count':0, 'size':0, 'exts':Counter(), 'topics':Counter(), 'files':[]})
for f in files:
    p = f['project']
    proj_data[p]['count'] += 1
    proj_data[p]['size'] += f['size']
    proj_data[p]['exts'][f['ext'].lower()] += 1
    proj_data[p]['topics'][f['tags']['topic']] += 1
    if len(proj_data[p]['files']) < 20:
        proj_data[p]['files'].append({
            'name': f['name'], 'size': f['size_str'], 'ext': f['ext'],
            'topic': f['tags']['topic'], 'domain': f['tags']['domain'],
            'mtime': f['mtime']
        })

# 扩展名全局统计
ext_counter = Counter()
for f in files:
    ext_counter[f['ext'].lower()] += 1

def fmt(b):
    for u in ['B','KB','MB','GB','TB']:
        if b < 1024: return f'{b:.1f} {u}'
        b /= 1024
    return f'{b:.1f} PB'

# 构建前端数据
viz_data = {
    'overview': stats['overview'],
    'scan': {
        'total_before': scan['total_before'],
        'dups_removed': scan['dups_removed'],
        'total_after': scan['total'],
    },
    'projects': [
        {'name': p, 'count': d['count'], 'size': d['size'], 'size_str': fmt(d['size']),
         'top_exts': dict(d['exts'].most_common(8)),
         'topics': dict(d['topics']),
         'sample_files': d['files']}
        for p, d in sorted(proj_data.items(), key=lambda x: -x[1]['count'])
    ],
    'topics': stats['by_topic'],
    'domains': stats['by_domain'],
    'top_exts': dict(ext_counter.most_common(30)),
    'simhash': {
        'total_pairs': dedup['total_pairs'],
        'sample_pairs': dedup['pairs'][:20],
    },
    'graph_stats': {
        'nodes': stats['overview']['nodes'],
        'edges': stats['overview']['edges'],
    }
}

# 生成 HTML
html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>文件扫描知识图谱 — 可视化</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; background:#0d1117; color:#c9d1d9; }
.container { max-width:1400px; margin:0 auto; padding:20px; }
h1 { font-size:28px; color:#58a6ff; margin-bottom:8px; }
h2 { font-size:20px; color:#58a6ff; margin:30px 0 12px; border-bottom:1px solid #21262d; padding-bottom:8px; }
h3 { font-size:16px; color:#8b949e; margin:16px 0 8px; }
.subtitle { color:#8b949e; font-size:14px; margin-bottom:24px; }

/* 概览卡片 */
.cards { display:grid; grid-template-columns:repeat(auto-fit, minmax(200px,1fr)); gap:16px; margin-bottom:30px; }
.card { background:#161b22; border:1px solid #30363d; border-radius:12px; padding:20px; }
.card .label { font-size:12px; color:#8b949e; text-transform:uppercase; letter-spacing:1px; }
.card .value { font-size:32px; font-weight:700; color:#58a6ff; margin-top:4px; }
.card .sub { font-size:12px; color:#8b949e; margin-top:4px; }

/* 图表 */
.chart { background:#161b22; border:1px solid #30363d; border-radius:12px; padding:20px; margin-bottom:20px; }
.bar-row { display:flex; align-items:center; margin:6px 0; }
.bar-label { width:180px; font-size:13px; text-align:right; padding-right:12px; color:#c9d1d9; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.bar-track { flex:1; height:24px; background:#21262d; border-radius:4px; overflow:hidden; position:relative; }
.bar-fill { height:100%; border-radius:4px; transition:width 0.6s ease; display:flex; align-items:center; padding-left:8px; font-size:11px; color:#fff; font-weight:600; min-width:fit-content; }
.bar-count { width:80px; font-size:13px; text-align:right; padding-left:12px; color:#8b949e; }

/* 饼图 (CSS) */
.pie-wrap { display:flex; align-items:center; gap:40px; flex-wrap:wrap; }
.pie { width:220px; height:220px; border-radius:50%; position:relative; }
.pie-legend { display:flex; flex-direction:column; gap:6px; }
.pie-legend-item { display:flex; align-items:center; gap:8px; font-size:13px; }
.pie-dot { width:12px; height:12px; border-radius:3px; flex-shrink:0; }

/* 表格 */
table { width:100%; border-collapse:collapse; font-size:13px; }
th { text-align:left; padding:10px 12px; background:#21262d; color:#8b949e; font-weight:600; position:sticky; top:0; }
td { padding:8px 12px; border-bottom:1px solid #21262d; }
tr:hover td { background:#161b22; }

/* 项目详情 */
.proj-detail { background:#161b22; border:1px solid #30363d; border-radius:12px; padding:20px; margin-bottom:16px; cursor:pointer; transition:border-color 0.2s; }
.proj-detail:hover { border-color:#58a6ff; }
.proj-header { display:flex; justify-content:space-between; align-items:center; }
.proj-name { font-size:18px; font-weight:600; color:#e6edf3; }
.proj-meta { font-size:13px; color:#8b949e; }
.proj-body { display:none; margin-top:16px; }
.proj-body.open { display:block; }
.ext-tags { display:flex; flex-wrap:wrap; gap:6px; margin:8px 0; }
.ext-tag { background:#21262d; border:1px solid #30363d; border-radius:6px; padding:3px 10px; font-size:12px; color:#8b949e; }
.ext-tag .cnt { color:#58a6ff; font-weight:600; margin-left:4px; }

/* SimHash */
.sim-pair { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:12px 16px; margin-bottom:8px; font-size:13px; }
.sim-pair .dist { color:#f0883e; font-weight:700; }
.sim-pair .sim { color:#3fb950; font-weight:600; }
.sim-pair .path { color:#8b949e; word-break:break-all; }

/* 知识图谱简化 */
.graph-vis { background:#161b22; border:1px solid #30363d; border-radius:12px; padding:20px; margin-bottom:20px; }
.graph-stats { display:grid; grid-template-columns:repeat(3,1fr); gap:16px; text-align:center; }
.graph-stat .num { font-size:36px; font-weight:700; color:#58a6ff; }
.graph-stat .lbl { font-size:13px; color:#8b949e; }

/* 筛选 */
.filter-bar { display:flex; gap:12px; margin-bottom:16px; flex-wrap:wrap; }
.filter-btn { background:#21262d; border:1px solid #30363d; border-radius:8px; padding:6px 16px; font-size:13px; color:#c9d1d9; cursor:pointer; transition:all 0.2s; }
.filter-btn:hover, .filter-btn.active { background:#58a6ff; color:#0d1117; border-color:#58a6ff; }

.search { background:#0d1117; border:1px solid #30363d; border-radius:8px; padding:8px 14px; font-size:14px; color:#c9d1d9; width:300px; outline:none; }
.search:focus { border-color:#58a6ff; }
</style>
</head>
<body>
<div class="container">
<h1>📊 文件扫描知识图谱</h1>
<p class="subtitle">生成时间: ''' + scan['generated'][:19] + ''' | 扫描耗时 69s | Hermes Agent</p>

<div class="cards">
  <div class="card">
    <div class="label">扫描文件</div>
    <div class="value">''' + f"{scan['total_before']:,}" + '''</div>
    <div class="sub">C: + D: 全盘</div>
  </div>
  <div class="card">
    <div class="label">去重后</div>
    <div class="value">''' + f"{scan['total']:,}" + '''</div>
    <div class="sub">去重 ''' + f"{scan['dups_removed']:,}" + ''' 个</div>
  </div>
  <div class="card">
    <div class="label">总数据量</div>
    <div class="value">''' + stats['overview']['total_size'] + '''</div>
    <div class="sub">138 GB</div>
  </div>
  <div class="card">
    <div class="label">知识图谱</div>
    <div class="value">''' + f"{stats['overview']['nodes']:,}" + '''</div>
    <div class="sub">节点 / ''' + f"{stats['overview']['edges']:,}" + ''' 边</div>
  </div>
  <div class="card">
    <div class="label">项目数</div>
    <div class="value">''' + str(len(viz_data['projects'])) + '''</div>
    <div class="sub">自动识别</div>
  </div>
</div>

<!-- 项目分布 -->
<h2>📁 项目分布</h2>
<div class="chart" id="proj-chart"></div>

<!-- 主题 & 领域 -->
<h2>🏷️ 标签分布</h2>
<div style="display:grid; grid-template-columns:1fr 1fr; gap:20px;">
  <div class="chart">
    <h3>主题 (Topic)</h3>
    <div id="topic-chart"></div>
  </div>
  <div class="chart">
    <h3>领域 (Domain)</h3>
    <div id="domain-chart"></div>
  </div>
</div>

<!-- 扩展名 TOP 30 -->
<h2>📄 文件类型 TOP 30</h2>
<div class="chart" id="ext-chart"></div>

<!-- 项目详情 -->
<h2>🔍 项目详情</h2>
<input class="search" id="proj-search" placeholder="搜索项目名..." oninput="filterProjs()">
<div id="proj-details"></div>

<!-- SimHash 去重 -->
<h2>🔗 SimHash 疑似重复 TOP 20</h2>
<div id="sim-list"></div>

<!-- 知识图谱概览 -->
<h2>🕸️ 知识图谱</h2>
<div class="graph-vis">
  <div class="graph-stats">
    <div class="graph-stat"><div class="num">''' + f"{stats['overview']['nodes']:,}" + '''</div><div class="lbl">节点</div></div>
    <div class="graph-stat"><div class="num">''' + f"{stats['overview']['edges']:,}" + '''</div><div class="lbl">关系</div></div>
    <div class="graph-stat"><div class="num">''' + str(len(viz_data['projects'])) + '''</div><div class="lbl">项目</div></div>
  </div>
  <div style="margin-top:20px;">
    <h3>图谱结构</h3>
    <pre style="color:#8b949e; font-size:13px; line-height:1.8; margin-top:8px;">
文件 ──belongs_to──▶ 目录
  ├──has_ext──────▶ 扩展名
  ├──tagged_topic──▶ 主题 (技术/个人/办公/其他)
  ├──tagged_domain─▶ 领域 (开发/前端/CAD/嵌入式/...)
  └──in_project────▶ 项目 (B1/B2/Micar/...)

项目 ──covers_topic──▶ 主题
项目 ──covers_domain─▶ 领域
    </pre>
  </div>
</div>

</div>

<script>
const DATA = ''' + json.dumps(viz_data, ensure_ascii=False) + ''';

const COLORS = ['#58a6ff','#3fb950','#f0883e','#bc8cff','#f778ba','#ff7b72','#79c0ff','#56d364','#d29922','#a5d6ff','#7ee787','#ffa657'];

function fmt(b) {
  const u = ['B','KB','MB','GB','TB'];
  let i = 0;
  while (b >= 1024 && i < u.length-1) { b /= 1024; i++; }
  return b.toFixed(1) + ' ' + u[i];
}

function bar(label, value, max, color, suffix='') {
  const pct = Math.max(value/max*100, 1);
  return `<div class="bar-row">
    <div class="bar-label" title="${label}">${label}</div>
    <div class="bar-track"><div class="bar-fill" style="width:${pct}%;background:${color}">${value > max*0.08 ? suffix : ''}</div></div>
    <div class="bar-count">${value.toLocaleString()}</div>
  </div>`;
}

// 项目分布
{
  const el = document.getElementById('proj-chart');
  const projs = DATA.projects.filter(p => p.count > 10);
  const max = projs[0]?.count || 1;
  el.innerHTML = projs.map((p, i) =>
    bar(p.name, p.count, max, COLORS[i % COLORS.length], p.size_str)
  ).join('');
}

// 主题
{
  const el = document.getElementById('topic-chart');
  const entries = Object.entries(DATA.topics);
  const max = entries[0]?.[1] || 1;
  el.innerHTML = entries.map(([k,v], i) =>
    bar(k, v, max, COLORS[i % COLORS.length])
  ).join('');
}

// 领域
{
  const el = document.getElementById('domain-chart');
  const entries = Object.entries(DATA.domains).filter(([k,v]) => v > 5);
  const max = entries[0]?.[1] || 1;
  el.innerHTML = entries.map(([k,v], i) =>
    bar(k, v, max, COLORS[i % COLORS.length])
  ).join('');
}

// 扩展名
{
  const el = document.getElementById('ext-chart');
  const entries = Object.entries(DATA.top_exts).filter(([k]) => k);
  const max = entries[0]?.[1] || 1;
  el.innerHTML = entries.map(([k,v], i) =>
    bar(k || '(无)', v, max, COLORS[i % COLORS.length])
  ).join('');
}

// 项目详情
function renderProjs(filter='') {
  const el = document.getElementById('proj-details');
  const projs = DATA.projects.filter(p =>
    !filter || p.name.toLowerCase().includes(filter.toLowerCase())
  );
  el.innerHTML = projs.map((p, idx) => {
    const exts = Object.entries(p.top_exts).map(([e,c]) =>
      `<span class="ext-tag">${e || '(无)'}<span class="cnt">${c}</span></span>`
    ).join('');
    const topics = Object.entries(p.topics).map(([t,c]) =>
      `<span class="ext-tag">${t}<span class="cnt">${c}</span></span>`
    ).join('');
    const files = p.sample_files.map(f =>
      `<tr><td>${f.name}</td><td>${f.size}</td><td>${f.topic}</td><td>${f.domain}</td><td>${f.mtime}</td></tr>`
    ).join('');
    return `<div class="proj-detail" onclick="this.querySelector('.proj-body').classList.toggle('open')">
      <div class="proj-header">
        <span class="proj-name">${p.name}</span>
        <span class="proj-meta">${p.count.toLocaleString()} 文件 | ${p.size_str}</span>
      </div>
      <div class="proj-body">
        <h3>扩展名</h3><div class="ext-tags">${exts}</div>
        <h3>主题</h3><div class="ext-tags">${topics}</div>
        <h3>示例文件 (前20)</h3>
        <table><tr><th>文件名</th><th>大小</th><th>主题</th><th>领域</th><th>修改时间</th></tr>${files}</table>
      </div>
    </div>`;
  }).join('');
}
renderProjs();

function filterProjs() {
  renderProjs(document.getElementById('proj-search').value);
}

// SimHash
{
  const el = document.getElementById('sim-list');
  el.innerHTML = DATA.simhash.sample_pairs.map(p =>
    `<div class="sim-pair">
      <span class="dist">h=${p.hamming}</span> <span class="sim">相似度 ${(p.similarity*100).toFixed(0)}%</span>
      <div class="path">${p.name_a} (${p.size_a}) vs ${p.name_b} (${p.size_b})</div>
    </div>`
  ).join('');
}
</script>
</body>
</html>'''

out_path = OUTPUT / 'dashboard.html'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(html)
print(f'生成完成: {out_path}')
print(f'文件大小: {out_path.stat().st_size / 1024:.0f} KB')
