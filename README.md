## lit-radar

一个可扩展的“文献雷达”：抓取 arXiv + Hugging Face Papers，按关键词/分类过滤，SQLite 去重，输出 Markdown/JSON。

### 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 运行（抓取最近 24 小时）

```bash
python3 -m lit_radar --window-hours 24 --sources arxiv,hf --out out
```

### 使用配置文件（避免长命令）

```bash
python3 -m lit_radar --config configs/dexterous_hand.json
```

### 常用参数
- `--config`: JSON 配置文件路径（配置文件会提供默认值；命令行同名参数会覆盖配置）
- `--query`: arXiv 搜索查询（例如 `cat:cs.RO AND (dexterous OR tactile)`）
- `--keywords`: 逗号分隔关键词（对 title/abstract 做包含过滤）
- `--sources`: `arxiv`、`hf` 或 `arxiv,hf`
- `--profile`: 相关性打分配置（`general` 或 `dexterous_hand`）
- `--min-score`: 最低相关性阈值（搭配 `--profile` 使用）
- `--include-seen`: 也输出数据库里已存在的论文（适合做日报/周报复跑）
- `--timeout-seconds`: HTTP 超时秒数（网络慢/偶发超时可调大）
- `--retries`: HTTP 重试次数（网络抖动可调大）
- `--db`: SQLite 路径（默认 `out/lit_radar.sqlite3`）
- `--out`: 输出目录（默认 `out`）

### 输出
- `out/papers.json`: 结构化结果
- `out/digest.md`: 今日摘要（可用于后续推送）

### 示例：抓“灵巧手操作”相关论文（更聚焦）

```bash
python3 -m lit_radar \
  --window-hours 72 \
  --sources arxiv,hf \
  --profile dexterous_hand \
  --min-score 5 \
  --query "cat:cs.RO AND (dexterous OR \"in-hand\" OR \"robotic hand\" OR multifinger OR tactile OR grasp OR manipulation)" \
  --out out
```

等价的配置文件方式：

```bash
python3 -m lit_radar --config configs/dexterous_hand.json
```

### 自定义 profile（可选）

你可以在配置文件里新增/覆盖 `profiles`，用于调整词表与权重；不需要的词直接删掉即可。例如：

```json
{
  "profile": "dexterous_hand",
  "profiles": {
    "dexterous_hand": [
      { "term": "in-hand", "weight": 6.0 },
      { "term": "dexterous hand", "weight": 6.0 },
      { "term": "tactile", "weight": 4.0 }
    ]
  }
}
```

