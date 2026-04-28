#!/usr/bin/env python3
"""
知识图谱构建器 — 从扫描结果构建文件知识图谱
输入: scan_results.json
输出: knowledge_graph.json + knowledge_graph_stats.json

图谱结构:
  节点: 文件、目录、扩展名、主题、领域、项目
  关系: belongs_to (文件→目录), has_ext (文件→扩展名), 
        tagged_topic (文件→主题), tagged_domain (文件→领域),
        in_project (文件→项目), similar_to (文件→文件, from dedup)
"""
import os
import re
import json
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict

OUTPUT_DIR = Path('/mnt/c/Users/hp/Desktop/文件迁移工具/output')
INPUT_FILE = OUTPUT_DIR / 'scan_results.json'

# ============ 标签推断 (复用 organize_files.py 的逻辑) ============

EXT_TOPIC = {
    '.py': ('技术', '开发'), '.js': ('技术', '前端'), '.ts': ('技术', '前端'),
    '.java': ('技术', '后端'), '.c': ('技术', '嵌入式'), '.cpp': ('技术', '嵌入式'),
    '.h': ('技术', '嵌入式'), '.go': ('技术', '后端'), '.rs': ('技术', '后端'),
    '.sql': ('技术', '数据'), '.sh': ('技术', '运维'), '.bat': ('技术', '运维'),
    '.yaml': ('技术', '开发'), '.yml': ('技术', '开发'), '.json': ('技术', '开发'),
    '.toml': ('技术', '开发'), '.ini': ('技术', '运维'), '.cfg': ('技术', '运维'),
    '.md': ('技术', '开发'), '.tex': ('技术', '开发'),
    '.docx': ('办公', '办公'), '.doc': ('办公', '办公'), '.pdf': ('办公', '办公'),
    '.xlsx': ('办公', '办公'), '.xls': ('办公', '办公'), '.pptx': ('办公', '办公'),
    '.ppt': ('办公', '办公'), '.csv': ('技术', '数据'),
    '.ipynb': ('技术', 'AI'), '.pt': ('技术', 'AI'), '.pth': ('技术', 'AI'),
    '.onnx': ('技术', 'AI'), '.safetensors': ('技术', 'AI'),
    '.psd': ('个人', '设计'), '.ai': ('个人', '设计'), '.svg': ('技术', '前端'),
    '.jpg': ('个人', '媒体'), '.png': ('个人', '媒体'), '.mp4': ('个人', '媒体'),
    '.zip': ('技术', '其他'), '.rar': ('技术', '其他'), '.7z': ('技术', '其他'),
}

PROJECT_PATTERNS = [
    (r'(?:^|[/\\])([^/\\]+?)(?:[/\\].*)?$', None),  # 顶层目录名
]

# 已知项目名关键词
KNOWN_PROJECTS = {
    'FANUC': 'FANUC机器人',
    'fanuc': 'FANUC机器人',
    'ROBOGUIDE': 'FANUC ROBOGUIDE',
    'Micar': 'Micar项目',
    'MICAR': 'Micar项目',
    'MicarServer': 'Micar Server',
    'EPLAN': 'EPLAN电气设计',
    'CAD': 'CAD图纸',
    'SCADA': 'SCADA系统',
    'B1': 'B1现场项目',
    'B2': 'B2现场项目',
    '武汉': '武汉项目',
    'UnifiedArchive': '统一归档',
    'Reports': '报告',
    '互传': '互传文件',
    '供应商': '供应商资料',
    '参考': '参考资料',
}

def detect_project(filepath: str) -> str:
    """从路径推断项目名"""
    parts = filepath.replace('\\', '/').split('/')
    
    # 跳过 /mnt/c/Users/hp/ 前缀
    for i, part in enumerate(parts):
        if part in ('mnt', 'c', 'd', 'Users', 'hp'):
            continue
        # 检查这个部分是否匹配已知项目
        for kw, proj in KNOWN_PROJECTS.items():
            if kw.lower() in part.lower():
                return proj
        # 检查路径中的任何部分
        break
    
    # 全路径搜索
    fp_lower = filepath.lower()
    for kw, proj in KNOWN_PROJECTS.items():
        if kw.lower() in fp_lower:
            return proj
    
    return '未分类'

