#!/usr/bin/env python3
"""
快速管线: 加载 find 结果 → 打标 → 知识图谱 → SimHash 抽样去重
跳过全量哈希（220K 文件太慢）
"""
import os, sys, json, hashlib, re, time
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict

OUTPUT_DIR = Path('/mnt/c/Users/hp/Desktop/文件迁移工具/output')
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def fmt(b):
    for u in ['B','KB','MB','GB','TB']:
        if b < 1024: return f'{b:.1f}{u}'
        b /= 1024
    return f'{b:.1f}PB'

def load(path):
    files = []
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            p = line.strip().split('|', 2)
            if len(p) != 3: continue
            try:
                sz, mt = int(p[0]), float(p[1])
            except: continue
            fp = p[2]
            if sz < 256 or sz > 10*1024**3: continue
            fn = os.path.basename(fp)
            if fn.lower() in ('desktop.ini','thumbs.db','ntuser.dat'): continue
            ext = os.path.splitext(fn)[1]
            if ext.lower() in ('.tmp','.bak','.swp','.lnk','.exe','.msi','.dll','.sys'): continue
            files.append({
                'path': fp, 'name': fn, 'ext': ext, 'size': sz,
                'size_str': fmt(sz),
                'mtime': datetime.fromtimestamp(mt).strftime('%Y-%m-%d %H:%M'),
            })
    return files

# 项目检测
PROJ_KW = {
    'FANUC':'FANUC机器人','ROBOGUIDE':'ROBOGUIDE','Micar':'Micar项目','MICAR':'Micar项目',
    'MicarServer':'Micar Server','EPLAN':'EPLAN电气','SCADA':'SCADA系统',
    'B1':'B1现场','B2':'B2现场','武汉':'武汉项目','Reports':'报告',
    '互传':'互传文件','供应商':'供应商资料','参考':'参考资料','AIAIAI':'AIAIAI项目',
    'UnifiedArchive':'统一归档','VM':'虚拟机','Github':'GitHub','Downloads':'下载',
}

