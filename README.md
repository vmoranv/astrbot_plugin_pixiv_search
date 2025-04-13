# AstrBot Pixiv 插画获取插件

[![文档](https://img.shields.io/badge/AstrBot-%E6%96%87%E6%A1%A3-blue)](https://astrbot.app)
[![pixiv-api](https://img.shields.io/pypi/v/pixiv-api.svg)](https://pypi.org/project/pixiv-api/)

这是一个为 [AstrBot](https://astrbot.app) 开发的插件，允许用户通过 Pixiv 插画 ID 获取插画的详细信息和图片。

## ✨ 功能特性

*   **ID 获取**: 使用简单的命令 `/p站插画 <插画ID>` 来获取指定 Pixiv 插画。
*   **信息展示**: 显示插画的标题和作者。
*   **图片发送**: 直接在聊天中发送插画图片（支持多平台，具体见 AstrBot 文档）。
*   **安全配置**: 通过 AstrBot 插件配置系统安全管理 Pixiv API 凭据。

## 🚀 开始使用

### 前提条件

*   Python >= 3.10
*   Git
*   已成功部署并运行的 AstrBot 实例 (v3.x 或更高版本) - 参考 [源码部署](https://astrbot.app/deploy/astrbot/cli.html) 或 [Docker 部署](https://astrbot.app/deploy/astrbot/docker.html)
*   一个有效的 Pixiv 账号，并已获取 `refresh_token` (获取方法请参考 [pixiv-api 文档](https://pixiv-api.readthedocs.io/en/latest/authentication.html) 或其他网络教程)。

### 安装插件

1.  进入你的 AstrBot 主目录。
2.  导航到插件目录，并将本插件仓库克隆下来：
    ```bash
    # 进入 AstrBot 根目录
    # cd /path/to/your/AstrBot
    mkdir -p data/plugins
    cd data/plugins
    # 将下面的 URL 替换为你的插件仓库地址
    git clone https://github.com/vmoranv/astrbot_plugin_pixiv_search.git
    ```

3.  **检查/创建依赖文件**: 确保插件目录下 存在 `requirements.txt` 文件，并包含以下内容：
    ```txt
    # requirements.txt
    pixiv-api>=3.0.0 # 确保版本兼容
    ```

4.  **重启或重载**:
    *   **首次安装**: 重启 AstrBot 以加载新插件及其依赖。
    *   **更新插件**: 在 AstrBot WebUI 的 `插件市场` -> `本地插件` 中找到该插件，点击 `管理` -> `重载插件`。AstrBot 会自动尝试安装 `requirements.txt` 中新增或更新的依赖。如果遇到 `ModuleNotFoundError`，请尝试重启 AstrBot。

### 配置 Pixiv 凭据 (重要!)

为了让插件能够访问 Pixiv API，你需要配置你的 `refresh_token`。**请勿将 Token 硬编码在代码中！**

1.  在你的 AstrBot 数据目录下，找到插件的配置目录：`data/astrbot_plugin_pixiv_fetcher/`。
2.  在该目录下创建一个名为 `config.yaml` 的文件。
3.  将你的 Pixiv `refresh_token` 添加到 `config.yaml` 文件中，格式如下：

    ```yaml
    # data/astrbot_plugin_pixiv_fetcher/config.yaml
    pixiv_refresh_token: "你的_refresh_token_粘贴在这里"
    # 可选：配置代理，如果你的网络访问 Pixiv API 需要代理
    # pixiv_proxy: "http://your_proxy_server:port"
    ```
4.  保存文件。
5.  在 AstrBot WebUI 中重载该插件，使配置生效。

插件代码将自动从这个配置文件中读取 `pixiv_refresh_token`。

### 使用方法

配置完成后，你可以在任何已接入 AstrBot 的聊天平台（QQ、Telegram、微信等）中使用以下命令：
