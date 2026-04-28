#!/usr/bin/env python3
"""
SimHash 增强去重 — 在现有三层去重基础上，用 simhash 做文本相似度检测
输入: scan_results.json (来自 scan_wsl.py)
输出: dedup_report.json
"""
import os
import json
import hashlib
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Tuple

OUTPUT_DIR = Path('/mnt/c/Users/hp/Desktop/文件迁移工具/output')
INPUT_FILE = OUTPUT_DIR / 'scan_results.json'

# ============ SimHash 实现 ============

class SimHash:
    """轻量 SimHash 实现，不依赖第三方库"""
    
    def __init__(self, hash_bits=64):
        self.hash_bits = hash_bits
    
    def _tokenize(self, text: str) -> List[str]:
        """分词: 中文按字，英文按词，混合按标点切"""
        tokens = []
        # 提取连续英文/数字
        for m in re.finditer(r'[a-zA-Z_]\w+', text):
            tokens.append(m.group().lower())
        # 提取连续中文字符 (bigram)
        cn_chars = re.findall(r'[\u4e00-\u9fff]', text)
        for i in range(len(cn_chars) - 1):
            tokens.append(cn_chars[i] + cn_chars[i+1])
        # 单个中文字符也作为 token
        tokens.extend(cn_chars)
        return tokens
    
    def _string_hash(self, token: str) -> int:
        """将 token 映射为 hash_bits 位的整数"""
        h = hashlib.md5(token.encode('utf-8')).hexdigest()
        return int(h[:16], 16)  # 取前64位
    
    def compute(self, text: str) -> int:
        """计算文本的 SimHash 值"""
        tokens = self._tokenize(text)
        if not tokens:
            return 0
        
        v = [0] * self.hash_bits
        for token in tokens:
            h = self._string_hash(token)
            for i in range(self.hash_bits):
                if h & (1 << i):
                    v[i] += 1
                else:
                    v[i] -= 1
        
        fingerprint = 0
        for i in range(self.hash_bits):
            if v[i] > 0:
                fingerprint |= (1 << i)
        return fingerprint
    
    @staticmethod
    def hamming_distance(h1: int, h2: int) -> int:
        """计算两个 SimHash 的汉明距离"""
        return bin(h1 ^ h2).count('1')
    
    @staticmethod
    def similarity(h1: int, h2: int, hash_bits=64) -> float:
        """相似度 (0~1)"""
        dist = SimHash.hamming_distance(h1, h2)
        return 1.0 - dist / hash_bits


def extract_text_preview(filepath: str, max_bytes=32768) -> str:
    """提取文件前 32KB 文本内容用于 simhash"""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read(max_bytes)
    except:
        try:
            with open(filepath, 'r', encoding='gbk', errors='ignore') as f:
                return f.read(max_bytes)
        except:
            return ''

def format_size(b):
    if b >= 1024**3: return f'{b/1024**3:.1f} GB'
    if b >= 1024**2: return f'{b/1024**2:.1f} MB'
    if b >= 1024: return f'{b/1024:.1f} KB'
    return f'{b} B'

