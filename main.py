import asyncio
from typing import Dict, Any
import aiohttp
import hashlib
import io
import base64
from pathlib import Path
from fpdf import FPDF

from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.api import logger
from astrbot.api.message_components import File
from astrbot.api.all import command
from pixivpy3 import AppPixivAPI, PixivError

from .utils.tag import build_detail_message, FilterConfig, validate_and_process_tags, process_and_send_illusts, sample_illusts
from .utils.database import initialize_database, add_subscription, remove_subscription, list_subscriptions
from .utils.subscription import SubscriptionService
from .utils.pixiv_utils import init_pixiv_utils, filter_items, send_pixiv_image, send_forward_message
from .utils.help import init_help_manager, get_help_message

@register(
    "pixiv_search",
    "vmoranv",
    "Pixiv 图片搜索",
    "1.4.0",
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

        # 初始化配置管理器
        from .utils.config import PixivConfig, PixivConfigManager
        self.pixiv_config = PixivConfig(self.config)
        self.config_manager = PixivConfigManager(self.pixiv_config)
        
        # 初始化其他依赖配置的属性
        self.client = AppPixivAPI(**self.pixiv_config.get_requests_kwargs())
        self._refresh_task: asyncio.Task = None
        self._http_session = None
        self.sub_service = None
        
        # 使用 StarTools 获取标准数据目录
        data_dir = StarTools.get_data_dir("pixiv_search")
        self.temp_dir = data_dir / "temp"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化 PixivUtils 模块
        init_pixiv_utils(self.client, self.pixiv_config, self.temp_dir)

        # 字体相关初始化
        # 使用项目相对路径下的字体文件
        self.font_path = Path(__file__).parent / "data" / "SmileySans-Oblique.ttf"
        
        # 初始化帮助消息管理器
        init_help_manager(data_dir)
        
        
        # 初始化数据库
        initialize_database()

        # 记录初始化信息
        logger.info(f"Pixiv 插件配置加载：{self.pixiv_config.get_config_info()}")

        # 启动后台刷新任务
        if self.pixiv_config.refresh_interval > 0:
            self._refresh_task = asyncio.create_task(self._periodic_token_refresh())
            logger.info(
                f"Pixiv 插件：已启动 Refresh Token 自动刷新任务，间隔 {self.pixiv_config.refresh_interval} 分钟。"
            )
        else:
            logger.info("Pixiv 插件：Refresh Token 自动刷新已禁用。")

        # 启动订阅服务
        if self.pixiv_config.subscription_enabled:
            self.sub_service = SubscriptionService(self)
            self.sub_service.start()
        else:
            logger.info("Pixiv 插件：订阅功能已禁用。")

    @staticmethod
    def info() -> Dict[str, Any]:
        """返回插件元数据"""
        return {
            "name": "pixiv_search",
            "author": "vmoranv",
            "description": "Pixiv 图片搜索",
            "version": "1.4.0",
            "homepage": "https://github.com/vmoranv/astrbot_plugin_pixiv_search",
        }

    async def _authenticate(self) -> bool:
        """尝试使用配置的凭据进行 Pixiv API 认证"""
        # 每次调用都尝试认证，让 pixivpy3 处理 token 状态
        try:
            if self.pixiv_config.refresh_token:
                # 调用 auth()，pixivpy3 会在需要时刷新 token
                await asyncio.to_thread(self.client.auth, refresh_token=self.pixiv_config.refresh_token)
                return True
            else:
                logger.error("Pixiv 插件：未提供有效的 Refresh Token，无法进行认证。")
                return False

        except Exception as e:
            logger.error(
                f"Pixiv 插件：认证/刷新时发生错误 - 异常类型: {type(e)}, 错误信息: {e}"
            )
            return False

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
                "请输入要搜索的标签。使用 `/pixiv_help` 查看帮助。\n" + self.pixiv_config.get_auth_error_message()
            )
            return

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result(self.pixiv_config.get_auth_error_message())
            return

        # 使用统一的标签处理函数
        tag_result = validate_and_process_tags(cleaned_tags)
        if not tag_result['success']:
            yield event.plain_result(tag_result['error_message'])
            return
        
        exclude_tags = tag_result['exclude_tags']
        search_tags = tag_result['search_tags']
        display_tags = tag_result['display_tags']

        # 标签搜索处理
        logger.info(f"Pixiv 插件：正在搜索标签 - {search_tags}，排除标签 - {exclude_tags}")
        try:
            # 包装同步搜索调用
            search_result = await asyncio.to_thread(
                self.client.search_illust,
                search_tags, 
                search_target="partial_match_for_tags"
            )
            initial_illusts = search_result.illusts if search_result.illusts else []

            if not initial_illusts:
                yield event.plain_result("未找到相关插画。")
                return

            # 使用统一的作品处理和发送函数
            config = FilterConfig(
                r18_mode=self.pixiv_config.r18_mode,
                ai_filter_mode=self.pixiv_config.ai_filter_mode,
                display_tag_str=display_tags,
                return_count=self.pixiv_config.return_count,
                logger=logger,
                show_filter_result=self.pixiv_config.show_filter_result,
                excluded_tags=exclude_tags or [],
                forward_threshold=self.pixiv_config.forward_threshold,
                show_details=self.pixiv_config.show_details
            )
            
            async for result in process_and_send_illusts(
                initial_illusts,  # 传入所有初始作品，让process_and_send_illusts内部处理过滤和选择
                config,
                self.client,
                event,
                build_detail_message,
                send_pixiv_image,
                send_forward_message,
                is_novel=False
            ):
                yield result

        except Exception as e:
            logger.error(f"Pixiv 插件：搜索插画时发生错误 - {e}")
            yield event.plain_result(f"搜索插画时发生错误: {str(e)}")

    @command("pixiv_subscribe_add")
    async def pixiv_subscribe_add(self, event: AstrMessageEvent, artist_id: str = ""):
        """订阅画师"""
        if not self.pixiv_config.subscription_enabled:
            yield event.plain_result("订阅功能未启用。")
            return

        if not artist_id or not artist_id.isdigit():
            yield event.plain_result("请输入有效的画师ID。用法: /pixiv_subscribe_add <画师ID>")
            return

        platform_name = event.platform_meta.name
        message_type = event.get_message_type().value
        session_id = f"{platform_name}:{message_type}:{event.get_group_id() or event.get_sender_id()}"

        sub_type = 'artist'
        target_name = artist_id
        
        try:
            if not await self._authenticate():
                yield event.plain_result(self.pixiv_config.get_auth_error_message())
                return
            
            # 获取画师信息
            user_detail = await asyncio.to_thread(self.client.user_detail, int(artist_id))
            if user_detail and user_detail.user:
                target_name = user_detail.user.name
            
            # 获取画师最新作品ID作为初始值
            latest_illust_id = 0
            try:
                user_illusts = await asyncio.to_thread(self.client.user_illusts, int(artist_id))
                if user_illusts and user_illusts.illusts:
                    latest_illust_id = user_illusts.illusts[0].id
                    logger.info(f"获取到画师 {artist_id} 的最新作品ID: {latest_illust_id}")
            except Exception as e:
                logger.warning(f"获取画师 {artist_id} 最新作品ID失败: {e}，将使用默认值 0")
                
        except Exception as e:
            logger.error(f"获取画师 {artist_id} 信息失败: {e}")
            yield event.plain_result(f"无法获取画师ID {artist_id} 的信息，但仍会使用该ID进行订阅。")

        success, message = add_subscription(event.get_group_id() or event.get_sender_id(), 
                                            session_id, 
                                            sub_type, 
                                            artist_id, 
                                            target_name,
                                            latest_illust_id)
        yield event.plain_result(message)
    @command("pixiv_subscribe_remove")
    async def pixiv_subscribe_remove(self, event: AstrMessageEvent, artist_id: str = ""):
        """取消订阅画师"""
        if not self.pixiv_config.subscription_enabled:
            yield event.plain_result("订阅功能未启用。")
            return

        if not artist_id or not artist_id.isdigit():
            yield event.plain_result("请输入有效的画师ID。用法: /pixiv_subscribe_remove <画师ID>")
            return

        chat_id = event.get_group_id() or event.get_sender_id()
        sub_type = 'artist'
        
        success, message = remove_subscription(chat_id, sub_type, artist_id)
        yield event.plain_result(message)

    @command("pixiv_subscribe_list")
    async def pixiv_subscribe_list(self, event: AstrMessageEvent):
        """查看当前订阅列表"""
        if not self.pixiv_config.subscription_enabled:
            yield event.plain_result("订阅功能未启用。")
            return

        chat_id = event.get_group_id() or event.get_sender_id()
        subs = list_subscriptions(chat_id)
        
        if not subs:
            yield event.plain_result("您还没有任何订阅。")
            return
        
        msg = "您的订阅列表：\n"
        for sub in subs:
            msg += f"- [画师] {sub.target_name} ({sub.target_id})\n"
        yield event.plain_result(msg)

    @command("pixiv_help")
    async def pixiv_help(self, event: AstrMessageEvent):
        """生成并返回帮助信息"""

        help_text = get_help_message("pixiv_help", "帮助消息加载失败，请检查配置文件。")
        yield event.plain_result(help_text)

    @command("pixiv_recommended")
    async def pixiv_recommended(self, event: AstrMessageEvent, args: str = ""):
        """获取 Pixiv 推荐作品"""

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result(self.pixiv_config.get_auth_error_message())
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

            # 使用统一的作品处理和发送函数
            config = FilterConfig(
                r18_mode=self.pixiv_config.r18_mode,
                ai_filter_mode=self.pixiv_config.ai_filter_mode,
                display_tag_str="推荐",
                return_count=self.pixiv_config.return_count,
                logger=logger,
                show_filter_result=self.pixiv_config.show_filter_result,
                excluded_tags=[],
                forward_threshold=self.pixiv_config.forward_threshold,
                show_details=self.pixiv_config.show_details
            )
            
            async for result in process_and_send_illusts(
                initial_illusts,
                config,
                self.client,
                event,
                build_detail_message,
                send_pixiv_image,
                send_forward_message,
                is_novel=False
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
            help_text = get_help_message("pixiv_ranking", "排行榜帮助消息加载失败，请检查配置文件。")
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
                if len(year) != 4 or len(month) != 2 or len(day) != 2:
                    raise ValueError("日期格式不正确")
            except Exception:
                yield event.plain_result(
                    f"无效的日期格式: {date}\n日期应为 YYYY-MM-DD 格式"
                )
                return

        # 检查 R18 权限
        if "r18" in mode and self.pixiv_config.r18_mode == "过滤 R18":
            yield event.plain_result(
                "当前 R18 模式设置为「过滤 R18」，无法使用 R18 相关排行榜。"
            )
            return

        logger.info(
            f"Pixiv 插件：正在获取排行榜 - 模式: {mode}, 日期: {date if date else '最新'}"
        )

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result(self.pixiv_config.get_auth_error_message())
            return

        try:
            # 调用 Pixiv API 获取排行榜
            ranking_result = self.client.illust_ranking(mode=mode, date=date)
            initial_illusts = ranking_result.illusts if ranking_result.illusts else []

            if not initial_illusts:
                yield event.plain_result(f"未能获取到 {date} 的 {mode} 排行榜数据。")
                return

            # 使用统一的作品处理和发送函数
            config = FilterConfig(
                r18_mode=self.pixiv_config.r18_mode,
                ai_filter_mode=self.pixiv_config.ai_filter_mode,
                display_tag_str=f"排行榜:{mode}",
                return_count=self.pixiv_config.return_count,
                logger=logger,
                show_filter_result=self.pixiv_config.show_filter_result,
                excluded_tags=[],
                forward_threshold=self.pixiv_config.forward_threshold,
                show_details=self.pixiv_config.show_details
            )
            
            async for result in process_and_send_illusts(
                initial_illusts,  # 传入所有初始作品，让process_and_send_illusts内部处理过滤和选择
                config,
                self.client,
                event,
                build_detail_message,
                send_pixiv_image,
                send_forward_message,
                is_novel=False
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
            help_text = get_help_message("pixiv_related", "相关作品帮助消息加载失败，请检查配置文件。")
            yield event.plain_result(help_text)
            return

        # 验证作品ID是否为数字
        if not illust_id.isdigit():
            yield event.plain_result(f"作品ID必须是数字: {illust_id}")
            return

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result(self.pixiv_config.get_auth_error_message())
            return

        logger.info(f"Pixiv 插件：获取相关作品 - ID: {illust_id}")
        try:
            # 调用 API 获取相关作品
            related_result = self.client.illust_related(int(illust_id))
            initial_illusts = related_result.illusts if related_result.illusts else []

            if not initial_illusts:
                yield event.plain_result(f"未能找到与作品 ID {illust_id} 相关的作品。")
                return

            # 使用统一的作品处理和发送函数
            config = FilterConfig(
                r18_mode=self.pixiv_config.r18_mode,
                ai_filter_mode=self.pixiv_config.ai_filter_mode,
                display_tag_str=f"相关:{illust_id}",
                return_count=self.pixiv_config.return_count,
                logger=logger,
                show_filter_result=self.pixiv_config.show_filter_result,
                excluded_tags=[],
                forward_threshold=self.pixiv_config.forward_threshold,
                show_details=self.pixiv_config.show_details
            )
            
            async for result in process_and_send_illusts(
                initial_illusts,  # 传入所有初始作品，让process_and_send_illusts内部处理过滤和选择
                config,
                self.client,
                event,
                build_detail_message,
                send_pixiv_image,
                send_forward_message,
                is_novel=False
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
            help_text = get_help_message("pixiv_user_search", "用户搜索帮助消息加载失败，请检查配置文件。")
            yield event.plain_result(help_text)
            return

        logger.info(f"Pixiv 插件：正在搜索用户 - {username}")

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result(self.pixiv_config.get_auth_error_message())
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
            config = FilterConfig(
                r18_mode=self.pixiv_config.r18_mode,
                ai_filter_mode=self.pixiv_config.ai_filter_mode,
                display_tag_str=f"用户:{user.name}",
                return_count=self.pixiv_config.return_count,
                logger=logger,
                show_filter_result=self.pixiv_config.show_filter_result,
                excluded_tags=[]
            )
            filtered_illusts, filter_msgs = filter_items(illusts, config)
            if self.pixiv_config.show_filter_result:
                for msg in filter_msgs:
                    yield event.plain_result(msg)

            # 始终显示用户基本信息
            yield event.plain_result(user_info)

            # 如果有合规插画，发送第一张插画
            if filtered_illusts:
                illust = filtered_illusts[0]
                detail_message = build_detail_message(illust, is_novel=False)
                async for result in send_pixiv_image(
                    self.client, event, illust, detail_message, show_details=self.pixiv_config.show_details
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
            help_text = get_help_message("pixiv_user_detail", "用户详情帮助消息加载失败，请检查配置文件。")
            yield event.plain_result(help_text)
            return

        logger.info(f"Pixiv 插件：正在获取用户详情 - ID: {user_id}")

        # 验证用户ID是否为数字
        if not user_id.isdigit():
            yield event.plain_result(f"用户ID必须是数字: {user_id}")
            return

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result(self.pixiv_config.get_auth_error_message())
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
            help_text = get_help_message("pixiv_user_illusts", "用户作品帮助消息加载失败，请检查配置文件。")
            yield event.plain_result(help_text)
            return

        logger.info(f"Pixiv 插件：正在获取用户作品 - ID: {user_id}")

        # 验证用户ID是否为数字
        if not user_id.isdigit():
            yield event.plain_result(f"用户ID必须是数字: {user_id}")
            return

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result(self.pixiv_config.get_auth_error_message())
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

            # 使用统一的作品处理和发送函数
            config = FilterConfig(
                r18_mode=self.pixiv_config.r18_mode,
                ai_filter_mode=self.pixiv_config.ai_filter_mode,
                display_tag_str=f"用户:{user_name}",
                return_count=self.pixiv_config.return_count,
                logger=logger,
                show_filter_result=self.pixiv_config.show_filter_result,
                excluded_tags=[],
                forward_threshold=self.pixiv_config.forward_threshold,
                show_details=self.pixiv_config.show_details
            )
            
            async for result in process_and_send_illusts(
                initial_illusts,  # 传入所有初始作品，让process_and_send_illusts内部处理过滤和选择
                config,
                self.client,
                event,
                build_detail_message,
                send_pixiv_image,
                send_forward_message,
                is_novel=False
            ):
                yield result

        except Exception as e:
            logger.error(f"Pixiv 插件：获取用户作品时发生错误 - {e}")
            yield event.plain_result(f"获取用户作品时发生错误: {str(e)}")

    @command("pixiv_novel")
    async def pixiv_novel(self, event: AstrMessageEvent, tags: str = ""):
        """处理 /pixiv_novel 命令，搜索 Pixiv 小说"""
        cleaned_tags = tags.strip()

        # Handle help and empty cases
        if not cleaned_tags or cleaned_tags.lower() == "help":
            help_text = get_help_message("pixiv_novel", "小说搜索帮助消息加载失败，请检查配置文件。")
            yield event.plain_result(help_text)
            return

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result(self.pixiv_config.get_auth_error_message())
            return

        # 使用统一的标签处理函数
        tag_result = validate_and_process_tags(cleaned_tags)
        if not tag_result['success']:
            yield event.plain_result(tag_result['error_message'])
            return
        
        exclude_tags = tag_result['exclude_tags']
        search_tags = tag_result['search_tags']
        display_tags = tag_result['display_tags']

        logger.info(
            f"Pixiv 插件：正在搜索小说 - 标签: {search_tags}，排除标签: {exclude_tags}"
        )

        try:
            # 调用 Pixiv API 搜索小说
            search_result = self.client.search_novel(
                search_tags, search_target="partial_match_for_tags"
            )
            initial_novels = search_result.novels if search_result.novels else []
            if not initial_novels:
                yield event.plain_result(f"未找到相关小说: {search_tags}")
                return

            # 使用统一的作品处理和发送函数
            config = FilterConfig(
                r18_mode=self.pixiv_config.r18_mode,
                ai_filter_mode=self.pixiv_config.ai_filter_mode,
                display_tag_str=display_tags,
                return_count=self.pixiv_config.return_count,
                logger=logger,
                show_filter_result=self.pixiv_config.show_filter_result,
                excluded_tags=exclude_tags or [],
                forward_threshold=self.pixiv_config.forward_threshold,
                show_details=self.pixiv_config.show_details
            )
            
            async for result in process_and_send_illusts(
                initial_novels,  # 传入所有初始小说，让process_and_send_illusts内部处理过滤和选择
                config,
                self.client,
                event,
                build_detail_message,
                send_pixiv_image,
                send_forward_message,
                is_novel=True
            ):
                yield result

        except Exception as e:
            logger.error(f"Pixiv 插件：搜索小说时发生错误 - {e}")
            yield event.plain_result(f"搜索小说时发生错误: {str(e)}")

    def create_pdf_from_text(self, title: str, text: str) -> bytes:
        """使用 fpdf2 将文本转换为 PDF 字节流"""
        if not self.font_path.exists():
            logger.error(f"字体文件不存在，无法创建PDF: {self.font_path}")
            raise FileNotFoundError(f"字体文件不存在: {self.font_path}")

        pdf = FPDF()
        pdf.add_page()

        # 添加并使用我们自己下载的字体
        pdf.add_font("SmileySans", "", str(self.font_path), uni=True)
        pdf.set_font("SmileySans", size=20)

        # 添加标题
        pdf.multi_cell(0, 10, title, align="C")
        pdf.ln(10)

        # 设置正文样式
        pdf.set_font_size(12)
        
        # 添加正文
        pdf.multi_cell(0, 10, text)

        # 返回 PDF 内容的字节
        # pdf.output() with a unicode font returns a bytearray, which is what we need.
        return pdf.output(dest='S')

    @command("pixiv_novel_download")
    async def pixiv_novel_download(self, event: AstrMessageEvent, novel_id: str = ""):
        """根据ID下载Pixiv小说为pdf文件"""
        cleaned_id = novel_id.strip()
        if not cleaned_id or not cleaned_id.isdigit():
            yield event.plain_result("请输入有效的小说ID。用法: /pixiv_novel_download <小说ID>")
            return

        if not await self._authenticate():
            yield event.plain_result(self.pixiv_config.get_auth_error_message())
            return

        logger.info(f"Pixiv 插件：正在准备下载小说并转换为PDF - ID: {cleaned_id}")

        try:

            # 获取小说详情和内容
            novel_detail_result = await asyncio.to_thread(self.client.novel_detail, cleaned_id)
            if not novel_detail_result or not novel_detail_result.novel:
                yield event.plain_result(f"未找到ID为 {cleaned_id} 的小说。")
                return
            novel_title = novel_detail_result.novel.title

            novel_content_result = await asyncio.to_thread(self.client.webview_novel, cleaned_id)
            if not novel_content_result or not hasattr(novel_content_result, "text"):
                yield event.plain_result(f"无法获取ID为 {cleaned_id} 的小说内容。")
                return
            novel_text = novel_content_result.text

            # 生成 PDF 字节流
            pdf_bytes = self.create_pdf_from_text(novel_title, novel_text)
            logger.info("Pixiv 插件：小说内容已成功转换为 PDF 字节流。")

            # 清理文件名
            safe_title = "".join(c for c in novel_title if c.isalnum() or c in (" ", "_")).rstrip()
            if not safe_title:
                safe_title = "novel"
            file_name = f"{safe_title}_{cleaned_id}.pdf"

            # --- PDF 内存加密逻辑 ---
            password = hashlib.md5(cleaned_id.encode()).hexdigest()
            final_pdf_bytes = None
            password_notice = ""
            
            try:
                from PyPDF2 import PdfReader, PdfWriter

                reader = PdfReader(io.BytesIO(pdf_bytes))
                writer = PdfWriter()
                for page in reader.pages:
                    writer.add_page(page)
                writer.encrypt(password)
                
                # Use an in-memory stream to hold the encrypted PDF
                with io.BytesIO() as bytes_stream:
                    writer.write(bytes_stream)
                    final_pdf_bytes = bytes_stream.getvalue()
                
                logger.info("Pixiv 插件：PDF 已成功在内存中加密。")
                password_notice = f"PDF已加密，密码为小说ID的MD5值: {password}"

            except ImportError:
                logger.warning("PyPDF2 未安装，无法加密PDF。将发送未加密的文件。")
                final_pdf_bytes = pdf_bytes  # Fallback to unencrypted
                password_notice = "【注意】PyPDF2库未安装，本次发送的PDF未加密。"

            # 将文件内容编码为 Base64 URI
            file_base64 = base64.b64encode(final_pdf_bytes).decode('utf-8')
            base64_uri = f"base64://{file_base64}"
            
            logger.info("Pixiv 插件：PDF 内容已编码为 Base64，准备发送。")

            # --- 文件发送逻辑 ---
            # 检查平台并发送文件
            if event.get_platform_name() == "aiocqhttp" and event.get_group_id():
                from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
                if isinstance(event, AiocqhttpMessageEvent):
                    client = event.bot
                    group_id = event.get_group_id()
                    try:
                        logger.info(f"Pixiv 插件：使用 aiocqhttp API (Base64) 上传群文件 {file_name} 到群组 {group_id}")
                        await client.upload_group_file(group_id=group_id, file=base64_uri, name=file_name)
                        logger.info("Pixiv 插件：成功调用 aiocqhttp API (Base64) 发送PDF。")
                        # 发送密码提示
                        if password_notice:
                            yield event.plain_result(password_notice)
                        return
                    except Exception as api_e:
                        logger.error(f"Pixiv 插件：调用 aiocqhttp API (Base64) 发送文件失败: {api_e}")
                        yield event.plain_result(f"通过高速接口发送文件失败: {api_e}。请联系管理员检查后端配置。")
                        return

            logger.info("非 aiocqhttp 平台或私聊，尝试使用标准 File 组件 (Base64) 发送。")
            yield event.chain_result([File(name=file_name, file=base64_uri)])
            if password_notice:
                yield event.plain_result(password_notice)

        except FileNotFoundError as e:
            logger.error(f"无法生成PDF: {e}")
            yield event.plain_result("无法生成PDF：所需的中文字体文件下载失败或不存在。请检查网络连接或联系管理员。")
        except Exception as e:
            logger.error(f"Pixiv 插件：下载或转换小说为PDF时发生错误 - {e}")
            yield event.plain_result(f"处理小说时发生错误: {str(e)}")

    @command("pixiv_trending_tags")
    async def pixiv_trending_tags(self, event: AstrMessageEvent):
        """获取 Pixiv 插画趋势标签"""
        logger.info("Pixiv 插件：正在获取插画趋势标签...")

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result(self.pixiv_config.get_auth_error_message())
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
        # 使用配置管理器处理命令
        result = await self.config_manager.handle_config_command(event, arg1, arg2)
        if result:
            yield event.plain_result(result)

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
                "支持排除标签功能，使用 -<标签> 来排除特定标签。\n"
                f"当前翻页深度设置: {self.pixiv_config.deep_search_depth} 页 (-1 表示获取所有页面)"
            )
            return

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result(
                "Pixiv API 认证失败，请检查配置中的凭据信息。\n" + self.pixiv_config.get_auth_error_message()
            )
            return

        # 使用统一的标签处理函数
        tag_result = validate_and_process_tags(tags.strip())
        if not tag_result['success']:
            yield event.plain_result(tag_result['error_message'])
            return
        
        include_tags = tag_result['include_tags']
        exclude_tags = tag_result['exclude_tags']
        search_tags_list = include_tags
        display_tags = tag_result['display_tags']
        deep_search_depth = self.pixiv_config.deep_search_depth

        # 日志记录
        tag_str = ", ".join(search_tags_list)
        logger.info(
            f"Pixiv 插件：正在深度搜索标签 - {tag_str}，排除标签 - {exclude_tags}，翻页深度: {deep_search_depth}"
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
                "word": " ".join(search_tags_list),
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

            # 使用统一的作品处理和发送函数
            config = FilterConfig(
                r18_mode=self.pixiv_config.r18_mode,
                ai_filter_mode=self.pixiv_config.ai_filter_mode,
                display_tag_str=display_tags,
                return_count=self.pixiv_config.return_count,
                logger=logger,
                show_filter_result=self.pixiv_config.show_filter_result,
                excluded_tags=exclude_tags or [],
                forward_threshold=self.pixiv_config.forward_threshold,
                show_details=self.pixiv_config.show_details
            )
            
            async for result in process_and_send_illusts(
                all_illusts,  # 传入所有初始作品，让process_and_send_illusts内部处理过滤和选择
                config,
                self.client,
                event,
                build_detail_message,
                send_pixiv_image,
                send_forward_message,
                is_novel=False
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
                "请输入要进行 AND 搜索的标签 (用逗号分隔)。使用 `/pixiv_help` 查看帮助。\n"
                "支持排除标签功能，使用 -<标签> 来排除特定标签。\n\n"
                "**配置说明**:\n1. 先配置代理->[Astrbot代理配置教程](https://astrbot.app/config/astrbot-config.html#http-proxy);\n2. 再填入 `refresh_token`->**Pixiv Refresh Token**: 必填，用于 API 认证。获取方法请参考 [pixivpy3 文档](https://pypi.org/project/pixivpy3/) 或[这里](https://gist.github.com/karakoo/5e7e0b1f3cc74cbcb7fce1c778d3709e)。"
            )
            return

        # 使用统一的标签处理函数
        tag_result = validate_and_process_tags(cleaned_tags)
        if not tag_result['success']:
            yield event.plain_result(tag_result['error_message'])
            return

        include_tags = tag_result['include_tags']
        exclude_tags = tag_result['exclude_tags']
        display_tag_str = tag_result['display_tags']

        # AND 搜索至少需要两个包含标签
        if len(include_tags) < 2:
            yield event.plain_result(
                "AND 搜索至少需要两个包含标签，请用英文逗号 `,` 分隔。"
            )
            return

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result(self.pixiv_config.get_auth_error_message())
            return

        # 获取翻页深度配置
        deepth = self.pixiv_config.deep_search_depth

        # 处理标签：分离第一个标签和其他标签
        first_tag = include_tags[0]
        other_tags = include_tags[1:]

        logger.info(
            f"Pixiv 插件：正在进行 AND 深度搜索。策略：先用标签 '{first_tag}' 深度搜索 (翻页深度: {deepth})，然后本地过滤要求同时包含: {','.join(include_tags)}，排除标签: {exclude_tags}"
        )

        # 搜索前发送提示消息
        search_phase_msg = f"正在深度搜索与标签「{first_tag}」相关的作品"
        filter_phase_msg = f"稍后将筛选出同时包含「{','.join(include_tags)}」所有标签的结果。"
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
                f"Pixiv 插件：本地 AND 过滤完成，找到 {initial_count} 个同时包含「{','.join(include_tags)}」所有标签的作品。"
            )

            # 使用统一的作品处理和发送函数
            config = FilterConfig(
                r18_mode=self.pixiv_config.r18_mode,
                ai_filter_mode=self.pixiv_config.ai_filter_mode,
                display_tag_str=display_tag_str,
                return_count=self.pixiv_config.return_count,
                logger=logger,
                show_filter_result=self.pixiv_config.show_filter_result,
                excluded_tags=exclude_tags or [],
                forward_threshold=self.pixiv_config.forward_threshold,
                show_details=self.pixiv_config.show_details
            )
            
            async for result in process_and_send_illusts(
                and_filtered_illusts,  # 传入所有过滤后的作品，让process_and_send_illusts内部处理选择
                config,
                self.client,
                event,
                build_detail_message,
                send_pixiv_image,
                send_forward_message,
                is_novel=False
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
            yield event.plain_result(self.pixiv_config.get_auth_error_message())
            return

        # 调用 Pixiv API 获取作品详情
        try:
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
            config = FilterConfig(
                r18_mode=self.pixiv_config.r18_mode,    
                ai_filter_mode=self.pixiv_config.ai_filter_mode,
                display_tag_str=f"ID:{illust_id}",
                return_count=self.pixiv_config.return_count,
                logger=logger,
                show_filter_result=self.pixiv_config.show_filter_result,
                excluded_tags=[]
            )
            filtered_illusts, filter_msgs = filter_items([illust], config)
            if self.pixiv_config.show_filter_result:
                for msg in filter_msgs:
                    yield event.plain_result(msg)
            if not filtered_illusts:
                return

            # 统一使用build_detail_message生成详情信息
            detail_message = build_detail_message(filtered_illusts[0], is_novel=False)
            async for result in send_pixiv_image(
                self.client,
                event,
                filtered_illusts[0],
                detail_message,
                show_details=self.pixiv_config.show_details,
                send_all_pages=True,  # Send all pages for specific illust
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
                wait_seconds = self.pixiv_config.refresh_interval * 60
                logger.debug(
                    f"Pixiv Token 刷新任务：等待 {self.pixiv_config.refresh_interval} 分钟 ({wait_seconds} 秒)..."
                )
                await asyncio.sleep(wait_seconds)

                # 检查 refresh_token 是否已配置
                current_refresh_token = self.pixiv_config.refresh_token
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
        # 停止订阅服务
        if self.sub_service:
            self.sub_service.stop()
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
        # 关闭HTTP会话
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()


    async def _get_http_session(self):
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session
