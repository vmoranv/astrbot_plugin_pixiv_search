import asyncio
import random
from typing import Dict, Any
import aiohttp
import aiofiles
import uuid
import os

from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Image, Plain, Node, Nodes
from astrbot.api.all import command
from pixivpy3 import AppPixivAPI, PixivError

from .config import TEMP_DIR, clean_temp_dir
from .tag import build_detail_message, filter_illusts_with_reason


@register(
    "pixiv_search",
    "vmoranv",
    "Pixiv 图片搜索",
    "1.2.2",
    "https://github.com/vmoranv/astrbot_plugin_pixiv_search",
)
class PixivSearchPlugin(Star):
    """
    AstrBot 插件，用于通过 Pixiv API 搜索插画。
    配置通过 AstrBot WebUI 进行管理。
    用法:
        /pixiv <标签1>,<标签2>,...  搜索 Pixiv 插画
        /pixiv help                 查看帮助信息
    可在配置中设置认证信息、返回数量和 R18 过滤模式。
    """

    def __init__(self, context: Context, config: Dict[str, Any]):
        """初始化 Pixiv 插件"""
        super().__init__(context)
        self.config = config
        self.client = AppPixivAPI()
        self.refresh_token = self.config.get("refresh_token", None)
        self.return_count = self.config.get("return_count", 1)
        self.r18_mode = self.config.get("r18_mode", "过滤 R18")
        self.ai_filter_mode = self.config.get("ai_filter_mode", "过滤 AI 作品")
        self.show_filter_result = self.config.get("show_filter_result", True)
        self.show_details = self.config.get("show_details", True)
        self.deep_search_depth = self.config.get("deep_search_depth", 3)
        self.forward_threshold = self.config.get("forward_threshold", 5)
        self.is_fromfilesystem = self.config.get("is_fromfilesystem", True)
        self.refresh_interval = self.config.get("refresh_token_interval_minutes", 720)
        self._refresh_task: asyncio.Task = None
        self.AUTH_ERROR_MSG = (
            "Pixiv API 认证失败，请检查配置中的凭据信息。\n"
            "先带脑子配置代理->[Astrbot代理配置教程](https://astrbot.app/config/astrbot-config.html#http-proxy);\n"
            "再填入refresh_token->**Pixiv Refresh Token**: 必填，用于 API 认证。获取方法请参考 "
            "[pixivpy3 文档](https://pypi.org/project/pixivpy3/) 或[这里](https://gist.github.com/karakoo/5e7e0b1f3cc74cbcb7fce1c778d3709e)。"
        )
        
        # 记录初始化信息，包含 AI 过滤模式和详细信息设置
        logger.info(
            f"Pixiv 插件配置加载：refresh_token={'已设置' if self.refresh_token else '未设置'}, "
            f"return_count={self.return_count}, r18_mode='{self.r18_mode}', "
            f"ai_filter_mode='{self.ai_filter_mode}', show_details={self.show_details}, "
            f"refresh_interval={self.refresh_interval} 分钟"
        )

        # 启动后台刷新任务 (如果间隔大于 0)
        if self.refresh_interval > 0:
            self._refresh_task = asyncio.create_task(self._periodic_token_refresh())
            logger.info(
                f"Pixiv 插件：已启动 Refresh Token 自动刷新任务，间隔 {self.refresh_interval} 分钟。"
            )
        else:
            logger.info("Pixiv 插件：Refresh Token 自动刷新已禁用 (间隔 <= 0)。")

    def filter_items(self, items, tag_label):
        """
        统一过滤插画/小说的辅助方法，只需传入待过滤对象和标签描述。
        其他参数自动使用插件全局配置。
        """
        return filter_illusts_with_reason(
            items,
            self.r18_mode,
            self.ai_filter_mode,
            display_tag_str=tag_label,
            return_count=self.return_count,
            logger=logger,
            show_filter_result=self.show_filter_result,
        )

    @staticmethod
    def info() -> Dict[str, Any]:
        """返回插件元数据"""
        return {
            "name": "pixiv_search",
            "author": "vmoranv",
            "description": "Pixiv 图片搜索",
            "version": "1.2.2",
            "homepage": "https://github.com/vmoranv/astrbot_plugin_pixiv_search",
        }

    async def _authenticate(self) -> bool:
        """尝试使用配置的凭据进行 Pixiv API 认证"""
        # 每次调用都尝试认证，让 pixivpy3 处理 token 状态
        logger.info("Pixiv 插件：尝试进行 Pixiv API 认证/状态检查...")
        try:
            if self.refresh_token:
                # 调用 auth()，pixivpy3 会在需要时刷新 token
                self.client.auth(refresh_token=self.refresh_token)
                logger.info("Pixiv 插件：认证状态检查/刷新完成。")
                return True
            else:
                logger.error("Pixiv 插件：未提供有效的 Refresh Token，无法进行认证。")
                return False

        except Exception as e:
            logger.error(
                f"Pixiv 插件：认证/刷新时发生错误 - 异常类型: {type(e)}, 错误信息: {e}"
            )
            return False

    async def send_pixiv_image(
        self,
        event: AstrMessageEvent,
        illust,
        detail_message: str = None,
        show_details: bool = True,
    ):
        """
        通用Pixiv图片下载与发送函数，自动选择最佳图片链接（original>large>medium），采用本地文件缓存，自动清理缓存目录，发送后删除临时文件。

        参数：
            event: 消息事件对象（AstrMessageEvent）
            illust: Pixiv插画对象
            detail_message: 附加文本（如作品详情，可选，str）
            show_details: 是否发送详情文本（bool，默认True）
        返回：
            通过 yield 方式返回消息结果对象，供主命令 yield 派发
        """

        # 自动选择最佳图片链接
        img_urls = getattr(illust, "image_urls", None)
        image_url = None
        if img_urls:
            if hasattr(img_urls, "original") and img_urls.original:
                image_url = img_urls.original
            elif hasattr(img_urls, "large") and img_urls.large:
                image_url = img_urls.large
            elif hasattr(img_urls, "medium") and img_urls.medium:
                image_url = img_urls.medium
        if not image_url:
            yield event.plain_result("未找到可用图片链接，无法发送。")
            return

        # 1. 清理缓存目录，保证不超过20张
        clean_temp_dir(max_files=20)
        filename = os.path.join(TEMP_DIR, f"pixiv_{uuid.uuid4().hex}.jpg")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    image_url, headers={"Referer": "https://app-api.pixiv.net/"}
                ) as response:
                    if response.status == 200:
                        img_data = await response.read()
                        async with aiofiles.open(filename, "wb") as f:
                            await f.write(img_data)
                        if show_details and detail_message:
                            yield event.chain_result(
                                [Image.fromFileSystem(filename), Plain(detail_message)]
                            )
                        else:
                            yield event.chain_result([Image.fromFileSystem(filename)])
                    else:
                        yield event.plain_result(
                            f"图片下载失败，仅发送信息：\n{detail_message or ''}"
                        )
        except Exception as e:
            yield event.plain_result(
                f"图片下载异常，仅发送信息：\n{detail_message or ''}"
            )
            logger.error(f"Pixiv 插件：图片下载异常 - {e}")
            import traceback

            logger.error(traceback.format_exc())
        finally:
            # 发送后删除临时文件
            if os.path.exists(filename):
                try:
                    os.remove(filename)
                except Exception as e:
                    print(
                        f"[PixivPlugin] 删除发送后临时图片失败: {filename}，原因: {e}"
                    )

    async def send_forward_message(self, event, images, build_detail_message_func):
        """
        直接下载图片并组装 nodes，避免不兼容消息类型。
        """
        batch_size = 10
        nickname = "PixivBot"
        clean_temp_dir(max_files=20)
        for i in range(0, len(images), batch_size):
            batch_imgs = images[i : i + batch_size]
            nodes_list = []
            async with aiohttp.ClientSession() as session:
                for img in batch_imgs:
                    detail_message = build_detail_message_func(img)
                    image_url = img.image_urls.medium
                    headers = {
                        "Referer": "https://www.pixiv.net/",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                    }
                    node_content = []
                    filename = os.path.join(TEMP_DIR, f"pixiv_{uuid.uuid4().hex}.jpg")
                    if image_url:
                        try:
                            async with session.get(image_url, headers=headers) as resp:
                                if resp.status == 200:
                                    img_data = await resp.read()
                                    if self.is_fromfilesystem:
                                        async with aiofiles.open(filename, "wb") as f:
                                            await f.write(img_data)
                                        node_content.append(
                                            Image.fromFileSystem(filename)
                                        )
                                    else:
                                        node_content.append(Image.fromBytes(img_data))
                                else:
                                    node_content.append(
                                        Plain(f"图片下载失败: {image_url}")
                                    )
                        except Exception as e:
                            node_content.append(Plain(f"图片下载异常: {e}"))
                    else:
                        node_content.append(Plain("未找到图片链接"))
                    if self.show_details:
                        node_content.append(Plain(detail_message))
                    node = Node(name=nickname, content=node_content)
                    nodes_list.append(node)
            if nodes_list:
                nodes_obj = Nodes(nodes=nodes_list)
                yield event.chain_result([nodes_obj])

    @command("pixiv")
    async def pixiv(self, event: AstrMessageEvent, tags: str = ""):
        """处理 /pixiv 命令，默认为标签搜索功能"""
        # 清理标签字符串，并检查是否为空或为 "help"
        cleaned_tags = tags.strip()

        if cleaned_tags.lower() == "help":
            yield self.pixiv_help(event)
            return

        if not cleaned_tags:
            logger.info("Pixiv 插件：用户未提供搜索标签或标签为空，返回帮助信息。")
            yield event.plain_result(
                "请输入要搜索的标签。使用 `/pixiv_help` 查看帮助。\n" + self.AUTH_ERROR_MSG
            )
            return

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result(self.AUTH_ERROR_MSG)
            return

        # 标签搜索处理
        logger.info(f"Pixiv 插件：正在搜索标签 - {cleaned_tags}")
        try:
            search_result = self.client.search_illust(
                cleaned_tags, search_target="partial_match_for_tags"
            )
            initial_illusts = search_result.illusts if search_result.illusts else []

            if not initial_illusts:
                yield event.plain_result("未找到相关插画。")
                return

            # 统一使用 filter_illusts_with_reason 进行过滤和提示
            filtered_illusts, filter_msgs = self.filter_items(
                initial_illusts, cleaned_tags
            )
            if self.show_filter_result:
                for msg in filter_msgs:
                    yield event.plain_result(msg)
            if not filtered_illusts:
                return

            # 限制返回数量
            count_to_send = min(len(filtered_illusts), self.return_count)
            illusts_to_send = (
                random.sample(filtered_illusts, count_to_send)
                if count_to_send > 0
                else []
            )

            if not illusts_to_send:
                logger.info("没有符合条件的推荐插画可供发送。")
                return

            threshold = self.config.get("forward_threshold", 5)
            if len(illusts_to_send) > threshold:
                async for result in self.send_forward_message(
                    event,
                    illusts_to_send,
                    lambda illust: build_detail_message(illust, is_novel=False),
                ):
                    yield result
            else:
                for illust in illusts_to_send:
                    detail_message = build_detail_message(illust, is_novel=False)
                    async for result in self.send_pixiv_image(
                        event, illust, detail_message, show_details=self.show_details
                    ):
                        yield result

        except Exception as e:
            logger.error(f"Pixiv 插件：搜索插画时发生错误 - {e}")
            yield event.plain_result(f"搜索插画时发生错误: {str(e)}")

    @command("pixiv_help")
    async def pixiv_help(self, event: AstrMessageEvent):
        """生成并返回帮助信息"""

        help_text = """# Pixiv 搜索插件使用帮助

## 基本命令
- `/pixiv <标签1>,<标签2>,...` - 搜索含有任意指定标签的插画 (OR 搜索)
- `/pixiv_help` - 显示此帮助信息

## 高级命令
- `/pixiv_recommended` - 获取推荐作品
- `/pixiv_specific <作品ID>` - 获取指定作品详情
- `/pixiv_user_search <用户名>` - 搜索Pixiv用户
- `/pixiv_user_detail <用户ID>` - 获取指定用户的详细信息
- `/pixiv_user_illusts <用户ID>` - 获取指定用户的作品
- `/pixiv_novel <标签1>,<标签2>,...` - 搜索小说 (OR 搜索)
- `/pixiv_ranking [mode] [date]` - 获取排行榜作品
- `/pixiv_related <作品ID>` - 获取与指定作品相关的其他作品
- `/pixiv_trending_tags` - 获取当前的插画趋势标签
- `/pixiv_deepsearch <标签1>,<标签2>,...` - 深度搜索插画 (OR 搜索，跨多页)
- `/pixiv_and <标签1>,<标签2>,...` - 深度搜索同时包含所有指定标签的插画 (AND 搜索，跨多页)

## 配置信息
- 当前 R18 模式: {r18_mode}
- 当前返回数量: {return_count}
- 当前 AI 作品模式: {ai_filter_mode}
- 深度搜索翻页深度: {deep_search_depth} (-1 表示不限制)
- 是否显示详细信息: {show_details}
- 超过 {forward_threshold} 张时自动使用消息转发
- 是否通过文件转发: {is_fromfilesystem}
## 注意事项
- OR 搜索 (如 /pixiv, /pixiv_deepsearch) 使用英文逗号(,)分隔标签
- AND 搜索 (/pixiv_and) 使用英文逗号(,)分隔标签
- 获取用户作品或相关作品时，ID必须为数字
- 日期必须采用 YYYY-MM-DD 格式
- 带脑子配置代理->[Astrbot代理配置教程](https://astrbot.app/config/astrbot-config.html#http-proxy)
- 填入refresh_token->**Pixiv Refresh Token**: 必填，用于 API 认证。获取方法请参考 [pixivpy3 文档](https://pypi.org/project/pixivpy3/) 或[这里](https://gist.github.com/karakoo/5e7e0b1f3cc74cbcb7fce1c778d3709e)。
- 使用 `/命令` 或 `/命令 help` 可获取每个命令的详细说明
- 仔细看[README.md](https://github.com/vmoranv/astrbot_plugin_pixiv_search/blob/master/README.md)
    """.format(
            r18_mode=self.r18_mode,
            return_count=self.return_count,
            ai_filter_mode=self.ai_filter_mode,
            deep_search_depth=self.deep_search_depth,
            show_details=self.show_details,
            forward_threshold=self.forward_threshold,
            is_fromfilesystem=self.is_fromfilesystem,
        )

        yield event.plain_result(help_text)

    @command("pixiv_recommended")
    async def pixiv_recommended(self, event: AstrMessageEvent, args: str = ""):
        """获取 Pixiv 推荐作品"""

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result(self.AUTH_ERROR_MSG)
            return

        logger.info("Pixiv 插件：获取推荐作品")
        try:
            # 调用 API 获取推荐
            recommend_result = self.client.illust_recommended()
            initial_illusts = (
                recommend_result.illusts if recommend_result.illusts else []
            )

            if not initial_illusts:
                yield event.plain_result("未能获取到推荐作品。")
                return

            # 统一使用 filter_illusts_with_reason 进行过滤和提示
            filtered_illusts, filter_msgs = self.filter_items(initial_illusts, "推荐")
            if self.show_filter_result:
                for msg in filter_msgs:
                    yield event.plain_result(msg)
            if not filtered_illusts:
                return

            # 限制返回数量
            count_to_send = min(len(filtered_illusts), self.return_count)
            if count_to_send > 0:
                illusts_to_send = filtered_illusts[:count_to_send]
            else:
                illusts_to_send = []

            threshold = self.config.get("forward_threshold", 5)
            if len(illusts_to_send) > threshold:
                async for result in self.send_forward_message(
                    event,
                    illusts_to_send,
                    lambda illust: build_detail_message(illust, is_novel=False),
                ):
                    yield result
            else:
                for illust in illusts_to_send:
                    detail_message = build_detail_message(illust, is_novel=False)
                    async for result in self.send_pixiv_image(
                        event, illust, detail_message, show_details=self.show_details
                    ):
                        yield result

        except Exception as e:
            logger.error(f"Pixiv 插件：获取推荐作品时发生错误 - {e}")
            yield event.plain_result(f"获取推荐作品时发生错误: {str(e)}")

    @command("pixiv_ranking")
    async def pixiv_ranking(self, event: AstrMessageEvent, args: str = ""):
        """获取 Pixiv 排行榜作品"""
        args_list = args.strip().split() if args.strip() else []

        # 如果没有传入参数或者第一个参数是 'help'，显示帮助信息
        if not args_list or args_list[0].lower() == "help":
            help_text = """# Pixiv 排行榜查询

## 命令格式
`/pixiv_ranking [mode] [date]`

## 参数说明
- `mode`: 排行榜模式，可选值：
  - 常规模式: day, week, month, day_male, day_female, week_original, week_rookie, day_manga
  - R18模式(需开启R18): day_r18, day_male_r18, day_female_r18, week_r18, week_r18g
- `date`: 日期，格式为 YYYY-MM-DD，可选，默认为最新

## 示例
- `/pixiv_ranking week` - 获取每周排行榜
- `/pixiv_ranking day 2023-05-01` - 获取2023年5月1日的每日排行榜
- `/pixiv_ranking day_r18` - 获取R18每日排行榜（需开启R18模式）
"""
            yield event.plain_result(help_text)
            return

        # 解析参数
        mode = args_list[0] if len(args_list) > 0 else "day"
        date = args_list[1] if len(args_list) > 1 else None

        # 验证模式参数
        valid_modes = [
            "day",
            "week",
            "month",
            "day_male",
            "day_female",
            "week_original",
            "week_rookie",
            "day_manga",
            "day_r18",
            "day_male_r18",
            "day_female_r18",
            "week_r18",
            "week_r18g",
        ]

        if mode not in valid_modes:
            yield event.plain_result(
                f"无效的排行榜模式: {mode}\n请使用 `/pixiv_ranking help` 查看支持的模式"
            )
            return

        # 验证日期格式
        if date:
            try:
                # 简单验证日期格式
                year, month, day = date.split("-")
                if not (len(year) == 4 and len(month) == 2 and len(day) == 2):
                    raise ValueError("日期格式不正确")
            except Exception:
                yield event.plain_result(
                    f"无效的日期格式: {date}\n日期应为 YYYY-MM-DD 格式"
                )
                return

        # 检查 R18 权限
        if "r18" in mode and self.r18_mode == "过滤 R18":
            yield event.plain_result(
                "当前 R18 模式设置为「过滤 R18」，无法使用 R18 相关排行榜。"
            )
            return

        logger.info(
            f"Pixiv 插件：正在获取排行榜 - 模式: {mode}, 日期: {date if date else '最新'}"
        )

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result(self.AUTH_ERROR_MSG)
            return

        try:
            # 调用 Pixiv API 获取排行榜
            ranking_result = self.client.illust_ranking(mode=mode, date=date)
            initial_illusts = ranking_result.illusts if ranking_result.illusts else []

            if not initial_illusts:
                yield event.plain_result(f"未能获取到 {date} 的 {mode} 排行榜数据。")
                return

            # 统一使用 filter_illusts_with_reason 进行过滤和提示
            filtered_illusts, filter_msgs = self.filter_items(
                initial_illusts, f"排行榜:{mode}"
            )
            if self.show_filter_result:
                for msg in filter_msgs:
                    yield event.plain_result(msg)
            if not filtered_illusts:
                return

            # 限制返回数量
            count_to_send = min(len(filtered_illusts), self.return_count)
            illusts_to_send = (
                random.sample(filtered_illusts, count_to_send)
                if count_to_send > 0
                else []
            )

            threshold = self.config.get("forward_threshold", 5)
            if len(illusts_to_send) > threshold:
                async for result in self.send_forward_message(
                    event,
                    illusts_to_send,
                    lambda illust: build_detail_message(illust, is_novel=False),
                ):
                    yield result
            else:
                for illust in illusts_to_send:
                    detail_message = build_detail_message(illust, is_novel=False)
                    async for result in self.send_pixiv_image(
                        event, illust, detail_message, show_details=self.show_details
                    ):
                        yield result

        except Exception as e:
            logger.error(f"Pixiv 插件：获取排行榜时发生错误 - {e}")
            yield event.plain_result(f"获取排行榜时发生错误: {str(e)}")

    @command("pixiv_related")
    async def pixiv_related(self, event: AstrMessageEvent, illust_id: str = ""):
        """获取与指定作品相关的其他作品"""
        # 检查参数是否为空或为 help
        if not illust_id.strip() or illust_id.strip().lower() == "help":
            help_text = """# Pixiv 相关作品

## 命令格式
`/pixiv_related <作品ID>`

## 参数说明
- `作品ID`: Pixiv 作品的数字ID

## 示例
- `/pixiv_related 12345678` - 获取ID为12345678的作品的相关作品
"""
            yield event.plain_result(help_text)
            return

        # 验证作品ID是否为数字
        if not illust_id.isdigit():
            yield event.plain_result(f"作品ID必须是数字: {illust_id}")
            return

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result(self.AUTH_ERROR_MSG)
            return

        logger.info(f"Pixiv 插件：获取相关作品 - ID: {illust_id}")
        try:
            # 调用 API 获取相关作品
            related_result = self.client.illust_related(int(illust_id))
            initial_illusts = related_result.illusts if related_result.illusts else []

            if not initial_illusts:
                yield event.plain_result(f"未能找到与作品 ID {illust_id} 相关的作品。")
                return

            # 统一使用 filter_illusts_with_reason 进行过滤和提示
            filtered_illusts, filter_msgs = self.filter_items(
                initial_illusts, f"相关:{illust_id}"
            )
            if self.show_filter_result:
                for msg in filter_msgs:
                    yield event.plain_result(msg)
            if not filtered_illusts:
                return

            # 限制返回数量
            count_to_send = min(len(filtered_illusts), self.return_count)
            illusts_to_send = (
                random.sample(filtered_illusts, count_to_send)
                if count_to_send > 0
                else []
            )

            threshold = self.config.get("forward_threshold", 5)
            if len(illusts_to_send) > threshold:
                async for result in self.send_forward_message(
                    event,
                    illusts_to_send,
                    lambda illust: build_detail_message(illust, is_novel=False),
                ):
                    yield result
            else:
                for illust in illusts_to_send:
                    detail_message = build_detail_message(illust, is_novel=False)
                    async for result in self.send_pixiv_image(
                        event, illust, detail_message, show_details=self.show_details
                    ):
                        yield result

        except Exception as e:
            logger.error(f"Pixiv 插件：获取相关作品时发生错误 - {e}")
            yield event.plain_result(f"获取相关作品时发生错误: {str(e)}")

    @command("pixiv_user_search")
    async def pixiv_user_search(self, event: AstrMessageEvent, username: str = ""):
        """搜索 Pixiv 用户"""
        # 检查参数是否为空或为 help
        if not username.strip() or username.strip().lower() == "help":
            help_text = """# Pixiv 用户搜索

## 命令格式
`/pixiv_user_search <用户名>`

## 参数说明
- `用户名`: 要搜索的 Pixiv 用户名

## 示例
- `/pixiv_user_search 初音ミク` - 搜索名称包含"初音ミク"的用户
- `/pixiv_user_search gomzi` - 搜索名称包含"gomzi"的用户
"""
            yield event.plain_result(help_text)
            return

        logger.info(f"Pixiv 插件：正在搜索用户 - {username}")

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result(self.AUTH_ERROR_MSG)
            return

        try:
            # 调用 Pixiv API 搜索用户
            json_result = self.client.search_user(username)
            if (
                not json_result
                or not hasattr(json_result, "user_previews")
                or not json_result.user_previews
            ):
                yield event.plain_result(f"未找到用户: {username}")
                return

            # 获取第一个用户
            user_preview = json_result.user_previews[0]
            user = user_preview.user

            # 构建用户信息
            user_info = f"用户名: {user.name}\n"
            user_info += f"用户ID: {user.id}\n"
            user_info += f"账号: @{user.account}\n"
            user_info += f"个人主页: https://www.pixiv.net/users/{user.id}"

            # 如果有作品，统一用 filter_illusts_with_reason 过滤预览插画
            illusts = (
                user_preview.illusts
                if hasattr(user_preview, "illusts") and user_preview.illusts
                else []
            )
            filtered_illusts, filter_msgs = self.filter_items(
                illusts, f"用户:{user.name}"
            )
            if self.show_filter_result:
                for msg in filter_msgs:
                    yield event.plain_result(msg)

            # 始终显示用户基本信息
            yield event.plain_result(user_info)

            # 如果有合规插画，发送第一张插画
            if filtered_illusts:
                illust = filtered_illusts[0]
                detail_message = build_detail_message(illust, is_novel=False)
                async for result in self.send_pixiv_image(
                    event, illust, detail_message, show_details=self.show_details
                ):
                    yield result

        except Exception as e:
            logger.error(f"Pixiv 插件：搜索用户时发生错误 - {e}")
            yield event.plain_result(f"搜索用户时发生错误: {str(e)}")

    @command("pixiv_user_detail")
    async def pixiv_user_detail(self, event: AstrMessageEvent, user_id: str = ""):
        """获取 Pixiv 用户详情"""
        # 检查参数是否为空或为 help
        if not user_id.strip() or user_id.strip().lower() == "help":
            help_text = """# Pixiv 用户详情

## 命令格式
`/pixiv_user_detail <用户ID>`

## 参数说明
- `用户ID`: Pixiv 用户的数字ID

## 示例
- `/pixiv_user_detail 660788` - 获取ID为660788的用户详情
"""
            yield event.plain_result(help_text)
            return

        logger.info(f"Pixiv 插件：正在获取用户详情 - ID: {user_id}")

        # 验证用户ID是否为数字
        if not user_id.isdigit():
            yield event.plain_result(f"用户ID必须是数字: {user_id}")
            return

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result(self.AUTH_ERROR_MSG)
            return

        try:
            # 调用 Pixiv API 获取用户详情
            json_result = self.client.user_detail(user_id)
            if not json_result or not hasattr(json_result, "user"):
                yield event.plain_result(f"未找到用户 - ID: {user_id}")
                return

            user = json_result.user
            profile = json_result.profile if hasattr(json_result, "profile") else None

            # 构建用户详情信息
            detail_info = f"用户名: {user.name}\n"
            detail_info += f"用户ID: {user.id}\n"
            detail_info += f"账号: @{user.account}\n"

            if profile:
                detail_info += f"地区: {profile.region if hasattr(profile, 'region') else '未知'}\n"
                detail_info += f"生日: {profile.birth_day if hasattr(profile, 'birth_day') else '未知'}\n"
                detail_info += f"性别: {profile.gender if hasattr(profile, 'gender') else '未知'}\n"
                detail_info += f"插画数: {profile.total_illusts if hasattr(profile, 'total_illusts') else '未知'}\n"
                detail_info += f"漫画数: {profile.total_manga if hasattr(profile, 'total_manga') else '未知'}\n"
                detail_info += f"小说数: {profile.total_novels if hasattr(profile, 'total_novels') else '未知'}\n"
                detail_info += f"收藏数: {profile.total_illust_bookmarks_public if hasattr(profile, 'total_illust_bookmarks_public') else '未知'}\n"

            detail_info += (
                f"简介: {user.comment if hasattr(user, 'comment') else '无'}\n"
            )
            detail_info += f"个人主页: https://www.pixiv.net/users/{user.id}"

            # 返回用户详情
            yield event.plain_result(detail_info)

        except Exception as e:
            logger.error(f"Pixiv 插件：获取用户详情时发生错误 - {e}")
            yield event.plain_result(f"获取用户详情时发生错误: {str(e)}")

    @command("pixiv_user_illusts")
    async def pixiv_user_illusts(self, event: AstrMessageEvent, user_id: str = ""):
        """获取指定用户的作品"""
        # 检查参数是否为空或为 help
        if not user_id.strip() or user_id.strip().lower() == "help":
            help_text = """# Pixiv 用户作品

## 命令格式
`/pixiv_user_illusts <用户ID>`

## 参数说明
- `用户ID`: Pixiv 用户的数字ID

## 示例
- `/pixiv_user_illusts 660788` - 获取ID为660788的用户的作品
"""
            yield event.plain_result(help_text)
            return

        logger.info(f"Pixiv 插件：正在获取用户作品 - ID: {user_id}")

        # 验证用户ID是否为数字
        if not user_id.isdigit():
            yield event.plain_result(f"用户ID必须是数字: {user_id}")
            return

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result(self.AUTH_ERROR_MSG)
            return

        try:
            # 获取用户信息以显示用户名
            user_detail_result = self.client.user_detail(int(user_id))
            user_name = (
                user_detail_result.user.name
                if user_detail_result and user_detail_result.user
                else f"用户ID {user_id}"
            )

            # 调用 API 获取用户作品
            user_illusts_result = self.client.user_illusts(int(user_id))
            initial_illusts = (
                user_illusts_result.illusts if user_illusts_result.illusts else []
            )

            if not initial_illusts:
                yield event.plain_result(
                    f"用户 {user_name} ({user_id}) 没有公开的作品。"
                )
                return

            # 统一使用 filter_illusts_with_reason 进行过滤和提示
            filtered_illusts, filter_msgs = self.filter_items(
                initial_illusts, f"用户:{user_name}"
            )
            if self.show_filter_result:
                for msg in filter_msgs:
                    yield event.plain_result(msg)
            if not filtered_illusts:
                return

            # 限制返回数量
            count_to_send = min(len(filtered_illusts), self.return_count)
            illusts_to_send = (
                random.sample(filtered_illusts, count_to_send)
                if count_to_send > 0
                else []
            )

            # 发送选定的插画
            if not illusts_to_send:
                logger.info(f"用户 {user_id} 没有符合条件的插画可供发送。")

            for illust in illusts_to_send:
                # 统一使用build_detail_message生成详情信息
                detail_message = build_detail_message(illust, is_novel=False)
                async for result in self.send_pixiv_image(
                    event, illust, detail_message, show_details=self.show_details
                ):
                    yield result

        except Exception as e:
            logger.error(f"Pixiv 插件：获取用户作品时发生错误 - {e}")
            yield event.plain_result(f"获取用户作品时发生错误: {str(e)}")

    @command("pixiv_novel")
    async def pixiv_novel(self, event: AstrMessageEvent, tags: str):
        """处理 /pixiv_novel 命令，搜索 Pixiv 小说"""
        # 检查参数是否为空或为 help
        if not tags.strip() or tags.strip().lower() == "help":
            help_text = """# Pixiv 小说搜索

## 命令格式
`/pixiv_novel <标签1>,<标签2>,...`

## 参数说明
- `标签`: 搜索的标签，多个标签用英文逗号分隔

## 示例
- `/pixiv_novel 恋愛` - 搜索标签为"恋愛"的小说
- `/pixiv_novel 百合,GL` - 搜索同时包含"百合"和"GL"标签的小说
"""
            yield event.plain_result(help_text)
            return

        logger.info(f"Pixiv 插件：正在搜索小说 - 标签: {tags}")

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result(self.AUTH_ERROR_MSG)
            return

        try:
            # 调用 Pixiv API 搜索小说
            search_result = self.client.search_novel(
                tags, search_target="partial_match_for_tags"
            )
            initial_novels = search_result.novels if search_result.novels else []
            if not initial_novels:
                yield event.plain_result(f"未找到相关小说: {tags}")
                return

            # 统一用 filter_items 进行小说过滤和提示
            filtered_novels, filter_msgs = self.filter_items(
                initial_novels, f"小说:{tags}"
            )
            if self.show_filter_result:
                for msg in filter_msgs:
                    yield event.plain_result(msg)
            if not filtered_novels:
                return

            # 限制返回数量
            count_to_send = min(len(filtered_novels), self.return_count)
            novels_to_show = (
                random.sample(filtered_novels, count_to_send)
                if count_to_send > 0
                else []
            )

            # 返回结果
            if not novels_to_show:
                logger.info("没有符合条件的小说可供发送。")

            for novel in novels_to_show:
                # 统一使用build_detail_message生成详情信息
                detail_message = build_detail_message(novel, is_novel=True)
                yield event.plain_result(detail_message)

        except Exception as e:
            logger.error(f"Pixiv 插件：搜索小说时发生错误 - {e}")
            yield event.plain_result(f"搜索小说时发生错误: {str(e)}")

    @command("pixiv_trending_tags")
    async def pixiv_trending_tags(self, event: AstrMessageEvent):
        """获取 Pixiv 插画趋势标签"""
        logger.info("Pixiv 插件：正在获取插画趋势标签...")

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result(self.AUTH_ERROR_MSG)
            return

        try:
            # 调用 API 获取趋势标签
            result = self.client.trending_tags_illust(
                filter="for_ios"
            )  # 默认使用 for_ios, 也可以尝试 for_android

            if not result or not result.trend_tags:
                yield event.plain_result("未能获取到趋势标签，可能是 API 暂无数据。")
                return

            # 格式化标签信息
            tags_list = []
            for tag_info in result.trend_tags:
                tag_name = tag_info.get("tag", "未知标签")
                translated_name = tag_info.get("translated_name")
                if translated_name and translated_name != tag_name:
                    tags_list.append(f"- {tag_name} ({translated_name})")
                else:
                    tags_list.append(f"- {tag_name}")

            if not tags_list:
                yield event.plain_result("未能解析任何趋势标签。")
                return

            # 构建最终消息
            message = "# Pixiv 插画趋势标签\n\n"
            message += "\n".join(tags_list)

            yield event.plain_result(message)

        except Exception as e:
            logger.error(f"Pixiv 插件：获取趋势标签时发生错误 - {e}")
            yield event.plain_result(f"获取趋势标签时发生错误: {str(e)}")

    @command("pixiv_config")
    async def pixiv_config(
        self, event: AstrMessageEvent, arg1: str = "", arg2: str = ""
    ):
        """查看或动态设置 Pixiv 插件参数（除 refresh_token）。"""
        help_text = """# Pixiv 配置命令帮助

## 命令格式
/pixiv_config show
/pixiv_config <参数名>
/pixiv_config <参数名> <值>
/pixiv_config help

## 支持参数
- r18_mode: 过滤_R18, 允许_R18, 仅_R18
- ai_filter_mode: 显示_AI_作品, 过滤_AI_作品, 仅_AI_作品
- return_count: 1-10
- show_filter_result: true|false
- deep_search_depth: -1|0-50
- show_details: true|false
- forward_threshold: 1-20
- is_fromfilesystem: true|false
- refresh_token_interval_minutes: 0-10080

## 示例
- /pixiv_config show
- /pixiv_config r18_mode 仅_R18
- /pixiv_config show_filter_result false
"""
        args = []
        if arg1:
            args.append(arg1)
        if arg2:
            args.append(arg2)
        # 参数定义与校验规则
        schema = {
            "r18_mode": {"type": "enum", "choices": ["过滤 R18", "允许 R18", "仅 R18"]},
            "ai_filter_mode": {
                "type": "enum",
                "choices": ["显示 AI 作品", "过滤 AI 作品", "仅 AI 作品"],
            },
            "return_count": {"type": "int", "min": 1, "max": 30},
            "show_filter_result": {"type": "bool"},
            "show_details": {"type": "bool"},
            "deep_search_depth": {"type": "int", "min": -1, "max": 50},
            "forward_threshold": {"type": "int", "min": 1, "max": 20},
            "is_fromfilesystem": {"type": "bool"},
            "refresh_token_interval_minutes": {"type": "int", "min": 0, "max": 10080},
        }
        # 统一提前定义当前配置（全部走 self.config）
        current = {k: self.config.get(k) for k in schema.keys()}
        if not args or (args and args[0].strip().lower() == "help"):
            yield event.plain_result(help_text)
            return
        if args[0].strip().lower() == "show":
            msg = "# 当前 Pixiv 配置\n"
            for k, v in current.items():
                msg += f"{k}: {v}\n"
            yield event.plain_result(msg)
            return
        # 1参数：显示某项及可选项
        key = args[0]
        if key not in schema:
            yield event.plain_result(
                f"不支持的参数: {key}\n可用参数: {', '.join(schema.keys())}"
            )
            return
        if len(args) == 1:
            # 直接用 config 获取当前值
            msg = f"{key} 当前值: {self.config.get(key, '未设置')}\n"
            if schema[key]["type"] == "enum":
                msg += f"可选值: {', '.join(schema[key]['choices'])}"
            elif schema[key]["type"] == "bool":
                msg += "可选值: true, false"
            elif schema[key]["type"] == "int":
                minv, maxv = schema[key].get("min", None), schema[key].get("max", None)
                msg += f"可选范围: {minv} ~ {maxv}"
            yield event.plain_result(msg)
            return
        # 2参数：设置
        value = args[1]
        typ = schema[key]["type"]
        # 类型校验和转换
        try:
            if typ == "enum":
                value_normalized = value.replace("_", " ")
                choices_map = {c.replace(" ", "_"): c for c in schema[key]["choices"]}
                if value in choices_map:
                    value_normalized = choices_map[value]
                if value_normalized not in schema[key]["choices"]:
                    yield event.plain_result(
                        f"无效值: {value}\n可选值: {', '.join(schema[key]['choices'])}\n可用下划线代替空格，如: 允许_R18"
                    )
                    return
                self.config[key] = value_normalized
            elif typ == "bool":
                v = value.lower()
                if v in ("true", "1", "yes", "on"):
                    v = True
                elif v in ("false", "0", "no", "off"):
                    v = False
                else:
                    yield event.plain_result(
                        "布尔值仅支持: true/false/yes/no/on/off/1/0"
                    )
                    return
                self.config[key] = v
            elif typ == "int":
                v = int(value)
                minv, maxv = schema[key].get("min", None), schema[key].get("max", None)
                if (minv is not None and v < minv) or (maxv is not None and v > maxv):
                    yield event.plain_result(
                        f"超出范围: {v}，应在 {minv} ~ {maxv} 之间"
                    )
                    return
                self.config[key] = v
            self.config.save_config()
        except Exception as e:
            yield event.plain_result(f"设置失败: {e}")
            return
        yield event.plain_result(f"{key} 已更新为: {self.config[key]}")
        msg = "# 当前 Pixiv 配置\n"
        for k in schema.keys():
            msg += f"{k}: {self.config.get(k, '未设置')}\n"
        yield event.plain_result(msg)

    @command("pixiv_deepsearch")
    async def pixiv_deepsearch(self, event: AstrMessageEvent, tags: str):
        """
        深度搜索 Pixiv 插画，通过翻页获取多页结果
        用法: /pixiv_deepsearch <标签1>,<标签2>,...
        注意: 翻页深度由配置中的 deep_search_depth 参数控制
        """
        # 验证用户输入
        if not tags or tags.strip().lower() == "help":
            yield event.plain_result(
                "用法: /pixiv_deepsearch <标签1>,<标签2>,...\n"
                "深度搜索 Pixiv 插画，将遍历多个结果页面。\n"
                f"当前翻页深度设置: {self.deep_search_depth} 页 (-1 表示获取所有页面)"
            )
            return

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result(
                "Pixiv API 认证失败，请检查配置中的凭据信息。\n" + self.AUTH_ERROR_MSG
            )
            return

        # 获取翻页深度配置
        deep_search_depth = self.config.get("deep_search_depth", 3)

        # 处理标签
        tag_list = [tag.strip() for tag in tags.split(",") if tag.strip()]
        if not tag_list:
            yield event.plain_result("请提供至少一个有效的标签。")
            return

        # 日志记录
        tag_str = ", ".join(tag_list)
        logger.info(
            f"Pixiv 插件：正在深度搜索标签 - {tag_str}，翻页深度: {deep_search_depth}"
        )

        # 搜索前发送提示消息
        if deep_search_depth == -1:
            yield event.plain_result(
                f"正在深度搜索标签「{tag_str}」，将获取所有页面的结果，这可能需要一些时间..."
            )
        else:
            yield event.plain_result(
                f"正在深度搜索标签「{tag_str}」，将获取 {deep_search_depth} 页结果，这可能需要一些时间..."
            )

        try:
            # 准备搜索参数
            search_params = {
                "word": " ".join(tag_list),
                "search_target": "partial_match_for_tags",
                "sort": "popular_desc",
                "filter": "for_ios",
                "req_auth": True,
            }

            # 执行初始搜索
            all_illusts = []
            page_count = 0
            next_params = search_params.copy()

            # 循环获取多页结果
            while next_params:
                # 限制页数
                if deep_search_depth > 0 and page_count >= deep_search_depth:
                    break

                # 搜索当前页
                json_result = self.client.search_illust(**next_params)
                if not json_result or not hasattr(json_result, "illusts"):
                    break

                # 收集当前页的插画
                current_illusts = json_result.illusts
                if current_illusts:
                    all_illusts.extend(current_illusts)
                    page_count += 1
                    logger.info(
                        f"Pixiv 插件：已获取第 {page_count} 页，找到 {len(current_illusts)} 个插画"
                    )

                    # 发送进度更新
                    if page_count % 3 == 0:
                        yield event.plain_result(
                            f"搜索进行中：已获取 {page_count} 页，共 {len(all_illusts)} 个结果..."
                        )
                else:
                    break

                # 获取下一页参数
                next_url = json_result.next_url
                next_params = self.client.parse_qs(next_url) if next_url else None

                # 避免请求过于频繁
                if next_params:
                    await asyncio.sleep(0.5)  # 添加延迟，避免请求过快

            # 检查是否有结果
            if not all_illusts:
                yield event.plain_result(f"深度搜索未找到与「{tag_str}」相关的插画。")
                return

            # 记录找到的总数量
            initial_count = len(all_illusts)
            logger.info(
                f"Pixiv 插件：深度搜索完成，共找到 {initial_count} 个插画，开始过滤处理..."
            )
            yield event.plain_result(
                f"搜索完成！共获取 {page_count} 页，找到 {initial_count} 个结果，正在处理..."
            )

            filtered_illusts, filter_msgs = self.filter_items(all_illusts, tag_str)

            # 1. 无论是否有结果，都先发送过滤信息（如果配置了显示）
            if self.show_filter_result:
                for msg in filter_msgs:
                    yield event.plain_result(msg)

            # 2. 检查最终过滤后是否还有结果
            if not filtered_illusts:
                # 如果没有结果，发送明确的提示信息然后返回
                logger.info(
                    f"Pixiv 插件 (DeepSearch)：经过 R18/AI 过滤后，没有找到符合条件的作品 (标签: {tag_str})。"
                )
                yield event.plain_result(
                    f"在深度搜索和过滤后，未找到与「{tag_str}」相关且符合 R18/AI 过滤条件的作品。"
                )
                return  # 明确返回，不再执行后续发送逻辑

            # log记录
            logger.info(
                f"Pixiv 插件 (DeepSearch)：最终筛选出 {len(filtered_illusts)} 个作品准备发送 (标签: {tag_str})。"
            )

            # 打乱顺序，随机选择作品
            random.shuffle(filtered_illusts)
            count_to_send = min(len(filtered_illusts), self.return_count)
            # 使用切片获取要发送的插画列表
            illusts_to_send = filtered_illusts[:count_to_send]

            # 发送结果
            if not illusts_to_send:
                logger.info(
                    f"深度搜索后没有符合条件的插画可供发送 (可能是 return_count 设置为 0)。(标签: {tag_str})"
                )
                return

            threshold = self.config.get("forward_threshold", 5)
            if len(illusts_to_send) > threshold:
                async for result in self.send_forward_message(
                    event,
                    illusts_to_send,
                    lambda illust: build_detail_message(illust, is_novel=False),
                ):
                    yield result
            else:
                for illust in illusts_to_send:
                    detail_message = build_detail_message(illust, is_novel=False)
                    async for result in self.send_pixiv_image(
                        event, illust, detail_message, show_details=self.show_details
                    ):
                        yield result

        except Exception as e:
            logger.error(f"Pixiv 插件：深度搜索时发生错误 - {e}")
            yield event.plain_result(f"深度搜索时发生错误: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())

    @command("pixiv_and")
    async def pixiv_and(self, event: AstrMessageEvent, tags: str = ""):
        """处理 /pixiv_and 命令，进行 AND 逻辑深度搜索"""
        # 清理标签字符串
        cleaned_tags = tags.strip()

        if not cleaned_tags:
            logger.info(
                "Pixiv 插件 (AND)：用户未提供搜索标签或标签为空，返回帮助信息。"
            )
            yield event.plain_result(
                "请输入要进行 AND 搜索的标签 (用逗号分隔)。使用 `/pixiv_help` 查看帮助。\n\n**配置说明**:\n1. 先配置代理->[Astrbot代理配置教程](https://astrbot.app/config/astrbot-config.html#http-proxy);\n2. 再填入 `refresh_token`->**Pixiv Refresh Token**: 必填，用于 API 认证。获取方法请参考 [pixivpy3 文档](https://pypi.org/project/pixivpy3/) 或[这里](https://gist.github.com/karakoo/5e7e0b1f3cc74cbcb7fce1c778d3709e)。"
            )
            return

        # 分割标签
        tag_list = [tag.strip() for tag in cleaned_tags.split(",") if tag.strip()]
        if len(tag_list) < 2:
            yield event.plain_result(
                "AND 搜索至少需要两个标签，请用英文逗号 `,` 分隔。"
            )
            return

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result("Pixiv API 认证失败，请检查配置中的凭据信息。")
            return

        # 获取翻页深度配置
        deepth = self.deep_search_depth

        # 处理标签：使用 , 分隔，并分离第一个标签和其他标签
        tag_list_input = [tag.strip() for tag in cleaned_tags.split(",") if tag.strip()]
        if not tag_list_input:
            yield event.plain_result("请提供至少一个有效的标签。")
            return

        first_tag = tag_list_input[0]
        other_tags = tag_list_input[1:]

        # 构建用于显示/日志的标签字符串 (, 分隔)
        display_tag_str = ",".join(tag_list_input)

        logger.info(
            f"Pixiv 插件：正在进行 AND 深度搜索。策略：先用标签 '{first_tag}' 深度搜索 (翻页深度: {deepth})，然后本地过滤要求同时包含: {display_tag_str}"
        )

        # 搜索前发送提示消息
        search_phase_msg = f"正在深度搜索与标签「{first_tag}」相关的作品"
        filter_phase_msg = f"稍后将筛选出同时包含「{display_tag_str}」所有标签的结果。"
        page_limit_msg = (
            f"将获取 {deepth} 页结果" if deepth != -1 else "将获取所有页面的结果"
        )
        yield event.plain_result(
            f"{search_phase_msg}，{filter_phase_msg} {page_limit_msg}，这可能需要一些时间..."
        )

        try:
            all_illusts_from_first_tag = []
            page_count = 0
            next_params = {}

            while deepth == -1 or page_count < deepth:
                current_page_num = page_count + 1
                try:
                    if page_count == 0:
                        # 第一次搜索: 传入标签和搜索目标
                        logger.debug(
                            f"Pixiv API Call (Page 1): search_illust(word='{first_tag}', search_target='partial_match_for_tags')"
                        )
                        json_result = self.client.search_illust(
                            first_tag, search_target="partial_match_for_tags"
                        )
                    else:
                        # 后续翻页: 使用从 next_url 解析出的参数再次调用 search_illust
                        if not next_params:
                            logger.warning(
                                f"Pixiv 插件：尝试为 '{first_tag}' 翻页至第 {current_page_num} 页，但 next_params 为空，中止翻页。"
                            )
                            break
                        logger.debug(
                            f"Pixiv API Call (Page {current_page_num}): search_illust(**{next_params})"
                        )
                        json_result = self.client.search_illust(**next_params)

                    # 检查 API 返回结果是否有错误字段
                    if hasattr(json_result, "error") and json_result.error:
                        logger.error(
                            f"Pixiv API 返回错误 (页码 {current_page_num}): {json_result.error}"
                        )
                        yield event.plain_result(
                            f"搜索 '{first_tag}' 的第 {current_page_num} 页时 API 返回错误: {json_result.error.get('message', '未知错误')}"
                        )
                        break

                    # 处理有效结果
                    if json_result.illusts:
                        logger.info(
                            f"Pixiv 插件：AND 搜索 (阶段1: '{first_tag}') 第 {current_page_num} 页找到 {len(json_result.illusts)} 个插画。"
                        )
                        all_illusts_from_first_tag.extend(json_result.illusts)
                    else:
                        logger.info(
                            f"Pixiv 插件：AND 搜索 (阶段1: '{first_tag}') 第 {current_page_num} 页没有找到插画。"
                        )

                    # 获取下一页参数
                    if hasattr(json_result, "next_url") and json_result.next_url:
                        next_params = self.client.parse_qs(json_result.next_url)
                        page_count += 1
                    else:
                        logger.info(
                            f"Pixiv 插件：AND 搜索 (阶段1: '{first_tag}') 在第 {current_page_num} 页后没有获取到下一页链接或达到深度限制，API 搜索结束。"
                        )
                        break

                except Exception as api_e:
                    # 捕获更具体的 API 调用异常或属性访问异常
                    logger.error(
                        f"Pixiv 插件：调用 search_illust API 时出错 (基于 '{first_tag}', 页码 {current_page_num}) - {type(api_e).__name__}: {api_e}"
                    )
                    yield event.plain_result(
                        f"搜索 '{first_tag}' 的第 {current_page_num} 页时遇到 API 错误，搜索中止。"
                    )
                    import traceback

                    logger.error(traceback.format_exc())
                    break

            logger.info(
                f"Pixiv 插件：AND 搜索 (阶段1: '{first_tag}') 完成，共获取 {len(all_illusts_from_first_tag)} 个插画，现在开始本地 AND 过滤..."
            )

            # 本地 AND 过滤
            and_filtered_illusts = []
            if all_illusts_from_first_tag:
                required_other_tags_lower = {tag.lower() for tag in other_tags}
                for illust in all_illusts_from_first_tag:
                    illust_tags_lower = {tag.name.lower() for tag in illust.tags}
                    # 检查是否包含所有其他必需标签 (第一个标签已通过 API 搜索保证存在)
                    if required_other_tags_lower.issubset(illust_tags_lower):
                        and_filtered_illusts.append(illust)

            initial_count = len(and_filtered_illusts)
            logger.info(
                f"Pixiv 插件：本地 AND 过滤完成，找到 {initial_count} 个同时包含「{display_tag_str}」所有标签的作品。"
            )

            final_filtered_illusts, filter_msgs = self.filter_items(
                and_filtered_illusts, display_tag_str
            )

            # 1. 无论是否有结果，都先发送过滤信息
            if self.show_filter_result:
                for msg in filter_msgs:
                    yield event.plain_result(msg)

            # 2. 检查最终过滤后是否还有结果
            if not final_filtered_illusts:
                logger.info(
                    f"Pixiv 插件 (AND)：经过 R18/AI 过滤后，没有找到符合条件的作品 (标签: {display_tag_str})。"
                )
                yield event.plain_result(
                    f"在深度搜索和过滤后，未找到同时包含「{display_tag_str}」所有标签且符合 R18/AI 过滤条件的作品。"
                )
                return

            # log记录
            logger.info(
                f"Pixiv 插件 (AND)：最终筛选出 {len(final_filtered_illusts)} 个作品准备发送 (标签: {display_tag_str})。"
            )

            # 限制返回数量
            count_to_send = min(len(final_filtered_illusts), self.return_count)
            # 从最终结果中随机抽样
            illusts_to_send = random.sample(final_filtered_illusts, count_to_send)

            threshold = self.config.get("forward_threshold", 5)
            if len(illusts_to_send) > threshold:
                async for result in self.send_forward_message(
                    event,
                    illusts_to_send,
                    lambda illust: build_detail_message(illust, is_novel=False),
                ):
                    yield result
            else:
                for illust in illusts_to_send:
                    detail_message = build_detail_message(illust, is_novel=False)
                    async for result in self.send_pixiv_image(
                        event, illust, detail_message, show_details=self.show_details
                    ):
                        yield result

        except Exception as e:
            logger.error(f"Pixiv 插件：AND 深度搜索时发生未预料的错误 - {e}")
            yield event.plain_result(f"AND 深度搜索时发生错误: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())

    @command("pixiv_specific")
    async def pixiv_specific(self, event: AstrMessageEvent, illust_id: str = ""):
        """根据作品 ID 获取特定作品详情"""
        # 检查是否提供了作品 ID
        if not illust_id:
            yield event.plain_result(
                "请输入要查询的作品 ID。使用 `/pixiv_help` 查看帮助。"
            )
            return

        # 验证作品 ID 是否为数字
        if not illust_id.isdigit():
            yield event.plain_result("作品 ID 必须为数字。")
            return

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result("Pixiv API 认证失败，请检查配置中的凭据信息。")
            return

        # 调用 Pixiv API 获取作品详情
        try:
            logger.info(f"Pixiv 插件：正在获取作品详情 - ID: {illust_id}")
            illust_detail = self.client.illust_detail(illust_id)

            # 检查 illust_detail 和 illust 是否存在
            if (
                not illust_detail
                or not hasattr(illust_detail, "illust")
                or not illust_detail.illust
            ):
                yield event.plain_result("未找到该作品，请检查作品 ID 是否正确。")
                return

            illust = illust_detail.illust

            # 统一使用 filter_illusts_with_reason 进行过滤和提示
            filtered_illusts, filter_msgs = self.filter_items(
                [illust], f"ID:{illust_id}"
            )
            if self.show_filter_result:
                for msg in filter_msgs:
                    yield event.plain_result(msg)
            if not filtered_illusts:
                return

            # 统一使用build_detail_message生成详情信息
            detail_message = build_detail_message(filtered_illusts[0], is_novel=False)
            async for result in self.send_pixiv_image(
                event,
                filtered_illusts[0],
                detail_message,
                show_details=self.show_details,
            ):
                yield result

        except Exception as e:
            logger.error(f"Pixiv 插件：获取作品详情时发生错误 - {e}")
            yield event.plain_result(f"获取作品详情时发生错误: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())

    async def _periodic_token_refresh(self):
        """定期尝试使用 refresh_token 进行认证以保持其活性"""
        while True:
            try:
                # 先等待指定间隔
                wait_seconds = self.refresh_interval * 60
                logger.debug(
                    f"Pixiv Token 刷新任务：等待 {self.refresh_interval} 分钟 ({wait_seconds} 秒)..."
                )
                await asyncio.sleep(wait_seconds)

                # 检查 refresh_token 是否已配置
                current_refresh_token = self.config.get("refresh_token")
                if not current_refresh_token:
                    logger.warning(
                        "Pixiv Token 刷新任务：未配置 Refresh Token，跳过本次刷新。"
                    )
                    continue

                logger.info("Pixiv Token 刷新任务：尝试使用 Refresh Token 进行认证...")
                try:
                    self.client.auth(refresh_token=current_refresh_token)
                    logger.info("Pixiv Token 刷新任务：认证调用成功。")

                except PixivError as pe:
                    logger.error(
                        f"Pixiv Token 刷新任务：认证时发生 Pixiv API 错误 - {pe}"
                    )
                except Exception as e:
                    logger.error(
                        f"Pixiv Token 刷新任务：认证时发生未知错误 - {type(e).__name__}: {e}"
                    )
                    import traceback

                    logger.error(traceback.format_exc())

            except asyncio.CancelledError:
                logger.info("Pixiv Token 刷新任务：任务被取消，停止刷新。")
                break
            except Exception as loop_e:
                logger.error(
                    f"Pixiv Token 刷新任务：循环中发生意外错误 - {loop_e}，将在下次间隔后重试。"
                )
                import traceback

                logger.error(traceback.format_exc())

    async def terminate(self):
        """插件终止时调用的清理函数"""
        logger.info("Pixiv 搜索插件正在停用...")
        # 取消后台刷新任务
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
            try:
                # 等待任务实际取消
                await self._refresh_task
            except asyncio.CancelledError:
                logger.info("Pixiv Token 刷新任务已成功取消。")
            except Exception as e:
                logger.error(f"等待 Pixiv Token 刷新任务取消时发生错误: {e}")
        logger.info("Pixiv 搜索插件已停用。")
        pass
