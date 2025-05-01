# AstrBot Pixiv 搜索插件

[![文档](https://img.shields.io/badge/AstrBot-%E6%96%87%E6%A1%A3-blue)](https://astrbot.app)
[![aiohttp](https://img.shields.io/pypi/v/aiohttp.svg)](https://pypi.org/project/aiohttp/)

![:@astrbot_plugin_pixiv_search](https://count.getloli.com/get/@astrbot_plugin_pixiv_search?theme=booru-lewd)

这是一个为 [AstrBot](https://astrbot.app) 开发的插件，允许用户通过 Pixiv 标签搜索插画。

## ✨ 功能特性

* **标签搜索**: 使用命令 `/pixiv <标签1>,<标签2>,...` 来搜索相关 Pixiv 插画。
* **推荐作品**: 使用命令 `/pixiv_recommended` 获取 Pixiv 推荐作品。
* **用户查询**: 支持搜索用户、获取用户详情和作品列表。
* **小说搜索**: 使用命令 `/pixiv_novel <标签1>,<标签2>,...` 搜索 Pixiv 小说。
* **排行榜查询**: 使用命令 `/pixiv_ranking` 获取不同类型的排行榜作品。
* **相关作品**: 使用命令 `/pixiv_related <作品ID>` 获取与特定作品相关的其他作品。
* **图片发送**: 直接在聊天中发送搜索到的插画图片。
* **统一帮助**: 所有命令支持参数缺省或使用 help 参数获取详细使用说明。
* **优化标签显示**: 标签以易读形式显示，包含原名和翻译名（如有）。
* **R18 模式**: 可配置是否过滤 R18 内容、仅显示 R18 内容或不过滤。支持以下模式：
  - **过滤 R18**: 默认模式，自动过滤所有 R18 作品。
  - **允许 R18**: 不进行过滤，返回所有作品。
  - **仅 R18**: 仅返回 R18 作品。
* **数量控制**: 可配置每次搜索返回的图片数量。
* **安全配置**: 通过 AstrBot 插件配置系统安全管理 Pixiv API 凭据。
* **趋势标签**: 获取插画趋势标签。
* **深度搜索**: 使用 `/pixiv_deepsearch <标签1>,<标签2>,...` 命令进行深度搜索，返回更多相关作品。
* **与搜索**: 使用 `/pixiv_and <标签1>,<标签2>,...` 命令进行与搜索，返回同时包含所有指定标签的作品。
* **指定作品详情**: 使用 `/pixiv_specific <作品ID>` 命令获取指定作品详情。
* **是否通过文件转发**: 通过 `is_fromfilesystem` 参数控制是否通过文件转发图片，默认为 `true`。(特别慢,而且会占用大量内存,base64过长还会被截断,不推荐)
* **自动刷新 Refresh Token**: 通过 `refresh_token_interval_minutes` 参数控制自动刷新 Refresh Token 的间隔时间，默认为 180 分钟 (3 小时)。
## 🚀 开始使用

### 前提条件

* Python >= 3.10
* Git
* 已成功部署并运行的 AstrBot 实例 (v3.x 或更高版本) - 参考 [源码部署](https://astrbot.app/deploy/astrbot/cli.html) 或 [Docker 部署](https://astrbot.app/deploy/astrbot/docker.html)
* 一个有效的 Pixiv 账号，并已获取 `refresh_token` (推荐) 。获取 `refresh_token` 方法请参考 [pixivpy3 文档](https://pypi.org/project/pixivpy3/) 或[Pixiv OAuth](https://gist.github.com/ZipFile/c9ebedb224406f4f11845ab700124362)。

### 安装插件

1. 进入你的 AstrBot 主目录。
2. 导航到插件目录，并将本插件仓库克隆下来：
    ```bash
    # 进入 AstrBot 根目录
    # cd /path/to/your/AstrBot
    mkdir -p data/plugins
    cd data/plugins
    git clone https://github.com/vmoranv/astrbot_plugin_pixiv_search.git
    ```
    *注意：建议将克隆下来的文件夹重命名为 `astrbot_plugin_pixiv_search` (或与 `metadata.yaml` 中 `name` 字段一致的名称)。*

3. **检查/创建依赖文件**: 确保插件目录下 (`data/plugins/astrbot_plugin_pixiv_search/`) 存在 `requirements.txt` 文件，并包含以下内容：
    ```txt:requirements.txt
    # requirements.txt
    pixivpy3>=3.0.0  # 确保版本兼容
    aiohttp>=3.8.0   # 用于下载图片
    ```

4. **重启或重载**:
    * **首次安装**: 重启 AstrBot 以加载新插件及其依赖。
    * **更新插件**: 在 AstrBot WebUI 的 `插件市场` -> `本地插件` 中找到该插件，点击 `管理` -> `重载插件`。AstrBot 会自动尝试安装 `requirements.txt` 中新增或更新的依赖。如果遇到 `ModuleNotFoundError`，请尝试重启 AstrBot。

### 配置 Pixiv 凭据与选项 (重要!)

为了让插件能够访问 Pixiv API 并按需工作，你需要进行配置。

1. **通过 AstrBot WebUI 配置 (推荐)**:
    * 在 AstrBot WebUI 的 `插件管理` 中找到该插件，点击 `操作`->`插件配置`。
    * 在配置页面中，填写以下信息：
        * **Pixiv Refresh Token**: 必填，用于 API 认证。获取方法请参考 [pixivpy3 文档](https://pypi.org/project/pixivpy3/) 或[这里](https://gist.github.com/karakoo/5e7e0b1f3cc74cbcb7fce1c778d3709e)。
        * **R18 过滤模式**: 选择如何处理 R18 内容，默认为 "过滤 R18"。
        * **每次返回的图片数量**: 设置每次搜索返回的图片数量，默认为 1，范围为 1-10。
        * **AI 作品显示**: 选择是否显示 AI 生成的作品，默认为 "显示"。
    * 有关代理配置，请参考 [AstrBot 文档](https://astrbot.app/config/astrbot-config.html#http-proxy)。
    * 保存配置。

### 使用方法

配置完成后，你可以在任何已接入 AstrBot 的聊天平台（QQ、Telegram、微信等）中使用以下命令：

#### 基本命令

```bash
/pixiv <标签1>,<标签2>,...  # 搜索插画
/pixiv_help  # 显示帮助信息
```

*   使用英文逗号 `,` 分隔多个标签。
*   标签可以是中文、英文或日文。
*   多个标签是 `或` 关系。

例如：

```
/pixiv 初音ミク,VOCALOID
/pixiv scenery,beautiful
```

#### 高级命令

```bash
/pixiv_recommended  # 获取推荐作品
/pixiv_user_search <用户名>  # 搜索Pixiv用户
/pixiv_specific <作品ID>  # 获取指定作品详情
/pixiv_user_detail <用户ID>  # 获取指定用户的详细信息
/pixiv_user_illusts <用户ID>  # 获取指定用户的作品
/pixiv_novel <标签1>,<标签2>,...  # 搜索小说
/pixiv_ranking [mode] [date]  # 获取排行榜作品
/pixiv_related <作品ID>  # 获取与指定作品相关的其他作品
/pixiv_trending_tags  # 获取插画趋势标签
/pixiv_config  # 查看和修改配置
/pixiv_deepsearch <标签1>,<标签2>,...  # 深度搜索
/pixiv_and <标签1>,<标签2>,...  # 与搜索
```

所有命令（除 `/pixiv_recommended`）在参数缺省时会显示详细的帮助信息。

#### 标签显示格式

插件将以易读的格式显示标签信息，格式为：`标签名(翻译名)`。如果没有翻译名，则只显示标签名。

例如：
```
标签: 原神(Genshin Impact), シトラリ, Citlali, 美脚(beautiful legs), 裸足(barefoot)
```

机器人将会根据你的配置（R18 模式、返回数量）搜索并回复相应的插画图片及信息。

## 支持

如需更多帮助，请访问 [AstrBot 官方文档](https://astrbot.app/)

***重要***:如果遇到`SSLError`请更新DNS解析,移步至该issue:[SSLError](https://github.com/upbit/pixivpy/issues/244)