# 标签映射
EXT_TAGS = {
    '.py': ('技术','代码','开发','高','长期有效','个人创作'),
    '.js': ('技术','代码','开发','高','长期有效','个人创作'),
    '.ts': ('技术','代码','前端','高','长期有效','个人创作'),
    '.java': ('技术','代码','','高','长期有效','个人创作'),
    '.c': ('技术','代码','','高','长期有效','个人创作'),
    '.cpp': ('技术','代码','','高','长期有效','个人创作'),
    '.h': ('技术','代码','','高','长期有效','个人创作'),
    '.go': ('技术','代码','后端','高','长期有效','个人创作'),
    '.sql': ('技术','代码','数据','高','长期有效','个人创作'),
    '.sh': ('技术','代码','运维','高','长期有效','个人创作'),
    '.bat': ('技术','代码','运维','高','长期有效','个人创作'),
    '.ps1': ('技术','代码','运维','高','长期有效','个人创作'),
    '.yaml': ('技术','配置','开发','中','长期有效','个人创作'),
    '.yml': ('技术','配置','开发','中','长期有效','个人创作'),
    '.json': ('技术','配置','开发','中','长期有效','个人创作'),
    '.toml': ('技术','配置','开发','中','长期有效','个人创作'),
    '.md': ('技术','文档','开发','高','长期有效','个人创作'),
    '.tex': ('技术','文档','开发','高','长期有效','个人创作'),
    '.docx': ('技术','文档','','中','不确定','个人创作'),
    '.doc': ('技术','文档','','中','不确定','个人创作'),
    '.pdf': ('技术','文档','','中','不确定','下载资料'),
    '.xlsx': ('技术','数据','','中','不确定','个人创作'),
    '.xls': ('技术','数据','','中','可能过时','个人创作'),
    '.pptx': ('技术','文档','','中','不确定','个人创作'),
    '.ppt': ('技术','文档','','中','不确定','个人创作'),
    '.csv': ('技术','数据','数据','中','不确定','项目产出'),
    '.ipynb': ('技术','数据','AI','高','长期有效','个人创作'),
    '.pt': ('技术','数据','AI','高','长期有效','项目产出'),
    '.pth': ('技术','数据','AI','高','长期有效','项目产出'),
    '.onnx': ('技术','数据','AI','高','长期有效','项目产出'),
    '.safetensors': ('技术','数据','AI','高','长期有效','项目产出'),
    '.jpg': ('其他','图片','','低','长期有效','个人创作'),
    '.jpeg': ('其他','图片','','低','长期有效','个人创作'),
    '.png': ('其他','图片','','低','长期有效','个人创作'),
    '.mp4': ('其他','视频','','中','长期有效','个人创作'),
    '.zip': ('技术','压缩包','其他','中','不确定','下载资料'),
    '.rar': ('技术','压缩包','其他','中','不确定','下载资料'),
    '.7z': ('技术','压缩包','其他','中','不确定','下载资料'),
    '.dwg': ('技术','设计','机械设计','高','长期有效','项目产出'),
    '.dxf': ('技术','设计','机械设计','高','长期有效','项目产出'),
    '.step': ('技术','设计','机械设计','高','长期有效','项目产出'),
    '.stp': ('技术','设计','机械设计','高','长期有效','项目产出'),
    '.iges': ('技术','设计','机械设计','高','长期有效','项目产出'),
    '.igs': ('技术','设计','机械设计','高','长期有效','项目产出'),
    '.psd': ('个人','设计','其他','中','长期有效','个人创作'),
    '.svg': ('技术','设计','前端','中','长期有效','个人创作'),
    '.html': ('技术','代码','前端','中','长期有效','个人创作'),
    '.css': ('技术','代码','前端','中','长期有效','个人创作'),
    '.vue': ('技术','代码','前端','中','长期有效','个人创作'),
    '.jsx': ('技术','代码','前端','中','长期有效','个人创作'),
    '.tsx': ('技术','代码','前端','中','长期有效','个人创作'),
    # 新增工业类别
    '.tp': ('技术','工业程序','机器人','高','长期有效','项目产出'),
    '.vr': ('技术','工业程序','机器人','高','长期有效','项目产出'),
    '.sv': ('技术','工业程序','机器人','高','长期有效','项目产出'),
    '.ls': ('技术','工业程序','机器人','高','长期有效','项目产出'),
    '.dg': ('技术','工业程序','机器人','高','长期有效','项目输出'),
    '.dt': ('技术','工业程序','机器人','高','长期有效','项目产出'),
    '.pc': ('技术','工业程序','机器人','中','长期有效','项目产出'),
    '.cm': ('技术','工业程序','机器人','高','长期有效','项目产出'),
    '.io': ('技术','工业程序','机器人','高','长期有效','项目产出'),
    '.kl': ('技术','工业程序','机器人','高','长期有效','项目产出'),
    '.va': ('技术','工业程序','机器人','中','长期有效','项目产出'),
    '.rbt': ('技术','工业程序','机器人','高','长期有效','项目产出'),
    # CAD支持
    '.lsp': ('技术','CAD支持','机械设计','低','长期有效','下载资料'),
    '.shx': ('技术','CAD支持','机械设计','低','长期有效','下载资料'),
    '.dwt': ('技术','CAD支持','机械设计','低','长期有效','下载资料'),
    '.dws': ('技术','CAD支持','机械设计','低','长期有效','下载资料'),
    '.arx': ('技术','CAD支持','机械设计','低','长期有效','下载资料'),
    '.crx': ('技术','CAD支持','机械设计','低','长期有效','下载资料'),
    # 音频
    '.mp3': ('个人','音频','其他','低','长期有效','个人创作'),
    '.wav': ('个人','音频','其他','低','长期有效','个人创作'),
    '.flac': ('个人','音频','其他','低','长期有效','个人创作'),
    # 字体
    '.ttf': ('技术','字体','其他','低','长期有效','下载资料'),
    '.otf': ('技术','字体','其他','低','长期有效','下载资料'),
}

def detect_proj(fp):
    for kw, proj in PROJ_KW.items():
        if kw.lower() in fp.lower():
            return proj
    return '未分类'

def get_tags(ext, fp):
    t = EXT_TAGS.get(ext.lower())
    if t:
        return dict(zip(['topic','doc_type','domain','priority','time_tag','source'], t))
    return {'topic':'其他','doc_type':'其他','domain':'其他','priority':'低','time_tag':'不确定','source':'未知'}

# SimHash
class SimHash:
    @staticmethod
    def compute(text):
        tokens = [m.group().lower() for m in re.finditer(r'[a-zA-Z_]\w+', text)]
        cn = re.findall(r'[\u4e00-\u9fff]', text)
        for i in range(len(cn)-1): tokens.append(cn[i]+cn[i+1])
        tokens.extend(cn)
        if not tokens: return 0
        v = [0]*64
        for t in tokens:
            h = int(hashlib.md5(t.encode()).hexdigest()[:16], 16)
            for i in range(64):
                v[i] += 1 if h & (1<<i) else -1
        return sum(1<<i for i in range(64) if v[i]>0)
    @staticmethod
    def hamming(a, b):
        return bin(a^b).count('1')

