#!/usr/bin/env python3
"""
WSL 版文件扫描器 + 遗漏检测
扫描 /mnt/c 和 /mnt/d，输出:
  1. 全量扫描结果 scan_results.json
  2. 遗漏检测报告 missed_report.json — 被 EXCLUDE_PATTERNS 排除但可能是有价值的文件
"""
import os
import sys
import json
import hashlib
import time
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter
from dataclasses import dataclass, asdict

# ============ 配置 ============

SCAN_ROOTS = [Path('/mnt/c/Users/hp'), Path('/mnt/d')]
OUTPUT_DIR = Path('/mnt/c/Users/hp/Desktop/文件迁移工具/output')
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

EXCLUDE_PATTERNS = [
    'Windows', 'Program Files', 'ProgramData', 'AppData',
    '$Recycle.Bin', 'Recovery', 'PerfLogs', 'boot',
    'WindowsApps', 'node_modules', '.git', '__pycache__',
    '.venv', 'venv', 'Cache', 'cache', 'Temp', 'tmp',
    'CrashDumps', 'Logs', 'Backup', 'old_',
    '小米办公', 'XiaoMiOffice', 'WeChatFiles', 'QQFiles',
    'Tencent', 'Microsoft', 'Packages',
    'System Volume Information', '$RECYCLE.BIN',
    'ollama', 'Webview2UserDir',
]

# 这些排除模式在遗漏检测时"豁免"——即使路径包含这些词，也检查是否真有价值
# (比如 Backup 下面可能有重要项目备份)
RECHECK_PATTERNS = ['Backup', 'backup', 'Temp', 'tmp', 'Cache', 'cache', 'Logs']

# 有价值的扩展名 (用于遗漏检测: 被排除但有这些扩展名的文件值得审查)
VALUABLE_EXTS = {
    '.py', '.js', '.ts', '.java', '.c', '.cpp', '.h', '.go', '.rs', '.rb',
    '.sql', '.sh', '.ps1', '.bat',
    '.yaml', '.yml', '.json', '.toml', '.ini', '.cfg', '.env',
    '.md', '.rst', '.tex', '.txt',
    '.docx', '.doc', '.pdf', '.xlsx', '.xls', '.pptx', '.ppt',
    '.ipynb', '.csv', '.parquet',
    '.sln', '.csproj', '.vcxproj', '.gradle', '.cmake',
    '.psd', '.ai', '.fig', '.sketch', '.svg',
    '.pt', '.pth', '.onnx', '.safetensors', '.gguf',
}

# 无价值扩展名
JUNK_EXTS = {
    '.tmp', '.bak', '.swp', '.lnk', '.log',
    '.exe', '.msi', '.dll', '.sys', '.dat',
    '.cache', '.lock', '.pid',
    '.thumb', '.thumbnail',
}

# 有价值路径关键词
VALUABLE_KEYWORDS = [
    'project', '项目', 'work', '工作', 'dev', '开发',
    'github', 'gitlab', 'source', 'src',
    'personal', '个人', 'diary', '日记',
    '报告', 'report', '文档', 'document',
    '代码', 'code', 'script', '脚本',
    'config', '配置', 'setting',
    'model', '模型', 'dataset', '数据集',
    'FANUC', 'fanuc', 'robot', '机器人',
    'CAD', 'EPLAN', 'SCADA',
    'Micar', 'B1', 'B2',
]

MIN_FILE_SIZE = 256  # bytes
MAX_SCAN_SIZE = 10 * 1024 * 1024 * 1024  # 10GB

# ============ 核心 ============

def should_exclude(path_str: str) -> bool:
    p = path_str.replace('/', '\\').lower()
    for pat in EXCLUDE_PATTERNS:
        if pat.lower() in p:
            return True
    return False

def file_hash_quick(filepath: str) -> str:
    """快速哈希: 文件大小 + 前8KB + 后8KB"""
    try:
        size = os.path.getsize(filepath)
        h = hashlib.md5()
        h.update(str(size).encode())
        with open(filepath, 'rb') as f:
            h.update(f.read(min(8192, size)))
            if size > 8192:
                f.seek(max(0, size - 8192))
                h.update(f.read(8192))
        return h.hexdigest()
    except:
        return ''

