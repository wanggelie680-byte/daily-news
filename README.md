# 每日热点自动聚合简报站

一个每天 07:00（北京时间）自动更新的中文新闻聚合网页，覆盖社会热点、时事政策、世界格局、世界经济四类主题。项目从免费 RSS 源抓取新闻，用 DeepSeek 生成中文摘要，并输出静态网页到 GitHub Pages。

## 本地运行

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python src\build_site.py
```

构建完成后打开 `docs\index.html` 即可预览。没有 `DEEPSEEK_API_KEY` 时自动使用免 key 降级摘要模式，页面仍可正常生成。

可选参数：

```text
--max-items 4       每类最多条数
--no-llm            强制使用降级摘要
--skip-details      跳过正文和图片提取，只使用 RSS 摘要
--date 2026-08-27   覆盖生成日期
```

## 配置 DeepSeek

1. 在 [DeepSeek 开放平台](https://platform.deepseek.com/) 注册并创建 API key。
2. 本地使用：复制 `.env.example` 为 `.env`，或直接设置环境变量 `DEEPSEEK_API_KEY`。
3. 云端使用：把 key 添加到 GitHub 仓库的 `Settings -> Secrets and variables -> Actions`，名称必须是 `DEEPSEEK_API_KEY`。

## 自动更新与部署

`.github/workflows/daily.yml` 会在每天 `0 0 * * *`（UTC，即北京时间 08:00）自动运行，也支持在 Actions 页面手动触发。工作流会抓取新闻、生成摘要、构建 `docs/` 静态站，并把 `docs/` 与 `data/digests/` 提交回仓库。

部署前需要：

1. 把代码推送到 GitHub 仓库。
2. 在仓库 `Settings -> Pages` 中，Source 选择 `Deploy from a branch`，Branch 选择你的默认分支（`main` 或 `master`）和 `/docs` 目录。
3. 在 Actions Secrets 中添加 `DEEPSEEK_API_KEY`。

## 一键发布到公网

1. 在 [github.com](https://github.com) 注册账号并新建一个 Public 仓库，例如 `daily-news`。
2. 在本项目目录执行下面三条命令，把代码推送到 GitHub：

```powershell
git branch -m main
git remote add origin https://github.com/你的用户名/daily-news.git
git push -u origin main
```

也可以直接运行一键发布脚本（只需填一次仓库地址）：

```powershell
.\deploy.ps1 https://github.com/你的用户名/daily-news.git
```

3. 打开仓库 `Settings -> Pages`，Source 选择 `Deploy from a branch`，Branch 选择 `main`、目录选择 `/docs`。
4. 在 `Settings -> Secrets and variables -> Actions` 添加 `DEEPSEEK_API_KEY`。
5. 等待几分钟，公网网址就是 `https://你的用户名.github.io/daily-news/`，其他电脑打开即可访问。

## 修改内容源

- `config/feeds.json`：RSS 源列表。默认使用中新网、人民网、新华网、IT之家、36氪等国内可达的 RSS；也可以按同样格式追加 BBC、Google News 等源，格式支持普通 RSS/Atom 和 Google News 关键词查询。
- `config/settings.json`：分类、每类条数、时效过滤、LLM 模型、历史保留天数。

每日结构化数据保存在 `data/digests/YYYY-MM-DD.json`，页面生成后自动保留最近 90 天并清理旧归档。