def main():
    print('='*64)
    print('  文件扫描 + 打标 + 知识图谱 管线')
    print('='*64)
    t0 = time.time()

    # 1. 加载
    print('\n[1/4] 加载文件列表...')
    fc = load('/tmp/files_c.txt')
    fd = load('/tmp/files_d.txt')
    all_f = fc + fd
    print(f'  C: {len(fc):,} | D: {len(fd):,} | 合计: {len(all_f):,}')

    # 2. 同名去重 + 打标
    print('\n[2/4] 同名去重 + 打标...')
    seen = {}
    dup_count = 0
    deduped = []
    for f in all_f:
        key = (f['name'].lower(), f['size'])
        if key in seen:
            dup_count += 1
            continue
        seen[key] = f
        f['tags'] = get_tags(f['ext'], f['path'])
        f['project'] = detect_proj(f['path'])
        deduped.append(f)
    print(f'  同名同大小重复: {dup_count:,} | 去重后: {len(deduped):,}')

    # 3. SimHash (抽样: 只对文本文件 <500KB)
    print('\n[3/4] SimHash 增强去重 (抽样)...')
    TEXT_EXT = {'.txt','.md','.py','.js','.ts','.c','.cpp','.h','.java','.go','.rs',
                '.rb','.sql','.sh','.bat','.ps1','.yaml','.yml','.json','.toml',
                '.ini','.html','.css','.xml','.csv','.rst','.tex','.log','.vue','.jsx','.tsx'}
    text_500k = [(i,f) for i,f in enumerate(deduped) if f['ext'].lower() in TEXT_EXT and f['size'] < 500*1024]
    print(f'  文本文件 (<500KB): {len(text_500k):,}')
    
    sh_results = []
    for idx, (i, f) in enumerate(text_500k):
        if idx % 5000 == 0 and idx:
            print(f'    hash: {idx:,}/{len(text_500k):,}', flush=True)
        try:
            with open(f['path'], 'r', encoding='utf-8', errors='ignore') as fh:
                text = fh.read(16384)
            if len(text) > 100:
                sh_results.append((f, SimHash.compute(text)))
        except: pass
    
    sh_results.sort(key=lambda x: x[0]['size'])
    sim_pairs = []
    checked = 0
    for a in range(len(sh_results)):
        if a % 1000 == 0 and a:
            print(f'    比对: {a:,}/{len(sh_results):,} | 疑似重复: {len(sim_pairs):,}', flush=True)
        fa, ha = sh_results[a]
        for b in range(a+1, min(a+200, len(sh_results))):  # 只比近邻
            fb, hb = sh_results[b]
            if abs(fa['size'] - fb['size']) / max(fa['size'],1) > 0.15:
                continue
            hd = SimHash.hamming(ha, hb)
            checked += 1
            if hd <= 8:
                sim_pairs.append({
                    'file_a': fa['path'], 'file_b': fb['path'],
                    'name_a': fa['name'], 'name_b': fb['name'],
                    'size_a': fa['size_str'], 'size_b': fb['size_str'],
                    'hamming': hd, 'similarity': round(1-hd/64, 4),
                })
    sim_pairs.sort(key=lambda x: x['hamming'])
    print(f'  比对次数: {checked:,} | 疑似重复: {len(sim_pairs):,} 对')

    # 4. 知识图谱 + 保存
    print('\n[4/4] 知识图谱 + 保存...')
    nodes, edges = {}, []
    def add_n(nid, ntype, **kw):
        if nid not in nodes: nodes[nid] = {'id':nid,'type':ntype,**kw}
    def add_e(src, tgt, rel):
        edges.append({'source':src,'target':tgt,'relation':rel})

    proj_files = defaultdict(list)
    for f in deduped:
        fid = f'file:{f["path"]}'
        parent = os.path.dirname(f['path'])
        ext = f['ext'].lower()
        t = f['tags']
        proj = f['project']
        add_n(f'dir:{parent}','directory',name=parent)
        add_n(f'ext:{ext}','extension',name=ext)
        add_n(f'topic:{t["topic"]}','topic',name=t['topic'])
        add_n(f'domain:{t["domain"]}','domain',name=t['domain'])
        add_n(f'project:{proj}','project',name=proj)
        add_n(fid,'file',name=f['name'],size=f['size'],topic=t['topic'],project=proj)
        add_e(fid, f'dir:{parent}', 'belongs_to')
        add_e(fid, f'ext:{ext}', 'has_ext')
        add_e(fid, f'topic:{t["topic"]}', 'tagged_topic')
        add_e(fid, f'domain:{t["domain"]}', 'tagged_domain')
        add_e(fid, f'project:{proj}', 'in_project')
        proj_files[proj].append(f)
    
    # 聚合边
    for proj, pfs in proj_files.items():
        for t in set(f['tags']['topic'] for f in pfs):
            add_e(f'project:{proj}', f'topic:{t}', 'covers_topic')
        for d in set(f['tags']['domain'] for f in pfs):
            add_e(f'project:{proj}', f'domain:{d}', 'covers_domain')

    # 保存
    with open(OUTPUT_DIR/'scan_results.json','w',encoding='utf-8') as f:
        json.dump({'generated':datetime.now().isoformat(),'total':len(deduped),
                   'total_before':len(all_f),'dups_removed':dup_count,'files':deduped}, f, ensure_ascii=False)
    
    with open(OUTPUT_DIR/'dedup_simhash_report.json','w',encoding='utf-8') as f:
        json.dump({'generated':datetime.now().isoformat(),'total_pairs':len(sim_pairs),
                   'pairs':sim_pairs[:500]}, f, ensure_ascii=False, indent=2)
    
    with open(OUTPUT_DIR/'missed_report.json','w',encoding='utf-8') as f:
        json.dump({'generated':datetime.now().isoformat(),'note':'find排除了node_modules/.git/__pycache__/Cache/Temp/ollama等目录',
                   'total':0,'files':[]}, f, ensure_ascii=False, indent=2)

    graph = {'generated':datetime.now().isoformat(),
             'metadata':{'total_files':len(deduped),'nodes':len(nodes),'edges':len(edges)},
             'nodes':list(nodes.values()),'edges':edges}
    with open(OUTPUT_DIR/'knowledge_graph.json','w',encoding='utf-8') as f:
        json.dump(graph, f, ensure_ascii=False)

    # 统计
    stats = {'generated':datetime.now().isoformat(),
             'overview':{'total_files':len(deduped),'total_size':fmt(sum(f['size'] for f in deduped)),
                         'nodes':len(nodes),'edges':len(edges)},
             'by_project':{p:{'count':len(pf),'size':fmt(sum(f['size'] for f in pf)),
                              'top_exts':dict(Counter(f['ext'].lower() for f in pf).most_common(5))}
                           for p,pf in sorted(proj_files.items(),key=lambda x:-len(x[1]))},
             'by_topic':dict(Counter(f['tags']['topic'] for f in deduped).most_common()),
             'by_domain':dict(Counter(f['tags']['domain'] for f in deduped).most_common())}
    with open(OUTPUT_DIR/'knowledge_graph_stats.json','w',encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    elapsed = time.time()-t0
    print(f'\n{"="*64}')
    print(f'  全部完成! 耗时 {elapsed:.0f}s')
    print(f'{"="*64}')
    print(f'\n  ┌─ 项目分布 TOP 15 ──────────────────────────────┐')
    for proj, pf in sorted(proj_files.items(),key=lambda x:-len(x[1]))[:15]:
        sz = fmt(sum(f['size'] for f in pf))
        print(f'  │ {proj:25} {len(pf):>6} 文件  {sz:>10}')
    print(f'  └─────────────────────────────────────────────────┘')
    tc = Counter(f['tags']['topic'] for f in deduped)
    print(f'\n  ┌─ 主题 ──────────────────────────────────────────┐')
    for t, c in tc.most_common():
        print(f'  │ {t:15} {c:>6}')
    print(f'  └─────────────────────────────────────────────────┘')
    dc = Counter(f['tags']['domain'] for f in deduped)
    print(f'\n  ┌─ 领域 TOP 15 ────────────────────────────────────┐')
    for d, c in dc.most_common(15):
        print(f'  │ {d:15} {c:>6}')
    print(f'  └─────────────────────────────────────────────────┘')
    if sim_pairs:
        print(f'\n  ┌─ SimHash 疑似重复 TOP 10 ───────────────────────┐')
        for i, p in enumerate(sim_pairs[:10], 1):
            print(f'  │ {i:2}. h={p["hamming"]:2} sim={p["similarity"]:.0%}  {p["name_a"][:30]}')
            print(f'  │         vs {p["name_b"][:30]}')
        print(f'  └─────────────────────────────────────────────────┘')

if __name__ == '__main__':
    main()