def get_topic_domain(ext: str, filepath: str) -> tuple:
    """推断主题和领域"""
    ext_lower = ext.lower()
    if ext_lower in EXT_TOPIC:
        return EXT_TOPIC[ext_lower]
    
    fp_lower = filepath.lower()
    if any(kw in fp_lower for kw in ['project', '项目', 'dev', '开发', 'src']):
        return ('技术', '开发')
    if any(kw in fp_lower for kw in ['personal', '个人', 'photo', '照片']):
        return ('个人', '其他')
    return ('其他', '其他')

def format_size(b):
    if b >= 1024**3: return f'{b/1024**3:.1f} GB'
    if b >= 1024**2: return f'{b/1024**2:.1f} MB'
    if b >= 1024: return f'{b/1024:.1f} KB'
    return f'{b} B'

def main():
    print('=' * 64)
    print('  知识图谱构建器')
    print('=' * 64)
    print()
    
    if not INPUT_FILE.exists():
        print(f'  错误: 找不到 {INPUT_FILE}')
        return
    
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    files = data['files']
    print(f'  文件数: {len(files):,}')
    
    # ============ 构建节点和关系 ============
    nodes = {}
    edges = []
    
    def add_node(node_id, node_type, **attrs):
        if node_id not in nodes:
            nodes[node_id] = {'id': node_id, 'type': node_type, **attrs}
    
    def add_edge(source, target, relation, **attrs):
        edges.append({'source': source, 'target': target, 'relation': relation, **attrs})
    
    # 项目统计
    project_files = defaultdict(list)
    ext_counter = Counter()
    topic_counter = Counter()
    domain_counter = Counter()
    dir_counter = Counter()
    
    for f in files:
        fid = f'file:{f["path"]}'
        ext = f['ext'].lower()
        topic, domain = get_topic_domain(ext, f['path'])
        project = detect_project(f['path'])
        
        # 目录节点
        parent = str(Path(f['path']).parent)
        dir_id = f'dir:{parent}'
        add_node(dir_id, 'directory', name=parent, path=parent)
        
        # 扩展名节点
        ext_id = f'ext:{ext}' if ext else 'ext:(无)'
        add_node(ext_id, 'extension', name=ext or '(无)')
        
        # 主题节点
        topic_id = f'topic:{topic}'
        add_node(topic_id, 'topic', name=topic)
        
        # 领域节点
        domain_id = f'domain:{domain}'
        add_node(domain_id, 'domain', name=domain)
        
        # 项目节点
        proj_id = f'project:{project}'
        add_node(proj_id, 'project', name=project)
        
        # 文件节点
        add_node(fid, 'file',
                 name=f['name'],
                 path=f['path'],
                 ext=ext,
                 size=f['size'],
                 size_str=f['size_str'],
                 mtime=f['mtime'],
                 topic=topic,
                 domain=domain,
                 project=project)
        
        # 关系
        add_edge(fid, dir_id, 'belongs_to')
        add_edge(fid, ext_id, 'has_ext')
        add_edge(fid, topic_id, 'tagged_topic')
        add_edge(fid, domain_id, 'tagged_domain')
        add_edge(fid, proj_id, 'in_project')
        
        # 统计
        project_files[project].append(f)
        ext_counter[ext] += 1
        topic_counter[topic] += 1
        domain_counter[domain] += 1
        dir_counter[parent] += 1
    
    # 项目 → 主题关系 (聚合)
    project_topics = defaultdict(set)
    for f in files:
        ext = f['ext'].lower()
        topic, _ = get_topic_domain(ext, f['path'])
        project = detect_project(f['path'])
        project_topics[project].add(topic)
    
    for proj, topics in project_topics.items():
        for topic in topics:
            add_edge(f'project:{proj}', f'topic:{topic}', 'covers_topic')
    
    # 项目 → 领域关系
    project_domains = defaultdict(set)
    for f in files:
        ext = f['ext'].lower()
        _, domain = get_topic_domain(ext, f['path'])
        project = detect_project(f['path'])
        project_domains[project].add(domain)
    
    for proj, domains in project_domains.items():
        for domain in domains:
            add_edge(f'project:{proj}', f'domain:{domain}', 'covers_domain')
    
    # 领域 → 主题关系
    domain_topics = defaultdict(set)
    for f in files:
        ext = f['ext'].lower()
        topic, domain = get_topic_domain(ext, f['path'])
        domain_topics[domain].add(topic)
    
    for domain, topics in domain_topics.items():
        for topic in topics:
            add_edge(f'domain:{domain}', f'topic:{topic}', 'related_to')
    
    # ============ 保存 ============
    graph = {
        'generated': datetime.now().isoformat(),
        'metadata': {
            'total_files': len(files),
            'total_nodes': len(nodes),
            'total_edges': len(edges),
            'node_types': dict(Counter(n['type'] for n in nodes.values())),
            'edge_types': dict(Counter(e['relation'] for e in edges)),
        },
        'nodes': list(nodes.values()),
        'edges': edges,
    }
    
    graph_path = OUTPUT_DIR / 'knowledge_graph.json'
    with open(graph_path, 'w', encoding='utf-8') as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)
    print(f'  图谱: {graph_path}')
    print(f'  节点: {len(nodes):,} | 边: {len(edges):,}')
    
    # ============ 统计摘要 ============
    stats = {
        'generated': datetime.now().isoformat(),
        'overview': {
            'total_files': len(files),
            'total_size': format_size(sum(f['size'] for f in files)),
            'total_nodes': len(nodes),
            'total_edges': len(edges),
        },
        'by_project': {
            proj: {
                'file_count': len(pfiles),
                'total_size': format_size(sum(f['size'] for f in pfiles)),
                'extensions': dict(Counter(f['ext'].lower() for f in pfiles).most_common(10)),
            }
            for proj, pfiles in sorted(project_files.items(), key=lambda x: -len(x[1]))
        },
        'by_topic': dict(topic_counter.most_common()),
        'by_domain': dict(domain_counter.most_common()),
        'by_extension': dict(ext_counter.most_common(20)),
        'top_directories': [
            {'path': d, 'count': c}
            for d, c in dir_counter.most_common(20)
        ],
    }
    
    stats_path = OUTPUT_DIR / 'knowledge_graph_stats.json'
    with open(stats_path, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f'  统计: {stats_path}')
    
    # 打印摘要
    print(f'\n  ┌─ 项目分布 ───────────────────────────────┐')
    for proj, pfiles in sorted(project_files.items(), key=lambda x: -len(x[1]))[:15]:
        total_sz = sum(f['size'] for f in pfiles)
        bar = '█' * min(int(len(pfiles) / max(len(files), 1) * 40), 40)
        print(f'  │ {proj:20} {len(pfiles):>6} {format_size(total_sz):>10} {bar}')
    print(f'  └───────────────────────────────────────────┘')
    
    print(f'\n  ┌─ 主题分布 ───────────────────────────────┐')
    for topic, cnt in topic_counter.most_common():
        bar = '█' * min(int(cnt / max(len(files), 1) * 40), 40)
        print(f'  │ {topic:10} {cnt:>6} {bar}')
    print(f'  └───────────────────────────────────────────┘')
    
    print(f'\n  ┌─ 领域分布 ───────────────────────────────┐')
    for domain, cnt in domain_counter.most_common(15):
        bar = '█' * min(int(cnt / max(len(files), 1) * 40), 40)
        print(f'  │ {domain:10} {cnt:>6} {bar}')
    print(f'  └───────────────────────────────────────────┘')

if __name__ == '__main__':
    main()
