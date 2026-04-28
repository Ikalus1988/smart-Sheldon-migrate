# 文件迁移工具 v3.2

6维RAG打标 + 工业智能分类 + 四层去重

将旧电脑上的有价值文件自动扫描、分类打标、去重后，整理到移动硬盘，即插即用于新电脑。

## 快速开始

```bash
# 1. 预览（推荐先试，不拷贝文件）
python organize_files.py --dry-run

# 2. 实际迁移（插移动硬盘后运行）
python organize_files.py

# 3. 带AI深度感知（需要 DEEPSEEK_API_KEY 环境变量）
python organize_files.py --ai
```

## 核心功能

### 智能分类（6维RAG打标）

| 维度 | 说明 | 示例值 |
|------|------|--------|
| topic | 主题 | 技术/工作/学习/个人/其他 |
| doc_type | 文件类型 | 文档/代码/数据/设计/工业程序/图片/视频/音频/压缩包... |
| domain | 专业领域 | 机器人/电气/视觉/焊接/机械设计/开发... |
| priority | 优先级 | 高/中/低 |
| time_tag | 时效性 | 长期有效/短期/不确定 |
| source | 来源 | 个人创作/下载资料/项目产出/系统生成... |

### 四层去重

1. 文件名+大小+MD5 精确去重
2. 同名文件去重（保留路径最短的）
3. SimHash文本相似度去重（h=0 完全相同自动删，h≤3 高度相似删）
4. SimHash检测结果生成报告备查

### 品牌/应用自动识别

内置 **40+ 工业品牌词库**：FANUC、KUKA、ABB、Siemens、EPLAN、SolidWorks、AutoCAD、Omron、Beckhoff 等。
从文件路径自动匹配品牌和项目归属。

### 目录结构

迁移目标目录按类型和优先级组织：

```
文件迁移整理/
├── 01_代码/高优先级/
├── 02_文档/技术手册/
├── 03_数据/
├── 04_配置/
├── 05_报告/
├── 06_待确认/
├── 07_媒体/图片/
├── 08_压缩包/
├── 09_设计/SolidWorks/
├── 10_字体/
├── 11_工业程序/机器人/
├── 12_CAD支持/
└── 文件整理_扫描报告_*.html  (可视化报告)
```

### 文件夹分组迁移

同目录下2个+ .md 文件 → 自动归为「知识文档文件夹」整体迁移
JSON+MD 混合目录 → 打包为项目文件夹
保留 \_来源信息.txt 记录原始位置

## 用法

```
python organize_files.py [参数]

参数:
  --dry-run         只预览不拷贝
  --ai              启用AI深度感知（DeepSeek API）
  --auto-discover   启用AI品牌自动发现
  --max-size 10GB   最大文件大小
  --limit N         仅处理前N个文件（测试用）
  --target E:\      指定目标磁盘
  --output ./out    指定输出目录
  --no-open         不自动打开报告
```

### 环境变量

```
DEEPSEEK_API_KEY=sk-xxx     AI分析用（可选）
USERPROFILE=C:\Users\hp     用户目录
```

## 快速管线（批量扫描用）

```bash
# 已有find结果时用快速管线
python process_pipeline.py
```
处理 find 扫描结果 → 打标 → 知识图谱 → SimHash 去重报告

## 系统要求

- Python 3.8+
- Windows（推荐）或 WSL
- 移动硬盘（目标盘）
- 可选：DeepSeek API Key（用于AI深度分析）

## 文件清单

| 文件 | 说明 |
|------|------|
| organize_files.py | 主工具（扫描→打标→去重→拷贝→报告） |
| process_pipeline.py | 快速管线（从find结果直接处理） |
| build_knowledge_graph.py | 知识图谱构建 |
| simhash_dedup.py | SimHash文本去重 |
| gen_dashboard.py | 可视化看板生成 |
| scan_wsl.py | WSL扫描辅助 |

## 版本历史

见 CHANGELOG.md
