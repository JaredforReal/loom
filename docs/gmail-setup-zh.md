# Gmail 配置指南

本指南帮助你把 Loom 的 Gmail adaptor 接到自己的 Gmail 账号。配置完成后，Loom 会轮询你的收件箱，把新邮件投递到 Mailbox 等待审阅。

## 前置条件

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/)
- 一个 Gmail 账号
- macOS 或 Linux（Windows 用户请把 `~` 替换成 `%USERPROFILE%`）

## 第 1 步 — 创建 Google Cloud 项目

1. 打开 [Google Cloud Console](https://console.cloud.google.com/)。
2. 顶栏点击项目选择器 → **新建项目**。
3. 起个名字，比如 `loom-gmail-dev`，创建。
4. 继续之前确保新项目处于选中状态。

## 第 2 步 — 启用 Gmail API

1. 进入 **APIs & Services → Library**（API 和服务 → 库）。
2. 搜索 **Gmail API** 并点击。
3. 点击 **Enable**（启用）。

## 第 3 步 — 配置 OAuth 同意屏幕

1. 进入 **APIs & Services → OAuth consent screen**（OAuth 同意屏幕）。
2. 选择 **External**（外部）→ **Create**（创建）。
3. 填写必填字段：
   - **应用名称**：`Loom`
   - **用户支持邮箱**：你的邮箱
   - **开发者联系邮箱**：你的邮箱
4. 点 **Save and Continue** 进入 **Scopes**（权限范围）页。
5. 点 **Add or Remove Scopes**，添加：
   ```
   https://www.googleapis.com/auth/gmail.modify
   ```
6. 点 **Save and Continue** 进入 **Test users**（测试用户）页。
7. 添加你自己的 Gmail 地址。（External + Testing 模式下，只有列在 Test users 里的账号才能授权。）
8. 保存完成。

## 第 4 步 — 创建 OAuth 客户端凭据

1. 进入 **APIs & Services → Credentials**（凭据）。
2. 点击 **Create Credentials → OAuth client ID**。
3. **Application type**（应用类型）：选 **Desktop app**（桌面应用）。
4. 起个名字（如 `loom-desktop`），创建。
5. 在生成的客户端上点 **Download JSON** 下载凭据文件。

## 第 5 步 — 放置凭据文件

```bash
mkdir -p ~/.loom/credentials
mv ~/Downloads/client_secret_*.json ~/.loom/credentials/gmail-client-secrets.json
```

上面这个路径只是**推荐**的位置和命名，并非强制。`GmailAdaptor` 通过 `client_secrets_path` 参数显式接受凭据文件路径 —— 如果你放到别处，记得在启动 harness/CLI 时把对应路径传给 adaptor。

## 第 6 步 — 安装 gmail extra

在仓库根目录执行：

```bash
uv sync --extra gmail
```

这会装上 `google-api-python-client`、`google-auth-oauthlib` 等依赖。

## 第 7 步 — 首次运行（浏览器 OAuth 授权）

启动 adaptor（通过你的 harness 或 smoke 脚本）。首次运行时：

1. 浏览器自动弹出。
2. 选择你在 Test users 里加过的 Google 账号。
3. 会出现 **"Google hasn't verified this app"**（Google 尚未验证此应用）的警告。点 **Advanced（高级）→ Go to Loom (unsafe)**。这是正常的 —— 因为应用还在 Testing 模式，而你就是开发者。
4. 同意 `gmail.modify` 权限。
5. 浏览器显示 "The authentication flow has completed."

此时会自动生成：

```
~/.loom/credentials/gmail-token.json
```

文件里存了 access token + refresh token。Loom 会自动刷新，你不需要再走第 7 步 —— 除非 token 被吊销。

## 文件布局参考

配置完成后，`~/.loom/credentials/` 下会有：

| 文件 | 来源 | 用途 |
|---|---|---|
| `gmail-client-secrets.json` | 你提供（第 4 步下载） | OAuth 客户端身份 |
| `gmail-token.json` | 首次运行自动生成 | Access + refresh token |
| `gmail-state.json` | adaptor 自动维护 | 已处理过的 message id（去重，最多 1000 条） |

这三个文件都不在仓库里，**不要 commit**。

## 常见问题

**"Access blocked: ... has not completed the Google verification process"**
你没在 Test users 列表里。回到 **OAuth consent screen → Test users** 把你的 Gmail 加进去。

**`invalid_grant` 或 "Token has been expired or revoked"**
删掉 token 重跑：
```bash
rm ~/.loom/credentials/gmail-token.json
```
下次运行会重新弹出 OAuth 窗口。

**等了几分钟没收到邮件**
- 默认查询条件是 `is:unread -in:chats newer_than:1d`。从另一个账号给自己发一封，确保是未读状态。
- 确认你授权的 Gmail 账号就是接收测试邮件的账号。
- Loom 默认每 30 秒轮询一次，等一个完整周期。

**想完全重置**
删掉整个凭据目录，重新走第 4–7 步：
```bash
rm ~/.loom/credentials/gmail-client-secrets.json
rm ~/.loom/credentials/gmail-token.json
rm ~/.loom/credentials/gmail-state.json
```