def is_potentially_valuable(filepath: str, ext: str, size: int) -> tuple:
    """判断被排除的文件是否可能有价值。返回 (score, reasons)"""
    score = 0
    reasons = []
    ext_lower = ext.lower()
    
    # 有价值扩展名
    if ext_lower in VALUABLE_EXTS:
        score += 30
        reasons.append(f'有价值扩展名 {ext}')
    
    # 无价值扩展名
    if ext_lower in JUNK_EXTS:
        score -= 50
        reasons.append(f'垃圾扩展名 {ext}')
    
    # 路径关键词
    path_lower = filepath.lower()
    for kw in VALUABLE_KEYWORDS:
        if kw.lower() in path_lower:
            score += 10
            reasons.append(f'关键词: {kw}')
    
    # 大小 (适中大小的文件更可能有价值)
    if 1024 < size < 10 * 1024 * 1024:  # 1KB ~ 10MB
        score += 5
    elif size > 10 * 1024 * 1024:
        score += 3
    
    # 非标准扩展名但也不是垃圾
    if ext_lower and ext_lower not in JUNK_EXTS and ext_lower not in VALUABLE_EXTS:
        score += 2
        reasons.append(f'未知扩展名 {ext}')
    
    return score, reasons

def should_skip_dir(dirpath: str) -> bool:
    """检查目录是否应该完全跳过 (不再递归进入)"""
    dir_lower = os.path.basename(dirpath).lower()
    skip_dirs = {
        'windows', 'program files', 'program files (x86)', 'programdata',
        '$recycle.bin', 'recovery', 'perflogs', 'windowsapps',
        'node_modules', '.git', '__pycache__', '.venv', 'venv',
        'system volume information', '$recycle.bin',
        'caches', 'crashdumps', 'webview2userdir',
        'ollama', 'packages',
        # AppData 子目录中的大文件夹
        'microsoft', 'tencent', 'google', 'mozilla', 'adobe',
        'wechatfiles', 'qqfiles', 'xiaomioffice', '小米办公',
        'temp', 'tmp', 'cache', 'logs',
        'thumbcache', 'iconcache',
    }
    # 完全跳过
    if dir_lower in skip_dirs:
        return True
    # AppData 下只保留部分
    if dir_lower == 'appdata':
        return True
    return False

def scan_all():
    """扫描所有路径，用 os.walk 提前跳过排除目录，返回 (all_files, excluded_with_scores)"""
    all_files = []
    excluded_valuable = []
    total_scanned = 0
    total_excluded = 0
    dirs_skipped = 0
    start = time.time()
    
    for scan_root in SCAN_ROOTS:
        if not scan_root.exists():
            continue
        print(f'  扫描: {scan_root}', flush=True)
        try:
            for dirpath, dirnames, filenames in os.walk(str(scan_root), topdown=True):
                # 提前剪枝: 跳过不需要的目录
                original_dirs = list(dirnames)
                dirnames[:] = []
                for d in original_dirs:
                    full_d = os.path.join(dirpath, d)
                    if should_skip_dir(full_d):
                        dirs_skipped += 1
                        continue
                    # 额外排除检查
                    if should_exclude(full_d):
                        dirs_skipped += 1
                        continue
                    dirnames.append(d)
                
                for fname in filenames:
                    total_scanned += 1
                    if total_scanned % 50000 == 0:
                        elapsed = time.time() - start
                        print(f'    已扫 {total_scanned:,} | 有效 {len(all_files):,} | 跳过 {dirs_skipped:,} dirs ({elapsed:.0f}s)', flush=True)
                    
                    fp = os.path.join(dirpath, fname)
                    
                    try:
                        size = os.path.getsize(fp)
                    except:
                        continue
                    
                    if size < MIN_FILE_SIZE or size > MAX_SCAN_SIZE:
                        continue
                    
                    name_lower = fname.lower()
                    if name_lower in ('desktop.ini', 'thumbs.db', 'ntuser.dat', 'ntuser.ini',
                                      'iconcache.db', 'swapfile.sys', 'pagefile.sys', 'hiberfil.sys',
                                      'iconcache_32.db', 'iconcache_16.db'):
                        continue
                    
                    ext = os.path.splitext(fname)[1]
                    
                    if should_exclude(fp):
                        total_excluded += 1
                        # 遗漏检测: 被排除但可能有价值？
                        score, reasons = is_potentially_valuable(fp, ext, size)
                        if score >= 20:
                            try:
                                mtime = datetime.fromtimestamp(os.path.getmtime(fp)).strftime('%Y-%m-%d %H:%M')
                            except:
                                mtime = ''
                            excluded_valuable.append({
                                'path': fp,
                                'name': fname,
                                'ext': ext,
                                'size': size,
                                'size_str': format_size(size),
                                'mtime': mtime,
                                'score': score,
                                'reasons': reasons,
                            })
                        continue
                    
                    try:
                        mtime = datetime.fromtimestamp(os.path.getmtime(fp)).strftime('%Y-%m-%d %H:%M')
                    except:
                        mtime = ''
                    hash_val = file_hash_quick(fp)
                    
                    all_files.append({
                        'path': fp,
                        'name': fname,
                        'ext': ext,
                        'size': size,
                        'size_str': format_size(size),
                        'mtime': mtime,
                        'hash': hash_val,
                    })
        except Exception as e:
            print(f'  警告: {scan_root} 扫描失败: {e}')
    
    elapsed = time.time() - start
    print(f'\n  扫描完成: 总计 {total_scanned:,} | 有效 {len(all_files):,} | 排除 {total_excluded:,} | 跳过目录 {dirs_skipped:,}')
    print(f'  遗漏候选: {len(excluded_valuable):,} | 耗时: {elapsed:.1f}s')
    return all_files, excluded_valuable