def main():
    print('=' * 64)
    print('  SimHash 增强去重 (dry run)')
    print('=' * 64)
    print()
    
    if not INPUT_FILE.exists():
        print(f'  错误: 找不到 {INPUT_FILE}')
        print(f'  请先运行 scan_wsl.py')
        return
    
    print(f'  加载扫描结果: {INPUT_FILE}')
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    files = data['files']
    print(f'  文件总数: {len(files):,}')
    
    # 按快速哈希分组 (已有的 MD5 层)
    hash_groups = defaultdict(list)
    for i, f in enumerate(files):
        if f.get('hash'):
            hash_groups[f['hash']].append(i)
    
    exact_dups = sum(len(idxs) - 1 for idxs in hash_groups.values() if len(idxs) > 1)
    print(f'  现有去重 (MD5快速哈希): {exact_dups:,} 个精确重复')
    
    # ---- SimHash 层 ----
    # 只对文本文件做 simhash (非精确重复的部分)
    TEXT_EXTS = {
        '.txt', '.md', '.py', '.js', '.ts', '.c', '.cpp', '.h', '.hpp', '.java',
        '.go', '.rs', '.rb', '.php', '.cs', '.sql', '.sh', '.bat', '.ps1',
        '.yaml', '.yml', '.json', '.xml', '.html', '.css', '.ini', '.cfg',
        '.conf', '.env', '.toml', '.csv', '.rst', '.tex', '.log', '.vue',
        '.jsx', '.tsx', '.scss', '.less', '.r', '.lua', '.dart', '.zig',
    }
    
    # 过滤出文本文件 (排除已知精确重复)
    exact_dup_set = set()
    for idxs in hash_groups.values():
        if len(idxs) > 1:
            for idx in idxs[1:]:
                exact_dup_set.add(idx)
    
    text_files = []
    for i, f in enumerate(files):
        if i in exact_dup_set:
            continue
        if f['ext'].lower() in TEXT_EXTS and f['size'] < 2 * 1024 * 1024:
            text_files.append((i, f))
    
    print(f'  待 simhash 检测: {len(text_files):,} 个文本文件')
    
    # 计算 simhash
    sh = SimHash()
    print(f'  计算 SimHash...', flush=True)
    
    simhash_results = []
    for idx, (i, f) in enumerate(text_files):
        if idx % 1000 == 0 and idx > 0:
            print(f'    {idx:,}/{len(text_files):,} ...', flush=True)
        text = extract_text_preview(f['path'])
        if text:
            h = sh.compute(text)
            simhash_results.append((i, f, h))
    
    print(f'  有效 SimHash: {len(simhash_results):,}')
    
    # 按大小分桶，只比较相近的
    simhash_results.sort(key=lambda x: x[1]['size'])
    
    SIMILARITY_THRESHOLD = 0.85  # SimHash 相似度阈值
    HAMMING_THRESHOLD = 10       # 汉明距离阈值 (64位中 <=10 位不同)
    
    similar_pairs = []
    total_comparisons = 0
    
    print(f'  比对中 (阈值: 汉明距离<={HAMMING_THRESHOLD})...', flush=True)
    
    for a_idx in range(len(simhash_results)):
        if a_idx % 500 == 0 and a_idx > 0:
            print(f'    {a_idx:,}/{len(simhash_results):,} 已比对, 发现 {len(similar_pairs):,} 对疑似重复', flush=True)
        
        i_a, f_a, h_a = simhash_results[a_idx]
        
        for b_idx in range(a_idx + 1, len(simhash_results)):
            i_b, f_b, h_b = simhash_results[b_idx]
            
            # 大小差超过 20% 跳过
            if abs(f_a['size'] - f_b['size']) / max(f_a['size'], 1) > 0.20:
                break
            
            total_comparisons += 1
            hamming = SimHash.hamming_distance(h_a, h_b)
            
            if hamming <= HAMMING_THRESHOLD:
                similarity = SimHash.similarity(h_a, h_b)
                similar_pairs.append({
                    'file_a': f_a['path'],
                    'file_b': f_b['path'],
                    'name_a': f_a['name'],
                    'name_b': f_b['name'],
                    'size_a': f_a['size_str'],
                    'size_b': f_b['size_str'],
                    'hamming_distance': hamming,
                    'similarity': round(similarity, 4),
                })
    
    print(f'\n  比对完成: {total_comparisons:,} 次比较')
    print(f'  SimHash 疑似重复: {len(similar_pairs):,} 对')
    
    # 排序 (相似度最高的在前)
    similar_pairs.sort(key=lambda x: x['hamming_distance'])
    
    # 保存报告
    report = {
        'generated': datetime.now().isoformat(),
        'method': 'SimHash (64-bit, hamming distance threshold <= 10)',
        'total_text_files': len(text_files),
        'total_compared': len(simhash_results),
        'total_comparisons': total_comparisons,
        'similar_pairs_count': len(similar_pairs),
        'pairs': similar_pairs[:500],  # 最多保存500对
    }
    
    report_path = OUTPUT_DIR / 'dedup_simhash_report.json'
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f'  报告: {report_path}')
    
    # 打印 TOP 疑似重复
    if similar_pairs:
        print(f'\n  ┌─ SimHash 疑似重复 TOP 20 ─────────────────────────────┐')
        for i, p in enumerate(similar_pairs[:20], 1):
            print(f'  │ {i:2}. 汉明距离={p["hamming_distance"]:2} 相似度={p["similarity"]:.2%}')
            print(f'  │     A: {p["name_a"]} ({p["size_a"]})')
            print(f'  │     B: {p["name_b"]} ({p["size_b"]})')
            print(f'  │     {p["file_a"][:70]}')
            print(f'  │     {p["file_b"][:70]}')
        print(f'  └─────────────────────────────────────────────────────────┘')
    else:
        print(f'\n  ✓ 未发现 SimHash 疑似重复')

if __name__ == '__main__':
    main()
