#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件迁移工具 v3.2 - 6维RAG打标 + 工业智能分类 + SimHash去重
自动扫描所有磁盘，识别有价值文件，按6维标签整理到移动硬盘。
支持: 移动硬盘自动检测, 四层去重(含SimHash), AI深度感知, 品牌/应用自动发现

用法:
  python organize_files.py              # 交互式扫描+拷贝
  python organize_files.py --dry-run    # 只预览不拷贝
  python organize_files.py --ai         # 启用AI深度感知
  python organize_files.py --ai --auto-discover  # AI + 品牌自动发现
"""

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# ============================================================
#  配置常量
# ============================================================

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

SCAN_PATHS = [
    Path(os.environ.get("USERPROFILE", "C:\\Users\\hp")) / "Desktop",
    Path(os.environ.get("USERPROFILE", "C:\\Users\\hp")) / "Documents",
    Path(os.environ.get("USERPROFILE", "C:\\Users\\hp")) / "Downloads",
    Path("C:\\Users\\Public"),
]

OUTPUT_ROOT = Path(os.environ.get("USERPROFILE", "C:\\Users\\hp")) / "Desktop" / "文件迁移整理"

MIN_FILE_SIZE = 1024
DEFAULT_MAX_SIZE = 10 * 1024 * 1024 * 1024

EXCLUDE_DIRS = {
    "Windows", "$Recycle.Bin", "System Volume Information", "Recovery",
    "$WinREAgent", "ProgramData", "PerfLogs",
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv",
    ".idea", ".vscode", ".gradle", ".maven", "target", "build", "dist",
    ".npm", ".yarn", ".cargo", ".rustup", ".conda", ".anaconda",
    "Cache", "cache", "GPUCache", "DawnCache", "DawnWebGPUCache",
    "Service Worker", "IndexedDB", "Local Storage",
    "Temp", "tmp", "Prefetch", "Installer", "WinSxS",
    "AppData", "Local Settings", "Application Data",
    "Thumbs.db", "desktop.ini", "__MACOSX",
}

SKIP_EXTS = {
    ".sys", ".dll", ".exe", ".msi", ".drv", ".inf", ".cat",
    ".tmp", ".temp", ".bak", ".swp", ".swo",
    ".cache", ".log",
    ".crx", ".xpi",
    ".xml", ".lnk", ".ink", ".va", ".vr", ".dg", ".dt", ".fvr",
    ".gif", ".pc", ".stm", ".ini", ".sv",
    ".ls", ".tp", ".io", ".cm", ".kl",
    ".plf", ".al16", ".zal16",
}
MIN_IMAGE_SIZE = 100 * 1024  # 100KB — 小于此的图片直接跳过

CODE_EXTS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala",
    ".sql", ".sh", ".ps1", ".bat", ".cmd", ".bash", ".zsh",
    ".html", ".css", ".scss", ".less", ".vue", ".svelte",
    ".r", ".m", ".mm", ".pl", ".lua", ".dart", ".zig",
}

VALUABLE_EXTS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".md", ".rst", ".tex", ".csv", ".json", ".yaml", ".yml",
    ".cfg", ".toml", ".env", ".conf",
    ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp",
    ".mp4", ".avi", ".mkv", ".mov", ".wmv",
    ".mp3", ".wav", ".flac", ".aac",
    ".zip", ".rar", ".7z", ".tar", ".gz",
    ".dwg", ".dxf", ".step", ".stp", ".iges", ".igs", ".stl", ".obj",
    ".3ds", ".skp", ".ipt", ".iam", ".sldprt", ".sldasm", ".slddrw",
    ".psd", ".ai", ".svg", ".eps",
}

RECHECK_PATTERNS = ["Backup", "backup", "Temp", "tmp", "Cache", "cache", "Logs"]

# 6维标签数据类
@dataclass
class Tags6D:
    topic: str = "其他"
    doc_type: str = "其他"
    domain: str = "其他"
    priority: str = "低"
    time_tag: str = "不确定"
    source: str = "其他"

@dataclass
class FileInfo:
    path: str
    name: str
    ext: str
    size: int
    mtime: str
    tags: Tags6D
    md5: str = ""
    dest: str = ""
    group: str = ""  # 所属文件夹组名（项目文件夹绑定迁移用）

# ============================================================
#  品牌/应用映射
# ============================================================

BRAND_APP_MAP = {
    "FANUC":   ("FANUC_机器人", ["fanuc", "发那科"]),
    "FESTO":   ("FESTO_气动",   ["festo"]),
    "KUKA":    ("KUKA_机器人",  ["kuka", "库卡"]),
    "SMC":     ("SMC_气动",     ["smc"]),
    "Atlas":   ("Atlas_压缩机", ["atlas", "阿特拉斯", "atlas copco"]),
    "ISV":     ("ISV_视觉",     ["isv"]),
    "QUISS":   ("QUISS_质检",   ["quiss"]),
    "VMT":     ("VMT_视觉",     ["vmt"]),
    "XYZ":     ("XYZ_设备",     ["xyz"]),
    "商科":    ("商科_设备",     ["商科"]),
    "Siemens":  ("Siemens_西门子", ["siemens", "西门子", "sinumerik", "simatic", "tia"]),
    "ABB":      ("ABB_机器人",    ["abb"]),
    "Yaskawa":  ("Yaskawa_安川",  ["yaskawa", "安川", "motoman"]),
    "Mitsubishi": ("Mitsubishi_三菱", ["mitsubishi", "三菱", "melsec"]),
    "Omron":    ("Omron_欧姆龙",  ["omron", "欧姆龙"]),
    "Schneider": ("Schneider_施耐德", ["schneider", "施耐德", "modicon"]),
    "Beckhoff": ("Beckhoff_倍福",  ["beckhoff", "倍福", "twincat"]),
    "Rockwell": ("Rockwell_AB",   ["rockwell", "allen-bradley", "compactlogix", "controllogix"]),
    "Keyence":  ("Keyence_基恩士", ["keyence", "基恩士"]),
    "Cognex":   ("Cognex_视觉",   ["cognex"]),
    "Halcon":   ("Halcon_视觉",   ["halcon", "mvtec"]),
    "EPLAN":    ("EPLAN_电气",    ["eplan"]),
    "SolidWorks": ("SolidWorks_CAD", ["solidworks"]),
    "AutoCAD":  ("AutoCAD_CAD",   ["autocad"]),
    "CATIA":    ("CATIA_CAD",     ["catia"]),
    "NX":       ("NX_CAD",        ["nx", "ug"]),
    "Inventor":  ("Inventor_CAD",  ["inventor"]),
    "Creo":      ("Creo_CAD",      ["creo", "proe"]),
    "Comau":    ("Comau_机器人",   ["comau"]),
    "Epson":    ("Epson_机器人",   ["epson"]),
    "Kawasaki": ("Kawasaki_机器人", ["kawasaki", "川崎"]),
    "Denso":    ("Denso_机器人",   ["denso"]),
    "Panasonic": ("Panasonic_焊接", ["panasonic", "松下", "tm"]),
    "IGM":      ("IGM_焊接",       ["igm"]),
    "CLOOS":    ("CLOOS_焊接",     ["cloos"]),
    "Fronius":  ("Fronius_焊接",   ["fronius"]),
    "Lincoln":  ("Lincoln_焊接",   ["lincoln"]),
    "ESAB":     ("ESAB_焊接",      ["esab"]),
    "Hypertherm": ("Hypertherm_切割", ["hypertherm"]),
    "Trumpf":   ("Trumpf_激光",    ["trumpf", "通快"]),
    "Bystronic": ("Bystronic_激光", ["bystronic", "百超"]),
}

APP_KEYWORD_MAP = {
    "机器人":  "机器人应用",
    "robot":   "机器人应用",
    "nc":      "NC_数控",
    "数控":    "NC_数控",
    "fds":     "FDS_系统",
    "地轨":    "地轨_行走轴",
    "导轨":    "地轨_行走轴",
    "行走轴":  "地轨_行走轴",
    "视觉":    "视觉应用",
    "焊机":    "焊接应用",
    "焊接":    "焊接应用",
    "搬运":    "搬运应用",
    "码垛":    "码垛应用",
    "涂胶":    "涂胶应用",
    "打磨":    "打磨应用",
    "切割":    "切割应用",
    "折弯":    "折弯应用",
    "冲压":    "冲压应用",
    "装配":    "装配应用",
    "检测":    "检测应用",
    "测量":    "测量应用",
    "伺服":    "伺服系统",
    "变频":    "变频系统",
    "hmi":     "HMI_人机界面",
    "触摸屏":  "HMI_人机界面",
    "i/o":     "IO_模块",
    "profibus": "现场总线",
    "profinet": "现场总线",
    "ethercat": "现场总线",
    "modbus":   "现场总线",
    "opc":      "通信协议",
    "mqtt":     "通信协议",
}

FOLDER_CATEGORY_MAP = {
    "FANUC": "机器人", "fanuc": "机器人", "发那科": "机器人",
    "KUKA": "机器人", "kuka": "机器人", "库卡": "机器人",
    "FESTO": "气动", "festo": "气动", "SMC": "气动", "smc": "气动",
    "Atlas": "压缩机", "ISV": "视觉", "QUISS": "质检", "VMT": "视觉",
    "项目": "项目管理", "合同": "商务", "报告": "报告",
    "技术": "技术", "电气": "电气", "机器人": "机器人",
    "ABB": "机器人", "Yaskawa": "机器人", "安川": "机器人",
    "Mitsubishi": "电气", "三菱": "电气", "Siemens": "电气", "西门子": "电气",
    "Omron": "电气", "欧姆龙": "电气", "Schneider": "电气", "施耐德": "电气",
    "Beckhoff": "电气", "倍福": "电气", "Rockwell": "电气",
    "Keyence": "视觉", "基恩士": "视觉", "Cognex": "视觉", "Halcon": "视觉",
    "EPLAN": "电气", "SolidWorks": "设计", "AutoCAD": "设计",
    "CATIA": "设计", "NX": "设计", "Inventor": "设计", "Creo": "设计",
    "B1": "现场项目", "B2": "现场项目", "武汉": "现场项目",
    "Micar": "Micar项目", "AIAIAI": "AIAIAI项目",
    "SCADA": "SCADA系统", "EPLAN": "电气",
    "焊接": "焊接", "weld": "焊接", "Panasonic": "焊接",
    "Downloads": "下载", "下载": "下载",
    "参考": "参考资料", "供应商": "供应商",
    "互传": "互传文件", "Desktop": "桌面",
    "Documents": "文档", "backup": "备份", "Backup": "备份",
}

TYPE_TO_DIR = {
    "文档": "02_文档", "代码": "01_代码", "数据": "03_数据",
    "配置": "04_配置", "报告": "05_报告", "其他": "06_待确认",
    "图片": "07_媒体/图片", "视频": "07_媒体/视频", "音频": "07_媒体/音频",
    "压缩包": "08_压缩包", "设计": "09_设计", "字体": "10_字体",
    "工业程序": "11_工业程序", "CAD支持": "12_CAD支持",
}

# ============================================================
#  辅助函数
# ============================================================

def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024*1024):.1f} MB"
    else:
        return f"{size_bytes / (1024*1024*1024):.2f} GB"


def file_md5(filepath: str, chunk_size: int = 8192) -> str:
    try:
        h = hashlib.md5()
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except:
        return ""


def should_skip_dir(dirpath: str) -> bool:
    dir_name = os.path.basename(dirpath)
    if dir_name in EXCLUDE_DIRS:
        return True
    parts = Path(dirpath).parts
    for part in parts:
        if part in EXCLUDE_DIRS:
            return True
    return False


def should_exclude(filepath: str) -> bool:
    name = os.path.basename(filepath).lower()
    if name in ("desktop.ini", "thumbs.db", "ntuser.dat", "ntuser.ini",
                "iconcache.db", "swapfile.sys", "pagefile.sys", "hiberfil.sys"):
        return True
    if name.startswith("."):
        return True
    if name.endswith("tic.zip"):  # FANUC 备份包
        return True
    return False


def detect_removable_drives() -> list:
    drives = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        drive_path = f"{letter}:\\"
        try:
            usage = shutil.disk_usage(drive_path)
            if letter == "C":
                continue
            drives.append({
                "letter": letter,
                "path": drive_path,
                "total_gb": usage.total / (1024**3),
                "free_gb": usage.free / (1024**3),
                "used_gb": usage.used / (1024**3),
            })
        except:
            continue
    return drives


def choose_target_drive(drives: list) -> Optional[Path]:
    if not drives:
        print("  未检测到可用磁盘，将使用桌面目录")
        return None
    print("  检测到以下磁盘:")
    for i, d in enumerate(drives, 1):
        print(f"    [{i}] {d['letter']}:\\ (空闲 {d['free_gb']:.0f} GB / 总计 {d['total_gb']:.0f} GB)")
    while True:
        choice = input(f"  选择目标磁盘 (1-{len(drives)}, 回车=自动选择最大): ").strip()
        if not choice:
            best = max(drives, key=lambda d: d["free_gb"])
            print(f"  自动选择: {best['letter']}\\ (空闲 {best['free_gb']:.0f} GB)")
            return Path(best["path"])
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(drives):
                d = drives[idx]
                print(f"  选择: {d['letter']}\\ (空闲 {d['free_gb']:.0f} GB)")
                return Path(d["path"])
        except ValueError:
            pass
        print("  无效选择，请重试")

# ============================================================
#  标签生成
# ============================================================

def get_tags(ext: str, filepath: str, size: int) -> Tags6D:
    """根据扩展名/路径/大小生成6维标签"""
    ext_lower = ext.lower()
    name_lower = os.path.basename(filepath).lower()
    path_lower = filepath.lower()

    # doc_type
    doc_exts = {".pdf", ".doc", ".docx", ".txt", ".md", ".rst", ".tex", ".rtf", ".odt", ".pages"}
    data_exts = {".xls", ".xlsx", ".csv", ".json", ".xml",
                 ".xlsm", ".xlsb",
                 ".db", ".sqlite", ".mdb", ".accdb", ".parquet", ".feather", ".hdf5", ".h5"}
    config_exts = {".ini", ".cfg", ".conf", ".env", ".properties", ".reg",
                   ".yaml", ".yml", ".toml"}
    code_exts_t = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h",
                   ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt",
                   ".scala", ".sql", ".sh", ".ps1", ".bat", ".cmd", ".html", ".css",
                   ".scss", ".less", ".vue", ".svelte", ".r", ".lua", ".dart", ".zig"}
    report_exts = {".ppt", ".pptx", ".odp", ".key"}
    image_exts_t = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".heic",
                    ".webp", ".raw", ".cr2", ".nef", ".arw", ".dng", ".ico", ".svg", ".psd", ".ai", ".eps"}
    video_exts_t = {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".webm", ".flv",
                    ".m4v", ".mpg", ".mpeg", ".3gp", ".ts", ".vob"}
    audio_exts_t = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a", ".opus", ".mid", ".midi"}
    archive_exts_t = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".iso", ".img", ".dmg"}
    cad_exts_t = {".dwg", ".dxf", ".step", ".stp", ".iges", ".igs", ".stl", ".obj",
                  ".3ds", ".skp", ".f3d", ".ipt", ".iam", ".catpart", ".catproduct",
                  ".prt", ".asm", ".drw", ".sldprt", ".sldasm", ".slddrw"}
    font_exts_t = {".ttf", ".otf", ".woff", ".woff2", ".eot"}
    fanuc_exts_t = {".tp", ".vr", ".sv", ".ls", ".dg", ".dt", ".pc", ".cm", ".io",
                    ".va", ".kl", ".pm", ".pn", ".rbt", ".sch_txt"}
    cad_support_t = {".lsp", ".dcl", ".shx", ".pat", ".lin", ".ctb", ".stb",
                     ".dwt", ".dws", ".arx", ".crx", ".dvb", ".fas"}
    web_log_t = {".htm", ".html", ".log", ".pak", ".qm", ".cab", ".tlb", ".fx"}

    if ext_lower in doc_exts:
        doc_type = "文档"
    elif ext_lower in data_exts:
        doc_type = "数据"
    elif ext_lower in config_exts:
        doc_type = "配置"
    elif ext_lower in code_exts_t:
        doc_type = "代码"
    elif ext_lower in report_exts:
        doc_type = "报告"
    elif ext_lower in image_exts_t:
        doc_type = "图片"
    elif ext_lower in video_exts_t:
        doc_type = "视频"
    elif ext_lower in audio_exts_t:
        doc_type = "音频"
    elif ext_lower in archive_exts_t:
        doc_type = "压缩包"
    elif ext_lower in cad_exts_t:
        doc_type = "设计"
    elif ext_lower in font_exts_t:
        doc_type = "字体"
    elif ext_lower in fanuc_exts_t:
        doc_type = "工业程序"
    elif ext_lower in cad_support_t:
        doc_type = "CAD支持"
    elif ext_lower in web_log_t:
        doc_type = "其他"
    else:
        doc_type = "其他"

    # topic
    tech_kw = ["技术", "manual", "guide", "datasheet", "spec", "specification",
               "api", "sdk", "protocol", "algorithm", "电路", "原理图", "编程",
               "操作手册", "安装", "维护", "保养", "参数", "设置", "配置",
               "operation", "maintenance", "install", "troubleshoot", "diagnostic",
               "schematic", "wiring", "接线", "调试", "commissioning", "plc",
               "instruction", "reference", "documentation", "readme",
               "技术交底", "专利", "patent", "公式", "原理"]
    work_kw = ["合同", "协议", "contract", "agreement", "报价", "invoice", "发票",
               "项目", "project", "方案", "proposal", "sop", "标准", "standard",
               "规范", "requirement", "需求", "评审", "review", "验收", "acceptance",
               "交付", "deliver", "meeting", "会议", "纪要", "通知", "notice",
               "计划", "plan", "进度", "schedule", "budget", "预算", "采购", "purchase"]
    study_kw = ["教程", "tutorial", "学习", "笔记", "note", "课程", "培训", "training",
                "论文", "paper", "article", "白皮书", "whitepaper", "案例", "case",
                "考试", "exam", "练习", "exercise", "book", "书", "readme"]
    personal_kw = ["个人", "personal", "简历", "resume", "照片", "photo",
                   "证件", "certificate", "保险", "insurance", "医疗", "体检",
                   "工资", "salary", "账单", "bill", "收据", "receipt"]

    if any(kw in name_lower or kw in path_lower for kw in tech_kw):
        topic = "技术"
    elif any(kw in name_lower or kw in path_lower for kw in work_kw):
        topic = "工作"
    elif any(kw in name_lower or kw in path_lower for kw in study_kw):
        topic = "学习"
    elif any(kw in name_lower or kw in path_lower for kw in personal_kw):
        topic = "个人"
    else:
        topic = "其他"

    # domain
    robot_kw = ["robot", "机器人", "fanuc", "kuka", "发那科", "库卡", "机械臂",
                "abb", "yaskawa", "安川", "comau", "川崎", "kawasaki", "epson",
                "denso", "otc", "松下", "panasonic", "igm", "reis"]
    elec_kw = ["电气", "electric", "plc", "电路", "wiring", "接线", "siemens",
               "西门子", "schneider", "施耐德", "omron", "欧姆龙", "mitsubishi",
               "三菱", "ab", "allen-bradley", "rockwell", "beckhoff", "倍福",
               "hmi", "scada", "dcs", "变频器", "inverter", "伺服", "servo"]
    dev_kw = ["code", "programming", "开发", "dev", "software", "软件",
              "github", "gitlab", "repository", "repo", "sdk", "api", "framework",
              "library", "package", "npm", "pip", "cargo", "maven", "gradle"]
    vision_kw = ["视觉", "vision", "camera", "相机", "图像", "image", "halcon",
                 "opencv", "cognex", "keyence", "基恩士", "isv", "vmt"]
    weld_kw = ["焊接", "weld", "焊机", "welder", "焊枪", "torch", "arc", "激光焊",
               "laser weld", "friction", "摩擦焊", "点焊", "spot"]
    mech_kw = ["机械", "mechanical", "cad", "solidworks", "catia", "ug", "nx",
               "autocad", "inventor", "creo", "proe", "sw", "零件", "装配", "工程图"]
    compress_kw = ["压缩机", "compressor", "atlas", "阿特拉斯", "气动", "pneumatic",
                   "festo", "smc", "气缸", "cylinder", "阀", "valve"]

    if any(kw in name_lower or kw in path_lower for kw in robot_kw):
        domain = "机器人"
    elif any(kw in name_lower or kw in path_lower for kw in elec_kw):
        domain = "电气"
    elif any(kw in name_lower or kw in path_lower for kw in dev_kw):
        domain = "开发"
    elif any(kw in name_lower or kw in path_lower for kw in vision_kw):
        domain = "视觉"
    elif any(kw in name_lower or kw in path_lower for kw in weld_kw):
        domain = "焊接"
    elif any(kw in name_lower or kw in path_lower for kw in mech_kw):
        domain = "机械设计"
    elif any(kw in name_lower or kw in path_lower for kw in compress_kw):
        domain = "气动/压缩"
    else:
        domain = "其他"

    # source (must be before priority, which references source)
    if "download" in path_lower or "下载" in path_lower:
        source = "下载资料"
    elif "desktop" in path_lower or "桌面" in path_lower:
        source = "个人创作"
    elif any(kw in path_lower for kw in ["project", "项目"]):
        source = "项目产出"
    else:
        source = "其他"

    # priority
    if doc_type in ("文档", "报告", "设计") and topic in ("技术", "工作"):
        priority = "高"
    elif doc_type in ("数据", "代码") and topic in ("工作", "技术"):
        priority = "高"
    elif doc_type in ("图片", "视频", "音频") and topic in ("技术", "工作"):
        priority = "中"
    elif doc_type == "压缩包" and topic == "技术":
        priority = "中"
    elif doc_type == "配置":
        priority = "低"
    elif doc_type == "其他" and source in ("个人创作", "项目产出"):
        priority = "中"
    elif doc_type in ("图片", "视频", "音频", "字体"):
        priority = "低"
    elif doc_type == "工业程序":
        priority = "高"
    elif doc_type == "CAD支持":
        priority = "低"
    else:
        priority = "中"

    # time_tag
    if doc_type == "配置":
        time_tag = "长期有效"
    elif doc_type == "报告":
        time_tag = "短期"
    elif doc_type in ("设计", "代码"):
        time_tag = "长期有效"
    elif doc_type in ("图片", "视频", "音频"):
        time_tag = "长期有效"
    elif doc_type == "压缩包":
        time_tag = "不确定"
    elif doc_type == "工业程序":
        time_tag = "长期有效"
    elif doc_type == "CAD支持":
        time_tag = "长期有效"
    else:
        time_tag = "不确定"

    return Tags6D(topic, doc_type, domain, priority, time_tag, source)


def get_source_folder_hint(filepath: str) -> str:
    """从文件路径提取源文件夹分类提示"""
    parts = Path(filepath).parts
    # 先精确匹配（高优先级）
    for part in reversed(parts[:-1]):
        if part in FOLDER_CATEGORY_MAP:
            return FOLDER_CATEGORY_MAP[part]
    # 再大小写不敏感匹配
    for part in reversed(parts[:-1]):
        part_lower = part.lower()
        for key, val in FOLDER_CATEGORY_MAP.items():
            if key.lower() == part_lower:
                return val
    return ""


def resolve_doc_subdir(filepath: str, filename: str) -> str:
    """根据文件名/路径特征，返回文档子目录。返回None走默认路径。"""
    fn_lower = filename.lower()
    fp_lower = filepath.lower()

    # 第一优先级: 特殊文档类型
    if any(kw in fn_lower for kw in ["会议", "纪要", "meeting", "minutes", "会议记录", "研讨"]):
        return "02_文档/会议纪要"

    if filename.upper().startswith("B-") and fn_lower.endswith(".pdf"):
        return "02_文档/FANUC_EDOC"

    if any(kw in fn_lower for kw in ["合同", "协议", "contract", "agreement", "nda"]):
        return "02_文档/合同协议"

    # 第二优先级: 品牌匹配
    for brand_key, (app_dir, keywords) in BRAND_APP_MAP.items():
        if any(kw in fn_lower or kw in fp_lower for kw in keywords):
            return f"02_文档/{brand_key}/{app_dir}"

    # 第三优先级: 应用关键词匹配
    for app_kw, app_dir in APP_KEYWORD_MAP.items():
        if app_kw in fn_lower or app_kw in fp_lower:
            return f"02_文档/应用/{app_dir}"

    # 第四优先级: 通用文档子类
    if any(kw in fn_lower for kw in ["手册", "说明书", "manual", "guide", "datasheet"]):
        return "02_文档/技术手册"
    if any(kw in fn_lower for kw in ["报告", "方案", "report", "proposal", "spec"]):
        return "02_文档/报告方案"

    return None


# ============================================================
#  未命名媒体检测
# ============================================================

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif",
              ".heic", ".webp", ".raw", ".cr2", ".nef", ".arw", ".dng"}
VIDEO_EXTS = {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".webm", ".flv",
              ".m4v", ".mpg", ".mpeg", ".3gp"}

def is_meaningful_name(filename: str) -> bool:
    """判断文件名是否有含义 (非相机默认命名)"""
    import re
    # 相机默认: IMG_20240101_123456.jpg, DSC_0001.jpg, VID_2024...
    if re.match(r"^(IMG|DSC|VID|MOV|DCIM)_\d+", filename, re.I):
        return False
    # 纯数字
    stem = Path(filename).stem
    if re.match(r"^\d+$", stem):
        return False
    # 有中文或有意义的英文单词
    if re.search(r"[\u4e00-\u9fff]", stem):
        return True
    if re.search(r"[a-zA-Z]{3,}", stem) and not re.match(r"^[A-Z]{2,4}_\d+", filename):
        return True
    return False


def get_media_subdir(filepath: str, filename: str) -> str:
    """媒体文件子目录分类"""
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTS:
        if is_meaningful_name(filename):
            return None  # 走默认的媒体目录
        return "07_媒体/未命名图片"
    elif ext in VIDEO_EXTS:
        if is_meaningful_name(filename):
            return None
        return "07_媒体/未命名视频"
    return None

# ============================================================
#  AI 分析函数
# ============================================================

def ai_analyze_document(filepath: str, ext: str, size: int):
    """调用 DeepSeek API 分析文档内容, 返回6维标签"""
    if not DEEPSEEK_API_KEY:
        return None
    text_exts = {".txt", ".md", ".rst", ".adoc", ".log", ".csv", ".json",
                 ".yaml", ".yml", ".xml", ".ini", ".cfg", ".conf", ".toml"}
    if ext.lower() not in text_exts:
        return None
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            preview = f.read(2048)
    except:
        return None
    if len(preview.strip()) < 50:
        return None

    import urllib.request
    import json as _json

    prompt = (
        "Analyze this file content and return 6-dimension tags as JSON:\n"
        f"File: {filepath}\nSize: {size} bytes\nExt: {ext}\n\n"
        f"Content preview:\n{preview[:1500]}\n\n"
        "Return pure JSON (no markdown):\n"
        '{"topic": "tech/personal/work/study/other", '
        '"doc_type": "doc/code/data/config/report/other", '
        '"domain": "dev/electrical/robot/project_mgmt/other", '
        '"priority": "high/medium/low", '
        '"time_tag": "long_term/short_term/uncertain", '
        '"source": "self_made/download/system/project/supplier/other"}'
    )

    try:
        data = _json.dumps({
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 200
        }).encode("utf-8")

        req = urllib.request.Request(
            DEEPSEEK_API_URL,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + DEEPSEEK_API_KEY
            }
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = _json.loads(resp.read().decode("utf-8"))
            content = result["choices"][0]["message"]["content"].strip()
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            tags_dict = _json.loads(content)
            _t = {"tech":"技术","personal":"个人","work":"工作","study":"学习","other":"其他"}
            _d = {"doc":"文档","code":"代码","data":"数据","config":"配置","report":"报告","other":"其他"}
            _dm = {"dev":"开发","electrical":"电气","robot":"机器人","project_mgmt":"项目管理","other":"其他"}
            _p = {"high":"高","medium":"中","low":"低"}
            _tt = {"long_term":"长期有效","short_term":"短期","uncertain":"不确定"}
            _s = {"self_made":"个人创作","download":"下载资料","system":"系统生成","project":"项目产出","supplier":"供应商","other":"其他"}
            return Tags6D(
                topic=_t.get(tags_dict.get("topic","other"),"其他"),
                doc_type=_d.get(tags_dict.get("doc_type","other"),"其他"),
                domain=_dm.get(tags_dict.get("domain","other"),"其他"),
                priority=_p.get(tags_dict.get("priority","low"),"低"),
                time_tag=_tt.get(tags_dict.get("time_tag","uncertain"),"不确定"),
                source=_s.get(tags_dict.get("source","other"),"其他"),
            )
    except Exception:
        return None


def ai_discover_brands(files: List[FileInfo]) -> int:
    """扫描文件名/路径，用AI批量发现新品牌/应用，注入到 BRAND_APP_MAP 和 APP_KEYWORD_MAP。
    返回新发现的品牌+应用数量。"""
    if not DEEPSEEK_API_KEY:
        return 0

    import urllib.request
    import json as _json

    unmatched = []
    for f in files:
        if f.tags.doc_type not in ("文档", "数据"):
            continue
        fn_lower = f.name.lower()
        fp_lower = f.path.lower()
        matched = False
        for _, (_, keywords) in BRAND_APP_MAP.items():
            if any(kw in fn_lower or kw in fp_lower for kw in keywords):
                matched = True
                break
        if not matched:
            for app_kw in APP_KEYWORD_MAP:
                if app_kw in fn_lower or app_kw in fp_lower:
                    matched = True
                    break
        if not matched:
            unmatched.append(f"{f.name} | {os.path.dirname(f.path)}")

    if not unmatched:
        return 0

    sample = unmatched[:100]
    sample_text = "\n".join(sample)

    prompt = (
        "以下是从工业设备相关电脑中扫描的文档文件名和路径。\n"
        "请识别其中的品牌名(如FANUC/KUKA/西门子等)和应用领域(如焊接/视觉/数控等)。\n\n"
        f"文件列表:\n{sample_text}\n\n"
        "返回纯JSON数组，每个元素格式:\n"
        '{"type":"brand","key":"品牌名","keywords":["关键词1","关键词2"],"dir":"品牌_应用类型"}\n'
        "或\n"
        '{"type":"app","keyword":"关键词","dir":"应用目录名"}\n\n'
        "只返回JSON数组，不要markdown代码块。"
    )

    try:
        data = _json.dumps({
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 1500
        }).encode("utf-8")

        req = urllib.request.Request(
            DEEPSEEK_API_URL,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + DEEPSEEK_API_KEY
            }
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = _json.loads(resp.read().decode("utf-8"))
            content = result["choices"][0]["message"]["content"].strip()
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            discoveries = _json.loads(content)

        added = 0
        for item in discoveries:
            if item.get("type") == "brand":
                key = item.get("key", "")
                keywords = item.get("keywords", [])
                dir_name = item.get("dir", f"{key}_设备")
                if key and keywords and key not in BRAND_APP_MAP:
                    BRAND_APP_MAP[key] = (dir_name, keywords)
                    added += 1
                    print(f"    + 新品牌: {key} -> {dir_name} (关键词: {', '.join(keywords)})")
            elif item.get("type") == "app":
                keyword = item.get("keyword", "")
                dir_name = item.get("dir", f"{keyword}_应用")
                if keyword and keyword not in APP_KEYWORD_MAP:
                    APP_KEYWORD_MAP[keyword] = dir_name
                    added += 1
                    print(f"    + 新应用: {keyword} -> {dir_name}")
        return added
    except Exception as e:
        print(f"    AI品牌发现失败: {e}")
        return 0


# ============================================================
#  扫描、去重、复制、报告
# ============================================================

def scan_files(paths: List[Path], max_size: int, use_ai: bool = False) -> List[FileInfo]:
    """扫描文件: os.walk + 目录剪枝 + 延迟MD5"""
    files = []
    skipped = 0
    total = 0
    code_skipped = 0
    dirs_skipped = 0
    ai_analyzed = 0
    for scan_dir in paths:
        if not scan_dir.exists():
            continue
        print(f"  扫描: {scan_dir}", flush=True)
        try:
            for dirpath, dirnames, filenames in os.walk(str(scan_dir), topdown=True):
                original_dirs = list(dirnames)
                dirnames[:] = []
                for d in original_dirs:
                    full_d = os.path.join(dirpath, d)
                    if should_skip_dir(full_d):
                        dirs_skipped += 1
                        continue
                    dirnames.append(d)
                for fname in filenames:
                    total += 1
                    if total % 10000 == 0:
                        print(f"    已扫描 {total:,} | 有效 {len(files):,} | 跳过目录 {dirs_skipped:,}", flush=True)
                    fp = os.path.join(dirpath, fname)
                    if should_exclude(fp):
                        skipped += 1
                        continue
                    try:
                        size = os.path.getsize(fp)
                    except:
                        skipped += 1
                        continue
                    if size < MIN_FILE_SIZE or size > max_size:
                        skipped += 1
                        continue
                    entry = Path(fp)
                    ext_lower = entry.suffix.lower()
                    if ext_lower in SKIP_EXTS:
                        skipped += 1
                        continue
                    if ext_lower in CODE_EXTS:
                        code_skipped += 1
                        continue
                    # 小图片跳过
                    if ext_lower in IMAGE_EXTS and size < MIN_IMAGE_SIZE:
                        skipped += 1
                        continue
                    try:
                        mtime_ts = os.path.getmtime(fp)
                        mtime = datetime.fromtimestamp(mtime_ts).strftime('%Y-%m-%d %H:%M')
                    except:
                        mtime = ''
                    ext = entry.suffix
                    tags = get_tags(ext, fp, size)
                    folder_hint = get_source_folder_hint(fp)
                    if folder_hint:
                        # folder_hint 优先用于补充 domain
                        if tags.domain == '其他':
                            tags = Tags6D(tags.topic, tags.doc_type, folder_hint,
                                          tags.priority, tags.time_tag, tags.source)
                    if use_ai and tags.doc_type in ('文档', '其他') and tags.priority != '高':
                        ai_tags = ai_analyze_document(fp, ext, size)
                        if ai_tags:
                            tags = ai_tags
                            ai_analyzed += 1
                    files.append(FileInfo(path=fp, name=entry.name, ext=ext,
                                          size=size, mtime=mtime, tags=tags, md5=''))
        except Exception as e:
            print(f"  警告: {scan_dir} 扫描失败: {e}")
    ai_info = f", AI分析 {ai_analyzed:,}" if use_ai else ""
    print(f"  扫描完成: 总计 {total:,}, 有效 {len(files):,}, 跳过 {skipped:,}, 代码跳过 {code_skipped:,}, 跳过目录 {dirs_skipped:,}{ai_info}")
    return files


class SimHash:
    """轻量 SimHash 实现，用于文本文件近似去重"""
    @staticmethod
    def compute(text: str) -> int:
        import re as _re
        tokens = [m.group().lower() for m in _re.finditer(r'[a-zA-Z_]\w+', text)]
        cn = _re.findall(r'[\u4e00-\u9fff]', text)
        for i in range(len(cn)-1):
            tokens.append(cn[i]+cn[i+1])
        tokens.extend(cn)
        if not tokens:
            return 0
        v = [0]*64
        for t in tokens:
            h = int(hashlib.md5(t.encode()).hexdigest()[:16], 16)
            for i in range(64):
                v[i] += 1 if h & (1<<i) else -1
        return sum(1<<i for i in range(64) if v[i]>0)

    @staticmethod
    def hamming(a: int, b: int) -> int:
        return bin(a^b).count('1')

SIMHASH_TEXT_EXTS = {
    '.txt', '.md', '.py', '.js', '.ts', '.c', '.cpp', '.h', '.java', '.go', '.rs',
    '.rb', '.sql', '.sh', '.bat', '.ps1', '.yaml', '.yml', '.json', '.toml',
    '.ini', '.html', '.css', '.xml', '.csv', '.rst', '.tex', '.log', '.vue',
    '.jsx', '.tsx', '.cfg', '.conf', '.env',
}

def dedup_files(files: List[FileInfo]) -> Tuple[List[FileInfo], list]:
    """三层去重: 同名同大小MD5 + 同名 + 文本内容相似度"""
    import difflib
    before_count = len(files)
    removed = set()
    dedup_log = []
    hash_map = defaultdict(list)
    name_size_groups = defaultdict(list)
    for i, f in enumerate(files):
        key = (f.name.lower().strip(), f.size)
        name_size_groups[key].append(i)
    md5_computed = 0
    for key, idxs in name_size_groups.items():
        if len(idxs) <= 1:
            continue
        for i in idxs:
            if not files[i].md5:
                files[i].md5 = file_md5(files[i].path)
                md5_computed += 1
    for i, f in enumerate(files):
        if f.md5:
            hash_map[f.md5].append(i)
    for md5_val, idxs in hash_map.items():
        if len(idxs) <= 1:
            continue
        best = min(idxs, key=lambda i: len(files[i].path))
        for i in idxs:
            if i != best:
                removed.add(i)
                dedup_log.append((files[best].path, files[i].path, 'MD5相同'))
    # 同名去重
    name_groups = defaultdict(list)
    for i, f in enumerate(files):
        if i not in removed:
            name_groups[f.name.lower().strip()].append(i)
    for name, idxs in name_groups.items():
        if len(idxs) <= 1:
            continue
        best = min(idxs, key=lambda i: len(files[i].path))
        for i in idxs:
            if i != best and i not in removed:
                removed.add(i)
                dedup_log.append((files[best].path, files[i].path, '同名文件'))
    # SimHash 近似去重 (文本文件 <500KB)
    simhash_removed = 0
    remaining = [f for i, f in enumerate(files) if i not in removed]
    text_candidates = [(i, f) for i, f in enumerate(remaining)
                       if f.ext.lower() in SIMHASH_TEXT_EXTS and f.size < 500*1024]
    if text_candidates:
        print(f"  SimHash 去重: {len(text_candidates):,} 个文本文件...")
        sh_map = []  # (index, hash)
        for idx, f in text_candidates:
            try:
                with open(f.path, 'r', encoding='utf-8', errors='ignore') as fh:
                    text = fh.read(16384)
                if len(text) > 100:
                    sh_map.append((idx, SimHash.compute(text), f))
            except:
                pass
        sh_map.sort(key=lambda x: x[2].size)
        simhash_idx_removed = set()
        for a in range(len(sh_map)):
            if a in simhash_idx_removed:
                continue
            idx_a, hash_a, fa = sh_map[a]
            for b in range(a+1, min(a+200, len(sh_map))):
                if b in simhash_idx_removed:
                    continue
                idx_b, hash_b, fb = sh_map[b]
                if abs(fa.size - fb.size) / max(fa.size, 1) > 0.15:
                    continue
                hd = SimHash.hamming(hash_a, hash_b)
                if hd == 0:
                    simhash_idx_removed.add(b)
                    dedup_log.append((fa.path, fb.path, f'SimHash完全相同(h=0)'))
                elif hd <= 3:
                    simhash_idx_removed.add(b)
                    dedup_log.append((fa.path, fb.path, f'SimHash高度相似(h={hd})'))
        if simhash_idx_removed:
            # 标记被 SimHash 去除的文件
            for idx in sorted(simhash_idx_removed, reverse=True):
                removed.add(files.index(remaining[idx]))
            simhash_removed = len(simhash_idx_removed)
            print(f"  SimHash 去除: {simhash_removed:,} 个近似重复")

    result = [f for i, f in enumerate(files) if i not in removed]
    print(f"  去重完成: {before_count:,} -> {len(result):,} (去除 {len(removed):,} 个重复)")
    return result, dedup_log


def resolve_dest_dir(f: FileInfo) -> str:
    """根据文件标签+名称特征，返回目标子目录路径"""
    type_dir = TYPE_TO_DIR.get(f.tags.doc_type, '06_待确认')
    # 对所有类型都尝试源文件夹提示
    folder_hint = get_source_folder_hint(f.path)
    if folder_hint:
        # 在类型目录下加源文件夹子目录
        type_dir = f"{type_dir}/{folder_hint}"
    if f.tags.doc_type == '文档':
        sub = resolve_doc_subdir(f.path, f.name)
        if sub:
            type_dir = sub
    elif f.tags.doc_type == '数据':
        sub = resolve_doc_subdir(f.path, f.name)
        if sub:
            type_dir = sub.replace('02_文档/', '02_文档/数据_')
    elif f.tags.doc_type in ('图片', '视频', '音频'):
        sub = get_media_subdir(f.path, f.name)
        if sub:
            type_dir = sub
    elif f.tags.doc_type == '设计':
        # CAD/3D文件按品牌子目录
        if folder_hint:
            type_dir = f"09_设计/{folder_hint}"
    return type_dir


def _build_file_groups(files: List[FileInfo]) -> dict:
    """将同目录下的 .json+.md 配对、知识图谱.md 归入文件夹组。
    返回 {file_index: group_name} 映射，不在组里的文件不出现。"""
    from collections import defaultdict
    dir_groups = defaultdict(list)  # dir_path -> [(index, FileInfo)]
    for i, f in enumerate(files):
        dir_groups[os.path.dirname(f.path)].append((i, f))

    groups = {}  # index -> group_name
    KG_PATTERNS = ("knowledge_point", "knowledge_graph", "知识点", "知识图谱")

    for dir_path, items in dir_groups.items():
        indices = [idx for idx, _ in items]
        names = {idx: fi.name.lower() for idx, fi in items}
        exts = {idx: fi.ext.lower() for idx, fi in items}
        folder_base = Path(dir_path).name
        parent_name = Path(dir_path).parent.name
        group_label = f"{parent_name}_{folder_base}" if parent_name else folder_base

        # 条件1: 同目录有 2+ 个 .md → 知识文档文件夹（整体迁移）
        md_indices = [idx for idx in indices if exts[idx] == ".md"]
        if len(md_indices) >= 2:
            for idx in md_indices:
                groups[idx] = group_label

        # 条件2: 检测知识图谱生成的 .md
        kg_mds = [idx for idx in indices
                  if exts[idx] == ".md" and any(p in names[idx] for p in KG_PATTERNS)]
        if len(kg_mds) >= 1:
            folder = "知识图谱文档集合"
            for idx in kg_mds:
                groups[idx] = folder

        # 条件3: 同目录有 JSON + MD → 整个目录打包为项目文件夹
        json_files = [idx for idx in indices if exts[idx] == ".json"]
        md_files = [idx for idx in indices if exts[idx] == ".md"]
        if json_files and md_files:
            for idx in indices:
                if idx not in groups:
                    groups[idx] = group_label

    if groups:
        print(f"  文件夹分组: {len(groups):,} 个文件组成项目文件夹")
    return groups


def copy_files(files: List[FileInfo], output_root: Path, dry_run: bool) -> List[FileInfo]:
    """复制文件到整理目录，支持文件夹分组，带进度条"""
    # 构建分组
    file_groups = _build_file_groups(files)
    total = len(files)
    total_bytes = sum(f.size for f in files)
    copied_bytes = 0
    errors = 0
    start_time = time.time()
    for i, f in enumerate(files, 1):
        type_dir = resolve_dest_dir(f)
        priority_dir = {'高':'高优先级', '中':'中优先级', '低':'低优先级'}.get(f.tags.priority, '待评估')
        base_dir = output_root / type_dir / priority_dir

        # 如果属于某个组，放到组文件夹里
        if (i - 1) in file_groups:
            group_name = file_groups[i - 1]
            group_dir = base_dir / group_name
            group_dir.mkdir(parents=True, exist_ok=True)
            dest_file = group_dir / f.name
            # 备注来源和创建时间到 _source.txt
            note_file = group_dir / "_来源信息.txt"
            if not note_file.exists() and not dry_run:
                try:
                    ctime = datetime.fromtimestamp(os.path.getctime(f.path)).strftime('%Y-%m-%d %H:%M')
                    with open(note_file, 'w', encoding='utf-8') as nf:
                        nf.write(f"文件夹: {group_name}\n")
                        nf.write(f"来源目录: {os.path.dirname(f.path)}\n")
                        nf.write(f"创建时间: {ctime}\n")
                        nf.write(f"迁移时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
                except:
                    pass
        else:
            base_dir.mkdir(parents=True, exist_ok=True)
            dest_file = base_dir / f.name

        if dest_file.exists():
            stem = dest_file.stem
            suffix = dest_file.suffix
            dest_file = dest_file.parent / f"{stem}_dup{i}{suffix}"
        f.dest = str(dest_file)
        if not dry_run:
            try:
                shutil.copy2(f.path, dest_file)
                copied_bytes += f.size
            except Exception as e:
                f.dest = f"ERROR: {e}"
                errors += 1
        else:
            copied_bytes += f.size
        if i % 50 == 0 or i == total or f.size > 50 * 1024 * 1024:
            elapsed = time.time() - start_time
            pct = i / total * 100
            speed = copied_bytes / elapsed if elapsed > 0 else 0
            eta = (total_bytes - copied_bytes) / speed if speed > 0 else 0
            bar_len = int(pct / 100 * 30)
            bar = '\u2588' * bar_len + '\u2591' * (30 - bar_len)
            print(f"\r  {bar} {pct:5.1f}%  {i}/{total}  {format_size(copied_bytes)}/{format_size(total_bytes)}  "
                  f"速度:{format_size(int(speed))}/s  ETA:{int(eta)}s", end='', flush=True)
    print()
    if errors:
        print(f"  完成: {total-errors}/{total} 成功, {errors} 失败")
    else:
        mode = "预览" if dry_run else "拷贝"
        print(f"  {mode}完成: {total:,} 个文件, {format_size(copied_bytes)}")
    return files


def generate_reports(files: List[FileInfo], output_root: Path, dedup_log: list) -> Tuple[str, str, str]:
    """生成 CSV/JSON/HTML 报告"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    csv_path = output_root / f"文件整理_扫描报告_{timestamp}.csv"
    json_path = output_root / f"文件整理_扫描报告_{timestamp}.json"
    html_path = output_root / f"文件整理_扫描报告_{timestamp}.html"
    # CSV
    try:
        with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['文件名', '扩展名', '大小', '修改时间', '主题', '类型', '领域', '优先级', '时效', '来源', '原路径', '目标路径'])
            for fi in files:
                writer.writerow([fi.name, fi.ext, format_size(fi.size), fi.mtime,
                                 fi.tags.topic, fi.tags.doc_type, fi.tags.domain,
                                 fi.tags.priority, fi.tags.time_tag, fi.tags.source,
                                 fi.path, fi.dest])
    except Exception as e:
        print(f"  CSV报告失败: {e}")
        csv_path = None
    # JSON
    try:
        report = {
            'scan_time': datetime.now().isoformat(),
            'total_files': len(files),
            'total_size': sum(f.size for f in files),
            'dedup_count': len(dedup_log),
            'files': [asdict(f) for f in files],
            'dedup_log': dedup_log,
        }
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  JSON报告失败: {e}")
        json_path = None
    # HTML
    try:
        html_content = _generate_html_report(files, output_root, dedup_log)
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
    except Exception as e:
        print(f"  HTML报告失败: {e}")
        html_path = None
    print(f"  报告生成: {csv_path}")
    return str(csv_path or ''), str(json_path or ''), str(html_path or '')


