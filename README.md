# AstrBot Pixiv 搜索插件

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/vmoranv/astrbot_plugin_pixiv_search)
[![文档](https://img.shields.io/badge/AstrBot-%E6%96%87%E6%A1%A3-blue)](https://astrbot.app)
[![aiohttp](https://img.shields.io/pypi/v/aiohttp.svg)](https://pypi.org/project/aiohttp/)

![:@astrbot_plugin_pixiv_search](https://count.getloli.com/get/@astrbot_plugin_pixiv_search?theme=booru-lewd)

这是一个为 [AstrBot](https://astrbot.app) 开发的 Pixiv 搜索插件，让你可以在聊天中轻松搜索和获取 Pixiv 插画作品。

## ✨ 核心特性

- 🎨 **多种搜索方式**: 支持标签搜索、用户搜索、作品详情查询
- 📚 **内容多样化**: 插画、小说、排行榜、推荐作品一应俱全  
- 🔍 **高级搜索**: 深度搜索、与搜索、相关作品推荐
- 🛡️ **内容控制**: 灵活的 R18 内容过滤配置
- ⚙️ **高度可配置**: 返回数量、显示详情、AI 作品过滤等
- 🔐 **安全管理**: 通过 WebUI 安全管理 API 凭据

## 🎯 主要功能

### 搜索功能
- `/pixiv <标签>` - 标签搜索插画
- `/pixiv_deepsearch <标签>` - 深度搜索更多相关作品
- `/pixiv_and <标签>` - 与搜索(同时包含所有标签)
- `/pixiv_user_search <用户名>` - 搜索用户
- `/pixiv_novel <标签>` - 搜索小说

### 排除 tag
- `-<tag>` - 排除包含 `<tag>` 的插画(仅在 /pixiv, /pixiv_novel, /pixiv_deepsearch, /pixiv_and 中有效)

### 内容获取
- `/pixiv_recommended` - 获取推荐作品
- `/pixiv_ranking [模式] [日期]` - 排行榜作品
- `/pixiv_trending_tags` - 获取趋势标签

### 详情查询
- `/pixiv_specific <作品ID>` - 指定作品详情
- `/pixiv_user_detail <用户ID>` - 用户详细信息
- `/pixiv_related <作品ID>` - 相关作品推荐

### 订阅功能
- `/pixiv_subscribe_add <画师ID>` - 订阅画师
- `/pixiv_subscribe_remove <画师ID>` - 取消订阅画师
- `/pixiv_subscribe_list` - 查看当前订阅列表

## 🚀 快速开始

### 前置条件

- Python >= 3.10
- 已部署的 AstrBot 实例 (v3.x+)
- 有效的 Pixiv 账号和 `refresh_token`

### 安装步骤

1. **克隆插件到 AstrBot 插件目录**
   ```bash
   cd /path/to/astrbot/data/plugins
   git clone https://github.com/vmoranv/astrbot_plugin_pixiv_search.git
   ```

2. **确认依赖文件**
   ```txt
   # requirements.txt
   pixivpy3>=3.0.0
   aiohttp>=3.8.0
   ```

3. **重启 AstrBot** 以加载插件和依赖

### 配置插件

1. 打开 AstrBot WebUI
2. 进入 `插件管理` -> 找到 Pixiv 搜索插件
3. 点击 `插件配置`，填写以下信息：
   - **Refresh Token**: 必填，用于 Pixiv API 认证
   - **R18 过滤模式**: 过滤R18/允许R18/仅R18
   - **返回图片数量**: 1-10张，默认1张
   - **AI作品显示**: 是否显示AI生成作品
   - **其他选项**: 详情显示、文件转发等

4. 保存配置

### 获取 Refresh Token

参考以下资源获取 Pixiv `refresh_token`:
- [pixivpy3 官方文档](https://pypi.org/project/pixivpy3/)
- [Pixiv OAuth 教程](https://gist.github.com/ZipFile/c9ebedb224406f4f11845ab700124362)

## 📝 使用示例

```bash
# 基础搜索
/pixiv 初音ミク,VOCALOID
/pixiv 茉莉安,-ntr

# 高级搜索  
/pixiv_deepsearch 原神,风景
/pixiv_and 初音ミク,可爱

# 获取推荐和排行榜
/pixiv_recommended
/pixiv_ranking daily

# 用户相关
/pixiv_user_search 某个画师名
/pixiv_user_detail 123456

# 获取帮助
/pixiv_help

# 订阅功能
/pixiv_subscribe_add 123456
/pixiv_subscribe_remove 123456
/pixiv_subscribe_list
```

## ⚙️ 配置选项

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `refresh_token` | Pixiv API 认证令牌 | 必填 |
| `r18_mode` | R18内容处理模式 | 过滤R18 |
| `image_count` | 每次返回图片数量 | 1 |
| `ai_type` | AI作品显示设置 | 显示 |
| `show_details` | 是否显示详细信息 | true |
| `show_filter_result` | 是否显示过滤提示 | true |
| `is_fromfilesystem` | 是否通过文件转发 | true |
| `proxy` | 网络代理地址，如 `http://127.0.0.1:7890` | 留空 |

## 🛠️ 开发构建

```bash
# 克隆项目
git clone https://github.com/vmoranv/astrbot_plugin_pixiv_search.git
cd astrbot_plugin_pixiv_search

# 安装依赖
pip install -r requirements.txt

# 部署到 AstrBot
cp -r . /path/to/astrbot/data/plugins/astrbot_plugin_pixiv_search/
```

## 🔧 故障排除

**SSL 错误**: 如遇到 `SSLError`，请更新 DNS 解析设置。参考: [SSLError 解决方案](https://github.com/upbit/pixivpy/issues/244)

**模块未找到**: 重启 AstrBot 以确保依赖正确安装

**API 认证失败**: 检查 `refresh_token` 是否有效和正确配置

## 📖 更多信息

- [AstrBot 官方文档](https://astrbot.app/)
- [插件开发指南](https://astrbot.app/develop/plugin.html)
- [问题反馈](https://github.com/vmoranv/astrbot_plugin_pixiv_search/issues)

## ⭐ 项目统计

<div align="center">

[![Star History Chart](https://api.star-history.com/svg?repos=vmoranv/astrbot_plugin_pixiv_search&type=Date)](https://star-history.com/#vmoranv/astrbot_plugin_pixiv_search&Date)

![Analytics](https://repobeats.axiom.co/api/embed/9e6727cd94536119069eebccfe45b505ac499470.svg "Repobeats analytics image")

</div>

## 📄 许可证

本项目遵循开源许可证，具体许可证信息请查看项目根目录下的 LICENSE 文件。

---

**注意**: 使用本插件需遵守 Pixiv 服务条款和相关法律法规。请合理使用 API 避免频繁请求。