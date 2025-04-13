# AstrBot Pixiv 搜索插件

[![文档](https://img.shields.io/badge/AstrBot-%E6%96%87%E6%A1%A3-blue)](https://astrbot.app)
[![pixiv-api](https://img.shields.io/pypi/v/pixiv-api.svg)](https://pypi.org/project/pixiv-api/)
[![aiohttp](https://img.shields.io/pypi/v/aiohttp.svg)](https://pypi.org/project/aiohttp/)

这是一个为 [AstrBot](https://astrbot.app) 开发的插件，允许用户通过 Pixiv 标签搜索插画。

## ✨ 功能特性

*   **标签搜索**: 使用命令 `/pixiv <标签1>,<标签2>,...` 来搜索相关 Pixiv 插画。
*   **图片发送**: 直接在聊天中发送搜索到的插画图片。
*   **R18 模式**: 可配置是否过滤 R18 内容、仅显示 R18 内容或不过滤。
*   **数量控制**: 可配置每次搜索返回的图片数量。
*   **安全配置**: 通过 AstrBot 插件配置系统安全管理 Pixiv API 凭据。
*   **代理支持**: 支持通过 HTTP/HTTPS 代理访问 Pixiv API。

## 🚀 开始使用

### 前提条件

*   Python >= 3.10
*   Git
*   已成功部署并运行的 AstrBot 实例 (v3.x 或更高版本) - 参考 [源码部署](https://astrbot.app/deploy/astrbot/cli.html) 或 [Docker 部署](https://astrbot.app/deploy/astrbot/docker.html)
*   一个有效的 Pixiv 账号，并已获取 `refresh_token` (推荐) 或知道用户名密码。获取 `refresh_token` 方法请参考 [pixiv-api 文档](https://pixiv-api.readthedocs.io/en/latest/authentication.html) 或其他网络教程。

### 安装插件

1.  进入你的 AstrBot 主目录。
2.  导航到插件目录，并将本插件仓库克隆下来：
    ```bash
    # 进入 AstrBot 根目录
    # cd /path/to/your/AstrBot
    mkdir -p data/plugins
    cd data/plugins
    git clone https://github.com/vmoranv/astrbot_plugin_pixiv_search.git
    ```
    *注意：建议将克隆下来的文件夹重命名为 `astrbot_plugin_pixiv_search` (或与 `metadata.yaml` 中 `name` 字段一致的名称)。*

3.  **检查/创建依赖文件**: 确保插件目录下 (`data/plugins/astrbot_plugin_pixiv_search/`) 存在 `requirements.txt` 文件，并包含以下内容：
    ```txt:requirements.txt
    # requirements.txt
    pixiv-api>=3.0.0 # 确保版本兼容
    aiohttp>=3.8.0   # 用于下载图片
    ```

4.  **重启或重载**:
    *   **首次安装**: 重启 AstrBot 以加载新插件及其依赖。
    *   **更新插件**: 在 AstrBot WebUI 的 `插件市场` -> `本地插件` 中找到该插件，点击 `管理` -> `重载插件`。AstrBot 会自动尝试安装 `requirements.txt` 中新增或更新的依赖。如果遇到 `ModuleNotFoundError`，请尝试重启 AstrBot。

### 配置 Pixiv 凭据与选项 (重要!)

为了让插件能够访问 Pixiv API 并按需工作，你需要进行配置。

1.  **通过 AstrBot WebUI 配置 (推荐)**:
    *   导航到 `插件市场` -> `本地插件`。
    *   找到 "Pixiv 搜索" 插件，点击 `管理` -> `配置`。
    *   在配置界面中填入以下信息：
        *   `pixiv_refresh_token`: (推荐) 你的 Pixiv Refresh Token。
        *   `pixiv_username`: (可选，如果不用 Token) 你的 Pixiv 用户名。
        *   `pixiv_password`: (可选，如果不用 Token) 你的 Pixiv 密码。
        *   `pixiv_proxy`: (可选) 你的 HTTP/HTTPS 代理地址，例如 `http://127.0.0.1:7890`。
        *   `r18_mode`: R18 内容过滤模式 (数字):
            *   `0`: 过滤 R18 内容 (默认)
            *   `1`: 仅显示 R18 内容
            *   `2`: 不过滤 R18 内容
        *   `return_count`: 每次搜索返回的图片数量 (数字，默认为 1)。
    *   点击 `保存`。

2.  **通过 `config.yaml` 文件配置 (备选)**:
    *   在你的 AstrBot 数据目录下，找到插件的配置目录：`data/plugins/astrbot_plugin_pixiv_search/`。
    *   在该目录下创建一个名为 `config.yaml` 的文件 (如果不存在)。
    *   将你的配置信息添加到 `config.yaml` 文件中，格式如下：

    ```yaml
    # data/plugins/astrbot_plugin_pixiv_search/config.yaml

    # --- 认证方式 (三选一或二) ---
    # 方式一：使用 Refresh Token (推荐)
    pixiv_refresh_token: "你的_refresh_token_粘贴在这里"

    # 方式二：使用用户名密码 (如果 Token 不可用)
    # pixiv_username: "你的Pixiv用户名"
    # pixiv_password: "你的Pixiv密码"

    # --- 可选配置 ---
    # 代理服务器地址 (如果需要)
    # pixiv_proxy: "http://your_proxy_server:port"

    # R18 过滤模式 (0=过滤R18, 1=仅R18, 2=不过滤)
    r18_mode: 0

    # 每次返回的图片数量
    return_count: 1
    ```
    *   保存文件。
    *   在 AstrBot WebUI 中重载该插件，使配置生效。

插件会优先使用 `refresh_token` 进行认证，如果未提供，则尝试使用用户名和密码。

### 使用方法

配置完成后，你可以在任何已接入 AstrBot 的聊天平台（QQ、Telegram、微信等）中使用以下命令：

```bash
/pixiv <标签1>,<标签2>,...
```

*   使用英文逗号 `,` 分隔多个标签。
*   标签可以是中文、英文或日文。

例如：

```
/pixiv 初音ミク,VOCALOID
/pixiv scenery,beautiful
```

机器人将会根据你的配置（R18 模式、返回数量）搜索并回复相应的插画图片及信息。

# 支持

[帮助](https://astrbot.app/)