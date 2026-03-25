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

### 常用参数
- `--query`: arXiv 搜索查询（例如 `cat:cs.RO AND (dexterous OR tactile)`）
- `--keywords`: 逗号分隔关键词（对 title/abstract 做包含过滤）
- `--sources`: `arxiv`、`hf` 或 `arxiv,hf`
- `--db`: SQLite 路径（默认 `out/lit_radar.sqlite3`）
- `--out`: 输出目录（默认 `out`）

### 输出
- `out/papers.json`: 结构化结果
- `out/digest.md`: 今日摘要（可用于后续推送）