def _generate_html_report(files: List[FileInfo], output_root: Path, dedup_log: list) -> str:
    """生成HTML报告"""
    topic_c = Counter(f.tags.topic for f in files)
    type_c = Counter(f.tags.doc_type for f in files)
    prio_c = Counter(f.tags.priority for f in files)
    domain_c = Counter(f.tags.domain for f in files)
    total_size = sum(f.size for f in files)
    rows = []
    for f in files:
        rows.append(f'<tr><td>{f.name}</td><td>{f.ext}</td><td>{format_size(f.size)}</td>'
                    f'<td>{f.tags.topic}</td><td>{f.tags.doc_type}</td><td>{f.tags.domain}</td>'
                    f'<td>{f.tags.priority}</td><td>{f.tags.source}</td></tr>')
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>文件迁移报告</title>
<style>body{{font-family:sans-serif;margin:20px}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:8px;text-align:left}}th{{background:#4CAF50;color:white}}.chart{{margin:20px 0}}.bar{{height:20px;background:#4CAF50;display:inline-block}}</style>
</head><body>
<h1>文件迁移报告</h1>
<p>扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 文件数: {len(files):,} | 总大小: {format_size(total_size)}</p>
<div class="chart"><h3>按主题</h3>{''.join(f'<p>{k}: {v} <span class="bar" style="width:{v/max(len(files),1)*200}px"></span></p>' for k,v in topic_c.items())}</div>
<div class="chart"><h3>按类型</h3>{''.join(f'<p>{k}: {v} <span class="bar" style="width:{v/max(len(files),1)*200}px"></span></p>' for k,v in type_c.items())}</div>
<div class="chart"><h3>按优先级</h3>{''.join(f'<p>{k}: {v} <span class="bar" style="width:{v/max(len(files),1)*200}px"></span></p>' for k,v in prio_c.items())}</div>
<div class="chart"><h3>按领域</h3>{''.join(f'<p>{k}: {v} <span class="bar" style="width:{v/max(len(files),1)*200}px"></span></p>' for k,v in domain_c.items())}</div>
<h2>文件列表</h2>
<table><tr><th>文件名</th><th>扩展名</th><th>大小</th><th>主题</th><th>类型</th><th>领域</th><th>优先级</th><th>来源</th></tr>
{''.join(rows)}</table>
</body></html>"""


# ============================================================
#  主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="文件迁移工具 v3.1 - 6维RAG打标 + 品牌/应用智能分类")
    parser.add_argument("--dry-run", action="store_true", help="只预览不拷贝")
    parser.add_argument("--ai", action="store_true", help="启用AI深度感知 (需要DEEPSEEK_API_KEY)")
    parser.add_argument("--auto-discover", action="store_true", help="启用AI品牌/应用自动发现")
    parser.add_argument("--max-size", type=str, default="10GB", help="最大文件大小 (如 5GB, 500MB)")
    parser.add_argument("--limit", type=int, default=0, help="限制处理文件数 (测试用)")
    parser.add_argument("--target", type=str, default="", help="目标磁盘路径 (如 E:\\\\ 或 auto)")
    parser.add_argument("--output", type=str, default="", help="自定义输出目录")
    parser.add_argument("--no-open", action="store_true", help="不自动打开输出目录")
    args = parser.parse_args()

    # 解析 max_size
    max_size_str = args.max_size.upper()
    if "GB" in max_size_str:
        max_size = int(float(max_size_str.replace("GB", "")) * 1024 * 1024 * 1024)
    elif "MB" in max_size_str:
        max_size = int(float(max_size_str.replace("MB", "")) * 1024 * 1024)
    else:
        max_size = DEFAULT_MAX_SIZE

    dry_run = args.dry_run

    print()
    print("=" * 64)
    print("  文件迁移工具 v3.1 - 6维RAG打标 + 品牌/应用智能分类")
    print("=" * 64)
    print()
    print(f"  模式: {'预览 (不拷贝)' if dry_run else '扫描 + 拷贝'}")
    print(f"  最大文件: {args.max_size}")
    if args.limit:
        print(f"  限制: 前 {args.limit} 个文件")

    # 目标选择
    target_drive = None
    output_root = None
    if args.target:
        if args.target.lower() == "auto":
            print("  自动检测移动硬盘...")
            drives = detect_removable_drives()
            target_drive = choose_target_drive(drives)
        else:
            target_path = Path(args.target)
            if target_path.exists():
                target_drive = target_path
                print(f"  目标: {target_drive}")
            else:
                print(f"  指定路径不存在: {args.target}")
                print("  检测可用磁盘...")
                drives = detect_removable_drives()
                target_drive = choose_target_drive(drives)
    elif args.output:
        output_root = Path(args.output)
    else:
        # 默认行为：自动选空闲最大的分区
        print("  自动选择最大分区...")
        drives = detect_removable_drives()
        if drives:
            best = max(drives, key=lambda d: d["free_gb"])
            target_drive = Path(best["path"])
            print(f"  自动选择: {best['letter']}\\\\ (空闲 {best['free_gb']:.0f} GB)")
        else:
            target_drive = None

    if target_drive:
        output_root = target_drive / "文件迁移整理"
        free_gb = shutil.disk_usage(str(target_drive)).free / (1024**3)
        print(f"  目标: {output_root} (空闲 {free_gb:.0f} GB)")
    else:
        output_root = Path(args.output) if args.output else OUTPUT_ROOT
        print(f"  目标: {output_root}")

    print()

    # 创建目录
    output_root.mkdir(parents=True, exist_ok=True)

    # 1. 扫描
    print("[1/5] 扫描文件...")
    if args.ai:
        if DEEPSEEK_API_KEY:
            print("  AI 深度感知: 已启用 (DeepSeek)")
        else:
            print("  警告: --ai 需要设置 DEEPSEEK_API_KEY 环境变量, 已跳过 AI 分析")
    files = scan_files(SCAN_PATHS, max_size, use_ai=args.ai and bool(DEEPSEEK_API_KEY))

    # 1.5 去重
    print()
    print("[1.5/5] 三层去重...")
    files, dedup_log = dedup_files(files)
    if args.limit and len(files) > args.limit:
        print(f"  --limit {args.limit}: 截取前 {args.limit} 个文件测试")
        files = files[:args.limit]
    if not files:
        print("  未找到有效文件.")
        return

    # 1.8 AI品牌/应用自动发现
    if args.auto_discover and DEEPSEEK_API_KEY:
        print()
        print("[1.8/5] AI品牌/应用自动发现...")
        discovered = ai_discover_brands(files)
        if discovered:
            print(f"  发现 {discovered} 个新品牌/应用")
        else:
            print("  未发现新品牌/应用")

    # 2. 统计
    print()
    print("[2/5] 统计分析...")
    topic_c = Counter(f.tags.topic for f in files)
    prio_c  = Counter(f.tags.priority for f in files)
    total_sz = sum(f.size for f in files)

    # 空间检查
    if target_drive:
        free_bytes = shutil.disk_usage(str(target_drive)).free
        if total_sz > free_bytes:
            print(f"  警告: 文件总大小 {format_size(total_sz)} 超过目标磁盘空闲 {format_size(free_bytes)}!")
            print(f"  建议: 用 --max-size 限制，或选择更大的磁盘")
            confirm = input("  是否继续? (y/N): ").strip().lower()
            if confirm not in ("y", "yes"):
                print("  已取消.")
                return
        else:
            print(f"  空间充足: 需要 {format_size(total_sz)}, 空闲 {format_size(free_bytes)}")

    print(f"  有效文件: {len(files):,} | 总大小: {format_size(total_sz)}")
    print()
    print("  +-- 按主题 ---------------------------------+")
    for k in ["技术","工作","学习","个人","其他"]:
        v = topic_c.get(k, 0)
        bar = "\u2588" * min(int(v / max(len(files),1) * 40), 40)
        print(f"  | {k:4} {v:6} {bar}")
    print("  +-------------------------------------------+")
    print()
    print("  +-- 按优先级 -------------------------------+")
    for k in ["高","中","低"]:
        v = prio_c.get(k, 0)
        bar = "\u2588" * min(int(v / max(len(files),1) * 40), 40)
        print(f"  | {k:4} {v:6} {bar}")
    print("  +-------------------------------------------+")
    print()

    # 3. 预览目录树
    print("[3/5] 目标目录结构预览:")
    print()
    file_groups = _build_file_groups(files)
    tree = {}
    grouped_display = {}  # key -> {group_name: [files]}
    for fi, f in enumerate(files):
        type_dir = resolve_dest_dir(f)
        priority_dir = {"高":"高优先级", "中":"中优先级", "低":"低优先级"}.get(f.tags.priority, "待评估")
        key = f"{type_dir}/{priority_dir}"
        if key not in tree:
            tree[key] = {"count": 0, "size": 0, "files": [], "ungrouped": [], "groups": {}}
        tree[key]["count"] += 1
        tree[key]["size"] += f.size
        tree[key]["files"].append(f)
        if fi in file_groups:
            gname = file_groups[fi]
            if gname not in tree[key]["groups"]:
                tree[key]["groups"][gname] = {"count": 0, "size": 0}
            tree[key]["groups"][gname]["count"] += 1
            tree[key]["groups"][gname]["size"] += f.size
        else:
            tree[key]["ungrouped"].append(f)

    sorted_keys = sorted(tree.keys())
    for key in sorted_keys:
        info = tree[key]
        print(f"  {key}/")
        print(f"    {info['count']} 个文件, {format_size(info['size'])}")
        # 显示文件夹组
        for gname, ginfo in info["groups"].items():
            print(f"      [{gname}/]  ({ginfo['count']} 个文件, {format_size(ginfo['size'])})")
        # 显示非组文件
        for fi in info["ungrouped"][:5]:
            print(f"      {fi.name}  ({format_size(fi.size)})")
        remaining = len(info["ungrouped"]) - 5
        if remaining > 0:
            print(f"      ... 还有 {remaining} 个文件")
        print()

    print(f"  合计: {len(files):,} 个文件, {format_size(total_sz)}")
    print()

    if dry_run:
        # dry-run 模式
        print("[4/5] 生成报告...")
        csv_p, json_p, html_p = generate_reports(files, output_root, dedup_log)
        print()
        print("=" * 64)
        print("  预览完成 (未拷贝)")
        print("=" * 64)
        print(f"  输出目录:  {output_root}")
        print(f"  CSV报告:   {csv_p}")
        print(f"  JSON报告:  {json_p}")
        print(f"  HTML报告:  {html_p}")
        print()
        print("  提示: 去掉 --dry-run 参数运行会实际拷贝文件")
        if not args.no_open:
            import subprocess
            subprocess.Popen(["explorer", str(output_root)])
            if html_p:
                subprocess.Popen(["cmd", "/c", "start", "", str(html_p)])
        return

    # 非 dry-run: 确认后拷贝
    print("  +---------------------------------------------+")
    print("  |  确认将以上文件拷贝到上述目录结构?            |")
    print("  |  [Y] 确认拷贝  [N] 取消  [C] 逐目录确认      |")
    print("  +---------------------------------------------+")
    choice = input("  请选择 (Y/N/C, 回车=Y): ").strip().lower() or "y"

    if choice == "n":
        print("  已取消.")
        return

    if choice == "c":
        confirmed_files = []
        for key in sorted_keys:
            info = tree[key]
            print(f"\n  {key}/ ({info['count']} 个, {format_size(info['size'])})")
            for fi in info["files"][:10]:
                print(f"    {fi.name}  ({format_size(fi.size)})")
            if info["count"] > 10:
                print(f"    ... 还有 {info['count'] - 10} 个")
            ans = input(f"  拷贝此目录? (Y/n, 回车=Y): ").strip().lower() or "y"
            if ans != "n":
                confirmed_files.extend(info["files"])
            else:
                print(f"    跳过 {key}")
        files = confirmed_files
        if not files:
            print("  没有选择任何文件，已取消.")
            return

    print(f"\n[4/5] 拷贝 {len(files):,} 个文件到 {output_root}...")
    files = copy_files(files, output_root, dry_run=False)

    # 5. 报告
    print()
    print("[5/5] 生成报告...")
    csv_p, json_p, html_p = generate_reports(files, output_root, dedup_log)

    print()
    print("=" * 64)
    print("  整理完成!")
    print("=" * 64)
    print()
    print(f"  输出目录:  {output_root}")
    print(f"  CSV报告:   {csv_p}")
    print(f"  JSON报告:  {json_p}")
    print(f"  HTML报告:  {html_p}")
    print()
    if target_drive:
        print(f"  文件已整理到移动硬盘 {target_drive}")
        print(f"     直接拔下硬盘插到新电脑即可")
    print("  提示: 用浏览器打开 HTML 报告查看可视化统计")
    print()

    # 自动打开输出目录和 HTML 报告
    if not args.no_open:
        import subprocess
        print("  正在打开输出目录...")
        subprocess.Popen(["explorer", str(output_root)])
        if html_p:
            subprocess.Popen(["cmd", "/c", "start", "", str(html_p)])
    if dry_run:
        print("  提示: 去掉 --dry-run 参数运行会实际复制文件")
    else:
        print("  提示: 原文件未被移动，仅复制到整理目录")


if __name__ == "__main__":
    main()
