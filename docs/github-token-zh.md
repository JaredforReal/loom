# 获取和配置 GitHub Token

## 创建 Token

1. 打开 GitHub → **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens**（推荐）或 **Tokens (classic)**

   直接访问: https://github.com/settings/tokens

2. 点击 **Generate new token**

3. 填写：

| 字段 | 值 |
|---|---|
| Token name | `loom` |
| Expiration | 按需选择（建议 90 天） |
| Repository access | **Only select repositories** → 选择你要监控的仓库 |
| Permissions → Issues | **Read and write**（读取 issue/PR + 发表评论/关闭/打标签） |
| Permissions → Pull requests | **Read and write**（同上） |

> 如果你用的是 **Classic token**，勾选 `repo` scope 即可覆盖所有需要。

4. 点击 **Generate token**，复制生成的 token（以 `github_pat_` 或 `ghp_` 开头）

## 配置 Token

### 方式一：环境变量（推荐）

```bash
# 写入 shell 配置文件（长期生效）
echo 'export GITHUB_TOKEN="ghp_xxxxxxxxxxxx"' >> ~/.zshrc
source ~/.zshrc

# 验证
echo $GITHUB_TOKEN
```

### 方式二：.env 文件

```bash
# 在项目根目录创建 .env
echo 'GITHUB_TOKEN=ghp_xxxxxxxxxxxx' >> .env
```

> 确保 `.env` 在 `.gitignore` 中，不要提交到版本控制。

## 验证 Token

```bash
curl -s -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/vllm-project/vllm/issues?per_page=1 \
  | head -5
```

如果返回 JSON 数据（而非 `401` 或 `message: "Bad credentials"`），说明 token 配置正确。

## Token 权限说明

| 操作 | 需要的权限 |
|---|---|
| 读取 issue/PR | Issues: Read, Pull requests: Read |
| 发表评论 | Issues: Read and write |
| 关闭 issue/PR | Issues: Read and write |
| 添加/删除标签 | Issues: Read and write |

如果你只需要监控不需要执行操作，**Read-only** 权限足够。

## 速率限制

GitHub API 对认证用户的限制为 **5000 次/小时**。Loom 使用 ETag 缓存和 `since` 参数减少请求量，典型使用场景（监控 1-5 个仓库，120 秒轮询间隔）每小时约消耗 150-300 次请求，远低于上限。

```bash
# 查看当前速率限制
curl -s -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/rate_limit | python3 -m json.tool
```