def format_size(b):
    if b >= 1024**3: return f'{b/1024**3:.1f} GB'
    if b >= 1024**2: return f'{b/1024**2:.1f} MB'
    if b >= 1024: return f'{b/1024:.1f} KB'
    return f'{b} B'

def generate_missed_report(excluded_valuable):
    """生成遗漏检测报告"""
    # 按分数排序
    excluded_valuable.sort(key=lambda x: -x['score'])
    
    # 按排除原因分组
    by_pattern = defaultdict(list)
    for item in excluded_valuable:
        # 找出是哪个排除模式命中的
        fp_lower = item['path'].lower()
        matched = []
        for pat in EXCLUDE_PATTERNS:
            if pat.lower() in fp_lower:
                matched.append(pat)
        item['exclude_patterns'] = matched
        for pat in matched:
            by_pattern[pat].append(item)
    
    report = {
        'generated': datetime.now().isoformat(),
        'total_excluded_valuable': len(excluded_valuable),
        'high_score_files': [f for f in excluded_valuable if f['score'] >= 40],
        'medium_score_files': [f for f in excluded_valuable if 20 <= f['score'] < 40],
        'by_exclude_pattern': {
            pat: {
                'count': len(files),
                'top_files': sorted(files, key=lambda x: -x['score'])[:10]
            }
            for pat, files in sorted(by_pattern.items(), key=lambda x: -len(x[1]))
        },
        'summary': {
            'high_risk': len([f for f in excluded_valuable if f['score'] >= 40]),
            'medium_risk': len([f for f in excluded_valuable if 20 <= f['score'] < 40]),
        }
    }
    return report

def main():
    print('=' * 64)
    print('  WSL 文件扫描器 + 遗漏检测')
    print('=' * 64)
    print()
    
    all_files, excluded_valuable = scan_all()
    
    print('\n  保存扫描结果...')
    
    # 保存全量扫描
    scan_path = OUTPUT_DIR / 'scan_results.json'
    with open(scan_path, 'w', encoding='utf-8') as f:
        json.dump({
            'generated': datetime.now().isoformat(),
            'total': len(all_files),
            'files': all_files,
        }, f, ensure_ascii=False, indent=2)
    print(f'  扫描结果: {scan_path}')
    
    # 保存遗漏检测报告
    if excluded_valuable:
        report = generate_missed_report(excluded_valuable)
        missed_path = OUTPUT_DIR / 'missed_report.json'
        with open(missed_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f'  遗漏报告: {missed_path}')
        
        # 打印摘要
        print(f'\n  ┌─ 遗漏检测结果 ──────────────────────────┐')
        print(f'  │ 高风险 (需审查): {report["summary"]["high_risk"]:>6} 个文件          │')
        print(f'  │ 中风险 (可忽略): {report["summary"]["medium_risk"]:>6} 个文件          │')
        print(f'  └───────────────────────────────────────────┘')
        
        if report['high_score_files']:
            print(f'\n  🔴 高风险 TOP 20:')
            for i, f in enumerate(report['high_score_files'][:20], 1):
                print(f'    {i:2}. [{f["score"]:2}] {f["name"]} ({f["size_str"]})')
                print(f'        {f["path"]}')
                print(f'        原因: {", ".join(f["reasons"][:3])}')
    else:
        print('  ✓ 未发现遗漏有价值文件')
    
    # 统计
    ext_stats = Counter(f['ext'].lower() for f in all_files)
    print(f'\n  ┌─ 扩展名 TOP 15 ──────────────────────────┐')
    for ext, cnt in ext_stats.most_common(15):
        bar = '█' * min(int(cnt / max(len(all_files), 1) * 40), 40)
        print(f'  │ {ext:10} {cnt:>6} {bar}')
    print(f'  └───────────────────────────────────────────┘')
    
    total_size = sum(f['size'] for f in all_files)
    print(f'\n  合计: {len(all_files):,} 个文件, {format_size(total_size)}')

if __name__ == '__main__':
    main()
