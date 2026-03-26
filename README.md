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
- `--keywords`: 逗号分隔关键词（对 title/abstract 做包含过滤；至少命中其一）
- `--require-any-keywords`: 逗号分隔「硬门槛」：标题/摘要里**至少命中其一**才保留（适合只要五指灵巧手/人手等，过滤泛泛 manipulation）
- `--exclude-keywords`: 逗号分隔：标题/摘要里出现**任一**则丢弃
- `--sources`: `arxiv`、`hf` 或 `arxiv,hf`
- `--profile`: 相关性打分配置（`general` 或 `dexterous_hand`）
- `--min-score`: 最低相关性阈值（搭配 `--profile` 使用）
- `--include-seen` / `--no-include-seen`: 是否也输出库里已有的论文；**不传时以配置文件为准**（避免命令行默认 false 覆盖配置里的 `true`）
- `--translate-summary-zh` / `--no-translate-summary-zh`: 是否将 `digest.zh.md` 里的摘要翻译成中文（默认开启）
- `--timeout-seconds`: HTTP 超时秒数（网络慢/偶发超时可调大）
- `--retries`: HTTP 重试次数（网络抖动可调大）
- `--db`: SQLite 路径（默认 `out/lit_radar.sqlite3`）
- `--out`: 输出目录（默认 `out`）
- `--verbose` / `-v`：打印各过滤阶段数量（便于排查为何 `papers_out` 为 0）；也可在 JSON 里设 `"verbose": true`
- `--llm-config`: 本地 LLM 配置路径（例如 `configs/llm.local.json`，用于生成中文“系统总结”）

### 输出
- `out/papers.json`: 结构化结果
- `out/digest.md`: 今日摘要（英文字段标签 + 原文摘要）
- `out/digest.zh.md`: 今日摘要（中文字段标签 + 中文摘要；翻译失败自动回退原文）

### 可选：启用千问系统总结（仅本地）

1) 复制示例配置并填入你本地 key（不要提交）：

```bash
cp configs/llm.example.json configs/llm.local.json
```

2) 运行时传入：

```bash
python3 -m lit_radar --config configs/my_dexhand.json --llm-config configs/llm.local.json
```

启用后，`out/digest.zh.md` 每篇会多一个“系统总结”小节（问题/方法/结果/相关性）。  
`configs/*.local.json` 已在 `.gitignore` 忽略，避免误提交。
若配置里或命令行开启 `verbose`，终端还会打印每次请求与总计的 token 用量。

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

