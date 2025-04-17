import asyncio
import random
from pathlib import Path
from typing import Optional, List, Dict, Any 
import aiohttp 

# AstrBot 核心库导入
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger  # 导入全局 logger
import astrbot.api.message_components as Comp
from astrbot.api.all import command  # 导入 command 装饰器

# 尝试导入 pixivpy 库
try:
    from pixivpy3 import AppPixivAPI
except ImportError:
    logger.error("Pixiv 插件依赖库 'pixivpy' 未安装。请确保 requirements.txt 文件存在且内容正确，然后重载插件或重启 AstrBot。")
    raise ImportError("pixivpy not found, please install it.")

@register(
    "pixiv_search",
    "vmoranv",
    "Pixiv 图片搜索",
    "1.0.3",
    "https://github.com/vmoranv/astrbot_plugin_pixiv_search"
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
        super().__init__(context)  # 调用父类的初始化方法
        self.config = config
        self.client = AppPixivAPI()  # 移除 client_id 和 client_secret
        self.authenticated = False
        self.refresh_token = self.config.get("refresh_token", None)
        self.return_count = self.config.get("return_count", 1)
        self.r18_mode = self.config.get("r18_mode", "过滤 R18")
        self.ai_filter_mode = self.config.get("ai_filter_mode", "显示 AI 作品") # 新增读取 AI 过滤模式
        
        # 记录初始化信息，包含 AI 过滤模式
        logger.info(f"Pixiv 插件配置加载：refresh_token={'已设置' if self.refresh_token else '未设置'}, return_count={self.return_count}, r18_mode='{self.r18_mode}', ai_filter_mode='{self.ai_filter_mode}'")
        
    @staticmethod
    def info() -> Dict[str, Any]:
        """返回插件元数据"""
        return {
            "name": "pixiv_search",
            "author": "vmoranv",
            "description": "Pixiv 图片搜索",
            "version": "1.0.3",
            "homepage": "https://github.com/vmoranv/astrbot_plugin_pixiv_search"
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
                return False # 明确返回 False

        except Exception as e:
            # 捕获更具体的异常可能更好，但 Exception 可以作为保底
            logger.error(f"Pixiv 插件：认证/刷新时发生错误 - 异常类型: {type(e)}, 错误信息: {e}")
            # 发生错误时，认为认证失败
            return False # 明确返回 False

    def _get_safe_tags(self, item: Any) -> List[str]:
        """安全地获取对象的标签列表，处理 None 和非字典/字符串的情况"""
        if not item or not hasattr(item, 'tags') or not item.tags:
            return []

        tags_list = []
        if isinstance(item.tags, list):
            for tag_item in item.tags:
                if isinstance(tag_item, dict):
                    tags_list.append(tag_item.get("name", str(tag_item)))
                elif isinstance(tag_item, str):
                    tags_list.append(tag_item)
        elif isinstance(item.tags, dict):
             tags_list.append(item.tags.get("name", str(item.tags)))
        elif isinstance(item.tags, str):
             tags_list.append(item.tags)

        return [tag for tag in tags_list if tag] # 过滤空字符串

    def _is_r18(self, illust: Any) -> bool:
        """检查插画是否包含 R18 标签"""
        r18_tags_lower = {"r-18", "r18", "r_18g", "r18g", "r-18g", "R18", "R18G", "R-18", "R-18G"}
        tags_list = self._get_safe_tags(illust)
        tags_lower_set = {tag.lower() for tag in tags_list}
        return any(tag in r18_tags_lower for tag in tags_lower_set)
    
    def _is_r18_novel(self, novel: Any) -> bool:
        """检查小说是否为 R18/R-18G"""
        if hasattr(novel, 'x_restrict') and novel.x_restrict > 0:
            return True
        r18_novel_tags_lower = {"r-18", "r18", "r_18", "r-18g", "r18g"}
        tags_list = self._get_safe_tags(novel)
        tags_lower_set = {tag.lower() for tag in tags_list}
        return any(tag in r18_novel_tags_lower for tag in tags_lower_set)

    def _is_ai(self, illust: Any) -> bool:
        """检查插画是否包含 AI 相关标签"""
        # 包含常见的 AI 标签及其变体 (忽略大小写)
        ai_tags_lower = {"ai", "ai-generated", "aiイラスト", "aigenerated", "ai generated"}
        tags_list = self._get_safe_tags(illust)
        tags_lower_set = {tag.lower() for tag in tags_list}
        return any(tag in ai_tags_lower for tag in tags_lower_set)

    def _filter_illusts(self, illusts: List[Any]) -> List[Any]:
        """根据配置过滤插画列表 (R18 和 AI)"""
        if not illusts:
            return []

        filtered_list = []
        for illust in illusts:
            # R18 过滤
            is_r18 = self._is_r18(illust)
            if self.r18_mode == "过滤 R18" and is_r18:
                continue
            if self.r18_mode == "仅 R18" and not is_r18:
                continue

            # AI 过滤
            is_ai = self._is_ai(illust)
            if self.ai_filter_mode == "过滤 AI 作品" and is_ai:
                continue
            if self.ai_filter_mode == "仅 AI 作品" and not is_ai:
                continue

            # 如果通过所有过滤条件，则添加到结果列表
            filtered_list.append(illust)

        return filtered_list

    def _filter_novels(self, novels: List[Any]) -> List[Any]:
        """根据配置过滤小说列表 (仅 R18)"""
        if not novels:
            return []

        filtered_list = []
        for novel in novels:
            # R18 过滤 (小说通常只检查 is_x_restricted 字段)
            # pixivpy 的 novel 对象似乎没有直接的 R18 标签列表，但可能有 is_x_restricted 字段
            # 或者检查标签中是否包含 R-18 或 R-18G
            is_r18_novel = False
            if hasattr(novel, 'x_restrict') and novel.x_restrict > 0: # 0: all, 1: r18, 2: r18g? (需要确认)
                 is_r18_novel = True
            else:
                 # 作为备选，检查标签
                 r18_novel_tags_lower = {"r-18", "r18", "r_18", "r-18g", "r18g"}
                 tags_list = self._get_safe_tags(novel)
                 tags_lower_set = {tag.lower() for tag in tags_list}
                 if any(tag in r18_novel_tags_lower for tag in tags_lower_set):
                     is_r18_novel = True

            if self.r18_mode == "过滤 R18" and is_r18_novel:
                continue
            if self.r18_mode == "仅 R18" and not is_r18_novel:
                continue

            # 小说暂不过滤 AI
            filtered_list.append(novel)

        return filtered_list

    @command("pixiv")
    async def pixiv(self, event: AstrMessageEvent, tags: str):
        """处理 /pixiv 命令，默认为标签搜索功能"""
        # 帮助信息处理
        if tags.strip().lower() == "help":
            yield self.pixiv_help(event)
            return

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result("Pixiv API 认证失败，请检查配置中的凭据信息。")
            return

        # 标签搜索处理
        logger.info(f"Pixiv 插件：正在搜索标签 - {tags}")
        try:
            # 调用 Pixiv API 搜索插画
            search_result = self.client.search_illust(tags, search_target="partial_match_for_tags")
            initial_illusts = search_result.illusts if search_result.illusts else []
            initial_count = len(initial_illusts)

            if not initial_illusts:
                yield event.plain_result("未找到相关插画。")
                return

            # 根据 R18 模式过滤作品
            filtered_illusts = self._filter_illusts(initial_illusts)

            filtered_count = len(filtered_illusts)
            if self.r18_mode == "过滤 R18" and initial_count > filtered_count:
                yield event.plain_result(f"部分 R18 内容已被过滤 (找到 {initial_count} 个，过滤后剩 {filtered_count} 个)。")

            if not filtered_illusts:
                # 根据过滤模式给出更具体的提示
                no_result_reason = []
                if self.r18_mode == "过滤 R18" and any(self._is_r18(i) for i in initial_illusts):
                    no_result_reason.append("R18 内容")
                if self.ai_filter_mode == "过滤 AI 作品" and any(self._is_ai(i) for i in initial_illusts):
                    no_result_reason.append("AI 作品")
                if self.r18_mode == "仅 R18" and not any(self._is_r18(i) for i in initial_illusts):
                     no_result_reason.append("非 R18 内容")
                if self.ai_filter_mode == "仅 AI 作品" and not any(self._is_ai(i) for i in initial_illusts):
                     no_result_reason.append("非 AI 作品")

                if no_result_reason and initial_count > 0:
                     yield event.plain_result(f"所有找到的作品均为 {' 或 '.join(no_result_reason)}，根据当前设置已被过滤。")
                return # 没有可发送的内容

            # 限制返回数量
            count_to_send = min(filtered_count, self.return_count)
            if count_to_send > 0:
                # 从过滤后的结果中随机选择
                illusts_to_send = random.sample(filtered_illusts, count_to_send)
            else:
                illusts_to_send = [] # 理论上不会执行到这里，因为上面已经处理了 filtered_count 为 0 的情况

            # 发送选定的插画
            if not illusts_to_send:
                 logger.info("没有符合条件的推荐插画可供发送。") 

            for illust in illusts_to_send:
                # 优化标签格式
                tags_str = self._format_tags(illust.tags)

                # 构建详情信息
                detail_message = f"作品标题: {illust.title}\n作者: {illust.user.name}\n标签: {tags_str}\n链接: https://www.pixiv.net/artworks/{illust.id}"

                # 尝试下载并发送图片
                image_url = illust.image_urls.medium # 或者 large
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(image_url, headers={'Referer': 'https://app-api.pixiv.net/'}) as response:
                            if response.status == 200:
                                img_data = await response.read()
                                # 发送图片和文字
                                yield event.chain_result([Comp.Image.fromBytes(img_data), Comp.Plain(detail_message)])
                            else:
                                logger.error(f"Pixiv 插件：下载图片失败 - 状态码: {response.status}, URL: {image_url}")
                                # 如果下载失败，只发送文字信息
                                yield event.plain_result(f"图片下载失败，仅发送信息：\n{detail_message}")
                except Exception as img_e:
                    logger.error(f"Pixiv 插件：下载或处理图片时发生错误 - {img_e}, URL: {image_url}")
                    yield event.plain_result(f"图片处理失败，仅发送信息：\n{detail_message}")


        except Exception as e:
            logger.error(f"Pixiv 插件：搜索插画时发生错误 - {e}")
            yield event.plain_result(f"搜索插画时发生错误: {str(e)}")

    def _format_tags(self, tags_data) -> str:
        """格式化标签数据为易读字符串"""
        if not tags_data:
            return "无"
        
        tags_str = ""
        if isinstance(tags_data, list):
            for tag in tags_data:
                if tag is not None:
                    if isinstance(tag, dict):
                        tag_name = tag.get("name", "")
                        translated_name = tag.get("translated_name") # 不设默认值，以便区分
                        if translated_name and translated_name != tag_name: # 仅当翻译名有效且不同时显示
                            tags_str += f"{tag_name}({translated_name}), "
                        elif tag_name:
                            tags_str += f"{tag_name}, "
                    elif isinstance(tag, str) and tag:
                        tags_str += f"{tag}, "
            return tags_str.rstrip(", ") if tags_str else "无"
        # 对非列表形式的 tags_data 做简单处理（虽然不常见）
        elif isinstance(tags_data, dict):
            tag_name = tags_data.get("name", "")
            translated_name = tags_data.get("translated_name")
            if translated_name and translated_name != tag_name:
                return f"{tag_name}({translated_name})"
            elif tag_name:
                return tag_name
        elif isinstance(tags_data, str):
            return tags_data
            
        return "格式无法解析"

    @command("pixiv_help")
    async def pixiv_help(self, event: AstrMessageEvent):
        """生成并返回帮助信息"""
        help_text = """# Pixiv 搜索插件使用帮助

## 基本命令
- `/pixiv <标签1>,<标签2>,...` - 搜索含有指定标签的插画
- `/pixiv_help` - 显示此帮助信息

## 高级命令
- `/pixiv_recommended` - 获取推荐作品
- `/pixiv_user_search <用户名>` - 搜索Pixiv用户
- `/pixiv_user_detail <用户ID>` - 获取指定用户的详细信息
- `/pixiv_user_illusts <用户ID>` - 获取指定用户的作品
- `/pixiv_novel <标签1>,<标签2>,...` - 搜索小说
- `/pixiv_ranking [mode] [date]` - 获取排行榜作品
- `/pixiv_related <作品ID>` - 获取与指定作品相关的其他作品
- `/pixiv_trending_tags` - 获取当前的插画趋势标签
- `/pixiv_toggle_ai [on|off|only]` - 设置 AI 作品过滤模式 (on:显示, off:过滤, only:仅AI)
- `/pixiv_deepsearch <标签1>,<标签2>,...` - 深度搜索插画（跨多页）

- 当前 R18 模式: {r18_mode}
- 当前返回数量: {return_count}
- 当前 AI 作品模式: {ai_filter_mode}
- 深度搜索翻页深度: {deep_search_depth}

## 注意事项
- 标签可以使用中文、英文或日文
- 多个标签使用英文逗号(,)分隔
- 获取用户作品或相关作品时，ID必须为数字
- 日期必须采用 YYYY-MM-DD 格式
- 使用 `/命令` 或 `/命令 help` 可获取每个命令的详细说明
    """.format(
            r18_mode=self.r18_mode,
            return_count=self.return_count,
            ai_filter_mode=self.ai_filter_mode,
            deep_search_depth=self.config.get("deep_search_depth", 3)
        )

        # 直接返回文本，不转为图片
        yield event.plain_result(help_text)

    @command("pixiv_recommended")
    async def pixiv_recommended(self, event: AstrMessageEvent, args: str = ""):
        """获取 Pixiv 推荐作品"""
        # 直接获取推荐作品，不显示帮助信息
        
        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result("Pixiv API 认证失败，请检查配置中的凭据信息。")
            return

        logger.info("Pixiv 插件：获取推荐作品")
        try:
            # 调用 API 获取推荐
            recommend_result = self.client.illust_recommended()
            initial_illusts = recommend_result.illusts if recommend_result.illusts else []
            initial_count = len(initial_illusts)

            if not initial_illusts:
                yield event.plain_result("未能获取到推荐作品。")
                return

            # 使用辅助函数进行过滤 (R18 和 AI)
            final_filtered_illusts = self._filter_illusts(initial_illusts)
            filtered_count = len(final_filtered_illusts)

            # --- 添加过滤提示信息 ---
            filter_messages = []
            r18_filtered = False
            ai_filtered = False
            if self.r18_mode == "过滤 R18" and any(self._is_r18(i) for i in initial_illusts if i not in final_filtered_illusts):
                r18_filtered = True
                filter_messages.append("R18 内容")
            if self.ai_filter_mode == "过滤 AI 作品" and any(self._is_ai(i) for i in initial_illusts if i not in final_filtered_illusts):
                ai_filtered = True
                filter_messages.append("AI 作品")

            if filter_messages:
                yield event.plain_result(f"部分推荐中的 {' 和 '.join(filter_messages)} 已被过滤 (找到 {initial_count} 个，过滤后剩 {filtered_count} 个)。")
            # --- 过滤提示信息结束 ---

            if not final_filtered_illusts:
                no_result_reason = []
                if self.r18_mode == "过滤 R18" and r18_filtered: no_result_reason.append("R18 内容")
                if self.ai_filter_mode == "过滤 AI 作品" and ai_filtered: no_result_reason.append("AI 作品")
                if self.r18_mode == "仅 R18" and not any(self._is_r18(i) for i in initial_illusts): no_result_reason.append("非 R18 内容")
                if self.ai_filter_mode == "仅 AI 作品" and not any(self._is_ai(i) for i in initial_illusts): no_result_reason.append("非 AI 作品")

                if no_result_reason and initial_count > 0:
                     yield event.plain_result(f"所有推荐作品均为 {' 或 '.join(no_result_reason)}，根据当前设置已被过滤。")
                return

            # 限制返回数量
            count_to_send = min(filtered_count, self.return_count)
            if count_to_send > 0:
                illusts_to_send = random.sample(final_filtered_illusts, count_to_send)
            else:
                illusts_to_send = []

            # 处理每个推荐作品
            for illust in illusts_to_send:
                try:
                    image_url = illust.image_urls.large
                    async with aiohttp.ClientSession() as session:
                        headers = {"Referer": "https://www.pixiv.net/"}
                        async with session.get(image_url, headers=headers) as response:
                            if response.status == 200:
                                img_data = await response.read()
                                
                                # 优化标签格式
                                tags_str = ""
                                for tag in illust.tags:
                                    if tag is not None:
                                        if isinstance(tag, dict):
                                            tag_name = tag.get("name", "")
                                            translated_name = tag.get("translated_name", "")
                                            if translated_name:
                                                tags_str += f"{tag_name}({translated_name}), "
                                            else:
                                                tags_str += f"{tag_name}, "
                                        else:
                                            tags_str += f"{tag}, "
                                tags_str = tags_str.rstrip(", ")  # 移除最后的逗号和空格
                                
                                detail_message = f"作品标题: {illust.title}\n作者: {illust.user.name}\n标签: {tags_str}\n链接: https://www.pixiv.net/artworks/{illust.id}"
                                yield event.chain_result([Comp.Image.fromBytes(img_data), Comp.Plain(detail_message)])
                            else:
                                logger.error(f"Pixiv 插件：下载图片失败 - 状态码: {response.status}")
                                yield event.plain_result(f"下载图片失败 - 状态码: {response.status}")
                except Exception as e:
                    logger.error(f"Pixiv 插件：处理推荐作品时发生错误 - {e}")
                    yield event.plain_result(f"处理推荐作品时发生错误: {str(e)}")

            # 在返回结果时，添加过滤信息
            if self.r18_mode == "过滤 R18":
                yield event.plain_result("已过滤 R18 内容。")
            elif self.r18_mode == "仅 R18":
                yield event.plain_result("仅返回 R18 内容。")
        except Exception as e:
            logger.error(f"Pixiv 插件：获取推荐作品时发生错误 - {e}")
            yield event.plain_result(f"获取推荐作品时发生错误: {str(e)}")

    @command("pixiv_user")
    async def pixiv_user_cmd(self, event: AstrMessageEvent, user_id: str):
        """处理 /pixiv_user <用户ID> 命令，获取用户作品"""
        # 验证用户ID是否为数字
        if not user_id.isdigit():
            yield event.plain_result(f"用户ID必须是数字: {user_id}")
            return

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result("Pixiv API 认证失败，请检查配置中的凭据信息。")
            return

        logger.info(f"Pixiv 插件：获取用户作品 - ID: {user_id}")
        try:
            # 调用 API 获取用户作品
            json_result = self.client.user_illusts(user_id)
            if not json_result.illusts:
                yield event.plain_result(f"未找到用户 {user_id} 的作品。")
                return

            # 根据 R18 模式过滤作品
            filtered_illusts = self._filter_illusts(json_result.illusts)
            
            if not filtered_illusts:
                yield event.plain_result(f"未找到符合过滤条件的用户 {user_id} 作品。")
                return

            # 限制返回数量
            illusts_to_show = filtered_illusts[:self.return_count]
            
            # 处理每个用户作品
            for illust in illusts_to_show:
                try:
                    image_url = illust.image_urls.large
                    async with aiohttp.ClientSession() as session:
                        headers = {"Referer": "https://www.pixiv.net/"}
                        async with session.get(image_url, headers=headers) as response:
                            if response.status == 200:
                                img_data = await response.read()
                                tags_str = ""
                                for tag in illust.tags:
                                    if tag is not None:
                                        if isinstance(tag, dict):
                                            tag_name = tag.get("name", "")
                                            translated_name = tag.get("translated_name", "")
                                            if translated_name:
                                                tags_str += f"{tag_name}({translated_name}), "
                                            else:
                                                tags_str += f"{tag_name}, "
                                        else:
                                            tags_str += f"{tag}, "
                                tags_str = tags_str.rstrip(", ")  # 移除最后的逗号和空格
                                detail_message = f"作品标题: {illust.title}\n作者: {illust.user.name}\n标签: {tags_str}\n链接: https://www.pixiv.net/artworks/{illust.id}"
                                yield event.chain_result([Comp.Image.fromBytes(img_data), Comp.Plain(detail_message)])
                            else:
                                logger.error(f"Pixiv 插件：下载图片失败 - 状态码: {response.status}")
                                yield event.plain_result(f"下载图片失败 - 状态码: {response.status}")
                except Exception as e:
                    logger.error(f"Pixiv 插件：处理用户作品时发生错误 - {e}")
                    yield event.plain_result(f"处理用户作品时发生错误: {str(e)}")

            # 在返回结果时，添加过滤信息
            if self.r18_mode == "过滤 R18":
                yield event.plain_result("已过滤 R18 内容。")
            elif self.r18_mode == "仅 R18":
                yield event.plain_result("仅返回 R18 内容。")
        except Exception as e:
            logger.error(f"Pixiv 插件：获取用户作品时发生错误 - {e}")
            yield event.plain_result(f"获取用户作品时发生错误: {str(e)}")

    @command("pixiv_ranking")
    async def pixiv_ranking(self, event: AstrMessageEvent, args: str = ""):
        """获取 Pixiv 排行榜作品"""
        args_list = args.strip().split() if args.strip() else []
        
        # 如果没有传入参数或者第一个参数是 'help'，显示帮助信息
        if not args_list or args_list[0].lower() == 'help':
            help_text = """# Pixiv 排行榜查询

## 命令格式
`/pixiv_ranking [mode] [date]`

## 参数说明
- `mode`: 排行榜模式，可选值：
  - 常规模式: day(默认), week, month, day_male, day_female, week_original, week_rookie, day_manga
  - R18模式(需开启R18): day_r18, day_male_r18, day_female_r18, week_r18, week_r18g
- `date`: 日期，格式为 YYYY-MM-DD，可选，默认为最新

## 示例
- `/pixiv_ranking` - 获取默认（每日）排行榜
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
            "day", "week", "month", "day_male", "day_female", 
            "week_original", "week_rookie", "day_manga",
            "day_r18", "day_male_r18", "day_female_r18", "week_r18", "week_r18g"
        ]
        
        if mode not in valid_modes:
            yield event.plain_result(f"无效的排行榜模式: {mode}\n请使用 `/pixiv_ranking help` 查看支持的模式")
            return
        
        # 验证日期格式（如果提供了日期）
        if date:
            try:
                # 简单验证日期格式
                year, month, day = date.split('-')
                if not (len(year) == 4 and len(month) == 2 and len(day) == 2):
                    raise ValueError("日期格式不正确")
            except Exception:
                yield event.plain_result(f"无效的日期格式: {date}\n日期应为 YYYY-MM-DD 格式")
                return

        # 检查 R18 权限
        if "r18" in mode and self.r18_mode == "过滤 R18":
            yield event.plain_result("当前 R18 模式设置为「过滤 R18」，无法使用 R18 相关排行榜。")
            return
        
        logger.info(f"Pixiv 插件：正在获取排行榜 - 模式: {mode}, 日期: {date if date else '最新'}")
        
        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result("Pixiv API 认证失败，请检查配置中的凭据信息。")
            return

        try:
            # 调用 Pixiv API 获取排行榜
            ranking_result = self.client.illust_ranking(mode=mode, date=date)
            initial_illusts = ranking_result.illusts if ranking_result.illusts else []
            initial_count = len(initial_illusts)

            if not initial_illusts:
                yield event.plain_result(f"未能获取到 {date} 的 {mode} 排行榜数据。")
                return

            # 使用辅助函数进行过滤 (R18 和 AI)
            final_filtered_illusts = self._filter_illusts(initial_illusts)
            filtered_count = len(final_filtered_illusts)

            # --- 添加过滤提示信息 ---
            filter_messages = []
            r18_filtered = False
            ai_filtered = False
            if self.r18_mode == "过滤 R18" and any(self._is_r18(i) for i in initial_illusts if i not in final_filtered_illusts):
                r18_filtered = True
                filter_messages.append("R18 内容")
            if self.ai_filter_mode == "过滤 AI 作品" and any(self._is_ai(i) for i in initial_illusts if i not in final_filtered_illusts):
                ai_filtered = True
                filter_messages.append("AI 作品")

            if filter_messages:
                yield event.plain_result(f"排行榜中的部分 {' 和 '.join(filter_messages)} 已被过滤 (找到 {initial_count} 个，过滤后剩 {filtered_count} 个)。")
            # --- 过滤提示信息结束 ---

            if not final_filtered_illusts:
                no_result_reason = []
                if self.r18_mode == "过滤 R18" and r18_filtered: no_result_reason.append("R18 内容")
                if self.ai_filter_mode == "过滤 AI 作品" and ai_filtered: no_result_reason.append("AI 作品")
                if self.r18_mode == "仅 R18" and not any(self._is_r18(i) for i in initial_illusts): no_result_reason.append("非 R18 内容")
                if self.ai_filter_mode == "仅 AI 作品" and not any(self._is_ai(i) for i in initial_illusts): no_result_reason.append("非 AI 作品")

                if no_result_reason and initial_count > 0:
                     yield event.plain_result(f"排行榜中所有作品均为 {' 或 '.join(no_result_reason)}，根据当前设置已被过滤。")
                return

            # 限制返回数量 (排行榜通常按顺序返回，所以取前 N 个而不是随机)
            count_to_send = min(filtered_count, self.return_count)
            if count_to_send > 0:
                # 取过滤后的前 N 个
                illusts_to_send = final_filtered_illusts[:count_to_send]
            else:
                illusts_to_send = []

            # 返回结果
            async with aiohttp.ClientSession() as session:
                for illust in illusts_to_send:
                    image_url = illust.image_urls.medium
                    
                    # 设置请求头以绕过 Pixiv 的防盗链
                    headers = {
                        'Referer': 'https://www.pixiv.net/',
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                    }
                    
                    # 构建标签字符串
                    tags_str = ""
                    for tag in illust.tags:
                        if tag is not None:
                            if isinstance(tag, dict):
                                tag_name = tag.get("name", "")
                                translated_name = tag.get("translated_name", "")
                                if translated_name:
                                    tags_str += f"{tag_name}({translated_name}), "
                                else:
                                    tags_str += f"{tag_name}, "
                            else:
                                tags_str += f"{tag}, "
                    tags_str = tags_str.rstrip(", ")  # 移除最后的逗号和空格
                    
                    # 构建详情信息
                    detail_message = f"作品标题: {illust.title}\n"
                    detail_message += f"作者: {illust.user.name if hasattr(illust, 'user') else '未知'}\n"
                    detail_message += f"排名: {illusts_to_send.index(illust) + 1}\n"
                    detail_message += f"标签: {tags_str}\n"
                    detail_message += f"链接: https://www.pixiv.net/artworks/{illust.id}"
                    
                    async with session.get(image_url, headers=headers) as response:
                        if response.status == 200:
                            img_data = await response.read()
                            yield event.chain_result([Comp.Image.fromBytes(img_data), Comp.Plain(detail_message)])
                        else:
                            yield event.plain_result(f"下载图片失败 - 状态码: {response.status}\n{detail_message}")

            # 在返回结果时，添加过滤信息
            if self.r18_mode == "过滤 R18":
                yield event.plain_result("已过滤 R18 内容。")
            elif self.r18_mode == "仅 R18":
                yield event.plain_result("仅返回 R18 内容。")
        
        except Exception as e:
            logger.error(f"Pixiv 插件：获取排行榜时发生错误 - {e}")
            yield event.plain_result(f"获取排行榜时发生错误: {str(e)}")

    @command("pixiv_related")
    async def pixiv_related(self, event: AstrMessageEvent, illust_id: str = ""):
        """获取与指定作品相关的其他作品"""
        # 检查参数是否为空或为 help
        if not illust_id.strip() or illust_id.strip().lower() == 'help':
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
            yield event.plain_result("Pixiv API 认证失败，请检查配置中的凭据信息。")
            return
        
        logger.info(f"Pixiv 插件：获取相关作品 - ID: {illust_id}")
        try:
            # 调用 API 获取相关作品
            related_result = self.client.illust_related(int(illust_id))
            initial_illusts = related_result.illusts if related_result.illusts else []
            initial_count = len(initial_illusts)

            if not initial_illusts:
                yield event.plain_result(f"未能找到与作品 ID {illust_id} 相关的作品。")
                return

            # 使用辅助函数进行过滤 (R18 和 AI)
            final_filtered_illusts = self._filter_illusts(initial_illusts)
            filtered_count = len(final_filtered_illusts)

            # --- 添加过滤提示信息 ---
            filter_messages = []
            r18_filtered = False
            ai_filtered = False
            if self.r18_mode == "过滤 R18" and any(self._is_r18(i) for i in initial_illusts if i not in final_filtered_illusts):
                r18_filtered = True
                filter_messages.append("R18 内容")
            if self.ai_filter_mode == "过滤 AI 作品" and any(self._is_ai(i) for i in initial_illusts if i not in final_filtered_illusts):
                ai_filtered = True
                filter_messages.append("AI 作品")

            if filter_messages:
                yield event.plain_result(f"相关作品中的部分 {' 和 '.join(filter_messages)} 已被过滤 (找到 {initial_count} 个，过滤后剩 {filtered_count} 个)。")
            # --- 过滤提示信息结束 ---

            if not final_filtered_illusts:
                no_result_reason = []
                if self.r18_mode == "过滤 R18" and r18_filtered: no_result_reason.append("R18 内容")
                if self.ai_filter_mode == "过滤 AI 作品" and ai_filtered: no_result_reason.append("AI 作品")
                if self.r18_mode == "仅 R18" and not any(self._is_r18(i) for i in initial_illusts): no_result_reason.append("非 R18 内容")
                if self.ai_filter_mode == "仅 AI 作品" and not any(self._is_ai(i) for i in initial_illusts): no_result_reason.append("非 AI 作品")

                if no_result_reason and initial_count > 0:
                     yield event.plain_result(f"所有相关作品均为 {' 或 '.join(no_result_reason)}，根据当前设置已被过滤。")
                return

            # 限制返回数量
            count_to_send = min(filtered_count, self.return_count)
            if count_to_send > 0:
                illusts_to_send = random.sample(final_filtered_illusts, count_to_send)
            else:
                illusts_to_send = []

            # 处理每个相关作品
            for illust in illusts_to_send:
                try:
                    image_url = illust.image_urls.large
                    async with aiohttp.ClientSession() as session:
                        headers = {"Referer": "https://www.pixiv.net/"}
                        async with session.get(image_url, headers=headers) as response:
                            if response.status == 200:
                                img_data = await response.read()
                                tags_str = ""
                                for tag in illust.tags:
                                    if tag is not None:
                                        if isinstance(tag, dict):
                                            tag_name = tag.get("name", "")
                                            translated_name = tag.get("translated_name", "")
                                            if translated_name:
                                                tags_str += f"{tag_name}({translated_name}), "
                                            else:
                                                tags_str += f"{tag_name}, "
                                        else:
                                            tags_str += f"{tag}, "
                                tags_str = tags_str.rstrip(", ")  # 移除最后的逗号和空格
                                detail_message = f"作品标题: {illust.title}\n作者: {illust.user.name}\n标签: {tags_str}\n链接: https://www.pixiv.net/artworks/{illust.id}"
                                yield event.chain_result([Comp.Image.fromBytes(img_data), Comp.Plain(detail_message)])
                            else:
                                logger.error(f"Pixiv 插件：下载图片失败 - 状态码: {response.status}")
                                yield event.plain_result(f"下载图片失败 - 状态码: {response.status}")
                except Exception as e:
                    logger.error(f"Pixiv 插件：处理相关作品时发生错误 - {e}")
                    yield event.plain_result(f"处理相关作品时发生错误: {str(e)}")

            # 在返回结果时，添加过滤信息
            if self.r18_mode == "过滤 R18":
                yield event.plain_result("已过滤 R18 内容。")
            elif self.r18_mode == "仅 R18":
                yield event.plain_result("仅返回 R18 内容。")
        except Exception as e:
            logger.error(f"Pixiv 插件：获取相关作品时发生错误 - {e}")
            yield event.plain_result(f"获取相关作品时发生错误: {str(e)}")

    @command("pixiv_user_search")
    async def pixiv_user_search(self, event: AstrMessageEvent, username: str = ""):
        """搜索 Pixiv 用户"""
        # 检查参数是否为空或为 help
        if not username.strip() or username.strip().lower() == 'help':
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
            yield event.plain_result("Pixiv API 认证失败，请检查配置中的凭据信息。")
            return
        
        try:
            # 调用 Pixiv API 搜索用户
            json_result = self.client.search_user(username)
            if not json_result or not hasattr(json_result, 'user_previews') or not json_result.user_previews:
                yield event.plain_result(f"未找到用户: {username}")
                return

            # 获取第一个用户
            user_preview = json_result.user_previews[0]
            user = user_preview.user
            
            # 构建用户信息
            user_info = f"用户名: {user.name}\n"
            user_info += f"用户ID: {user.id}\n"
            user_info += f"账号: @{user.account}\n"
            user_info += f"简介: {user.comment if hasattr(user, 'comment') else '无'}\n"
            user_info += f"作品数: {user_preview.illusts_len if hasattr(user_preview, 'illusts_len') else '未知'}\n"
            user_info += f"个人主页: https://www.pixiv.net/users/{user.id}"
            
            # 如果有作品，获取一个作为预览
            if hasattr(user_preview, 'illusts') and user_preview.illusts:
                illust = user_preview.illusts[0]
                
                # 构建结果消息
                async with aiohttp.ClientSession() as session:
                    image_url = illust.image_urls.medium
                    
                    # 设置请求头以绕过 Pixiv 的防盗链
                    headers = {
                        'Referer': 'https://www.pixiv.net/',
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                    }
                    
                    async with session.get(image_url, headers=headers) as response:
                        if response.status == 200:
                            img_data = await response.read()
                            yield event.chain_result([Comp.Image.fromBytes(img_data), Comp.Plain(user_info)])
                        else:
                            # 如果无法下载图片，只返回文本信息
                            yield event.plain_result(f"{user_info}\n\n[注意] 无法下载预览图片，状态码: {response.status}")
            else:
                # 如果没有作品，只返回用户信息
                yield event.plain_result(user_info)
                
            # 在返回结果时，添加过滤信息
            if self.r18_mode == "过滤 R18":
                yield event.plain_result("已过滤 R18 内容。")
            elif self.r18_mode == "仅 R18":
                yield event.plain_result("仅返回 R18 内容。")
                
        except Exception as e:
            logger.error(f"Pixiv 插件：搜索用户时发生错误 - {e}")
            yield event.plain_result(f"搜索用户时发生错误: {str(e)}")

    @command("pixiv_user_detail")
    async def pixiv_user_detail(self, event: AstrMessageEvent, user_id: str = ""):
        """获取 Pixiv 用户详情"""
        # 检查参数是否为空或为 help
        if not user_id.strip() or user_id.strip().lower() == 'help':
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
            yield event.plain_result("Pixiv API 认证失败，请检查配置中的凭据信息。")
            return
        
        try:
            # 调用 Pixiv API 获取用户详情
            json_result = self.client.user_detail(user_id)
            if not json_result or not hasattr(json_result, 'user'):
                yield event.plain_result(f"未找到用户 - ID: {user_id}")
                return
            
            user = json_result.user
            profile = json_result.profile if hasattr(json_result, 'profile') else None
            
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
            
            detail_info += f"简介: {user.comment if hasattr(user, 'comment') else '无'}\n"
            detail_info += f"个人主页: https://www.pixiv.net/users/{user.id}"
            
            # 返回用户详情
            yield event.plain_result(detail_info)
            
            # 在返回结果时，添加过滤信息
            if self.r18_mode == "过滤 R18":
                yield event.plain_result("已过滤 R18 内容。")
            elif self.r18_mode == "仅 R18":
                yield event.plain_result("仅返回 R18 内容。")
            
        except Exception as e:
            logger.error(f"Pixiv 插件：获取用户详情时发生错误 - {e}")
            yield event.plain_result(f"获取用户详情时发生错误: {str(e)}")

    @command("pixiv_user_illusts")
    async def pixiv_user_illusts(self, event: AstrMessageEvent, user_id: str = ""):
        """获取指定用户的作品"""
        # 检查参数是否为空或为 help
        if not user_id.strip() or user_id.strip().lower() == 'help':
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
            yield event.plain_result("Pixiv API 认证失败，请检查配置中的凭据信息。")
            return
        
        try:
            # 获取用户信息以显示用户名
            user_detail_result = self.client.user_detail(int(user_id))
            user_name = user_detail_result.user.name if user_detail_result and user_detail_result.user else f"用户ID {user_id}"

            # 调用 API 获取用户作品
            user_illusts_result = self.client.user_illusts(int(user_id))
            initial_illusts = user_illusts_result.illusts if user_illusts_result.illusts else []
            initial_count = len(initial_illusts)

            if not initial_illusts:
                yield event.plain_result(f"用户 {user_name} ({user_id}) 没有公开的作品。")
                return

            # 使用辅助函数进行过滤 (R18 和 AI)
            final_filtered_illusts = self._filter_illusts(initial_illusts)
            filtered_count = len(final_filtered_illusts)

            # --- 添加过滤提示信息 ---
            filter_messages = []
            r18_filtered = False
            ai_filtered = False
            if self.r18_mode == "过滤 R18" and any(self._is_r18(i) for i in initial_illusts if i not in final_filtered_illusts):
                r18_filtered = True
                filter_messages.append("R18 内容")
            if self.ai_filter_mode == "过滤 AI 作品" and any(self._is_ai(i) for i in initial_illusts if i not in final_filtered_illusts):
                ai_filtered = True
                filter_messages.append("AI 作品")

            if filter_messages:
                yield event.plain_result(f"用户 {user_name} 的部分 {' 和 '.join(filter_messages)} 已被过滤 (找到 {initial_count} 个，过滤后剩 {filtered_count} 个)。")
            # --- 过滤提示信息结束 ---

            if not final_filtered_illusts:
                no_result_reason = []
                if self.r18_mode == "过滤 R18" and r18_filtered: no_result_reason.append("R18 内容")
                if self.ai_filter_mode == "过滤 AI 作品" and ai_filtered: no_result_reason.append("AI 作品")
                if self.r18_mode == "仅 R18" and not any(self._is_r18(i) for i in initial_illusts): no_result_reason.append("非 R18 内容")
                if self.ai_filter_mode == "仅 AI 作品" and not any(self._is_ai(i) for i in initial_illusts): no_result_reason.append("非 AI 作品")

                if no_result_reason and initial_count > 0:
                     yield event.plain_result(f"用户 {user_name} 的所有作品均为 {' 或 '.join(no_result_reason)}，根据当前设置已被过滤。")
                return

            # 限制返回数量
            count_to_send = min(filtered_count, self.return_count)
            if count_to_send > 0:
                illusts_to_send = random.sample(final_filtered_illusts, count_to_send)
            else:
                illusts_to_send = []

            # 发送选定的插画
            if not illusts_to_send:
                 logger.info(f"用户 {user_id} 没有符合条件的插画可供发送。") # 可以加个日志
                 # 此处不需要 yield 消息，因为之前的逻辑已经处理了无结果的情况

            for illust in illusts_to_send:
                # 优化标签格式
                tags_str = self._format_tags(illust.tags)

                # 构建详情信息
                detail_message = f"作品标题: {illust.title}\n"
                detail_message += f"作者: {user_name}\n"
                detail_message += f"标签: {tags_str}\n"
                detail_message += f"链接: https://www.pixiv.net/artworks/{illust.id}"
                
                # 尝试下载并发送图片
                image_url = illust.image_urls.medium
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(image_url, headers={'Referer': 'https://app-api.pixiv.net/'}) as response:
                            if response.status == 200:
                                img_data = await response.read()
                                # 发送图片和文字
                                yield event.chain_result([Comp.Image.fromBytes(img_data), Comp.Plain(detail_message)])
                            else:
                                logger.error(f"Pixiv 插件：下载图片失败 - 状态码: {response.status}, URL: {image_url}")
                                # 如果下载失败，只发送文字信息
                                yield event.plain_result(f"图片下载失败，仅发送信息：\n{detail_message}")
                except Exception as img_e:
                    logger.error(f"Pixiv 插件：下载或处理图片时发生错误 - {img_e}, URL: {image_url}")
                    yield event.plain_result(f"图片处理失败，仅发送信息：\n{detail_message}")
        
            # 在返回结果时，添加过滤信息
            if self.r18_mode == "过滤 R18":
                yield event.plain_result("已过滤 R18 内容。")
            elif self.r18_mode == "仅 R18":
                yield event.plain_result("仅返回 R18 内容。")
        
        except Exception as e:
            logger.error(f"Pixiv 插件：获取用户作品时发生错误 - {e}")
            yield event.plain_result(f"获取用户作品时发生错误: {str(e)}")

    @command("pixiv_novel")
    async def pixiv_novel(self, event: AstrMessageEvent, tags: str):
        """处理 /pixiv_novel 命令，搜索 Pixiv 小说"""
        # 检查参数是否为空或为 help
        if not tags.strip() or tags.strip().lower() == 'help':
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
            yield event.plain_result("Pixiv API 认证失败，请检查配置中的凭据信息。")
            return
        
        try:
            # 调用 Pixiv API 搜索小说
            search_result = self.client.search_novel(tags, search_target="partial_match_for_tags") # 或 'exact_match_for_tags'
            initial_novels = search_result.novels if search_result.novels else []
            initial_count = len(initial_novels)

            if not initial_novels:
                yield event.plain_result(f"未找到相关小说: {tags}")
                return

            # 使用 _filter_novels 进行 R18 过滤
            filtered_novels = self._filter_novels(initial_novels)
            filtered_count = len(filtered_novels)

            # --- 更新过滤提示信息 ---
            r18_filtered_novel = False
            if self.r18_mode == "过滤 R18" and any(self._is_r18_novel(n) for n in initial_novels if n not in filtered_novels): # 需要一个 _is_r18_novel 辅助函数
                 r18_filtered_novel = True

            if self.r18_mode == "过滤 R18" and r18_filtered_novel:
                yield event.plain_result(f"部分 R18/R-18G 内容已被过滤 (找到 {initial_count} 个，过滤后剩 {filtered_count} 个)。")
            # --- 过滤提示信息结束 ---


            if not filtered_novels:
                if self.r18_mode == "过滤 R18" and r18_filtered_novel:
                    yield event.plain_result("所有找到的小说均为 R18/R-18G 内容，已被过滤。")
                elif self.r18_mode == "仅 R18" and not any(self._is_r18_novel(n) for n in initial_novels):
                    yield event.plain_result("未找到符合条件的 R18/R-18G 小说。")
                # 如果 initial_count 本身就是 0，则之前的 "未找到" 消息已经发送
                return # 没有可发送的内容

            # 限制返回数量
            count_to_send = min(filtered_count, self.return_count) # 确定实际要发送的数量
            if count_to_send > 0:
                novels_to_show = random.sample(filtered_novels, count_to_send)
            else:
                novels_to_show = [] # 理论上不会执行到这里

            # 返回结果
            if not novels_to_show:
                 logger.info("没有符合条件的小说可供发送。") # 可以加个日志

            for novel in novels_to_show:
                # 构建标签字符串 (使用辅助函数)
                tags_str = self._format_tags(novel.tags)

                # 构建详情信息
                detail_message = f"小说标题: {novel.title}\n"
                detail_message += f"作者: {novel.user.name if hasattr(novel, 'user') else '未知'}\n"
                detail_message += f"标签: {tags_str}\n"
                detail_message += f"字数: {novel.text_length if hasattr(novel, 'text_length') else '未知'}\n"
                if hasattr(novel, 'series') and novel.series:
                    detail_message += f"系列: {novel.series.title if hasattr(novel.series, 'title') else '未知'}\n"
                detail_message += f"链接: https://www.pixiv.net/novel/show.php?id={novel.id}"

                # 返回小说信息
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
            yield event.plain_result("Pixiv API 认证失败，请检查配置中的凭据信息。")
            return

        try:
            # 调用 API 获取趋势标签
            # filter 参数可以尝试 'for_ios' 或 'for_android'，默认为 'for_ios'
            result = self.client.trending_tags_illust(filter="for_ios")

            if not result or not result.trend_tags:
                yield event.plain_result("未能获取到趋势标签，可能是 API 暂无数据。")
                return

            # 格式化标签信息
            tags_list = []
            for tag_info in result.trend_tags:
                tag_name = tag_info.get("tag", "未知标签")
                translated_name = tag_info.get("translated_name")
                if translated_name and translated_name != tag_name:
                    tags_list.append(f"- {tag_name} ({translated_name})") # 加个 - 看起来更像列表
                else:
                    tags_list.append(f"- {tag_name}") # 加个 -

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

    @command("pixiv_toggle_ai")
    async def pixiv_toggle_ai(self, event: AstrMessageEvent, mode: str = ""):
        """
        切换 AI 作品过滤模式 (仅当前会话有效)。
        用法: /pixiv_toggle_ai [on|off|only]
        - on: 显示 AI 作品 (默认行为)
        - off: 过滤 AI 作品
        - only: 仅显示 AI 作品
        不带参数则显示当前模式。
        """
        mode_map = {
            "on": "显示 AI 作品",
            "off": "过滤 AI 作品",
            "only": "仅 AI 作品"
        }
        valid_modes_display = ", ".join(mode_map.keys()) # "on, off, only"

        if not mode:
            # 如果没有提供参数，显示当前模式和用法
            yield event.plain_result(f"当前 AI 作品过滤模式: {self.ai_filter_mode}\n用法: /pixiv_toggle_ai [{valid_modes_display}]")
            return

        mode_lower = mode.lower() # 转换为小写以匹配

        if mode_lower in mode_map:
            new_mode = mode_map[mode_lower]
            if self.ai_filter_mode == new_mode:
                yield event.plain_result(f"AI 作品过滤模式已经是: {self.ai_filter_mode}")
            else:
                self.ai_filter_mode = new_mode
                logger.info(f"Pixiv 插件：AI 过滤模式已切换至 '{self.ai_filter_mode}' (仅当前会话)")
                yield event.plain_result(f"AI 作品过滤模式已切换为: {self.ai_filter_mode}\n(注意：此更改仅在本次插件运行期间有效，如需永久更改请修改配置)")
        else:
            # 无效参数
            yield event.plain_result(f"无效的模式 '{mode}'。请使用以下模式之一: {valid_modes_display}")

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
                f"当前翻页深度设置: {self.config.get('deep_search_depth', 3)} 页 (-1 表示获取所有页面)"
            )
            return

        # 验证是否已认证
        if not await self._authenticate():
            yield event.plain_result("Pixiv API 认证失败，请检查配置中的凭据信息。")
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
        logger.info(f"Pixiv 插件：正在深度搜索标签 - {tag_str}，翻页深度: {deep_search_depth}")
        
        # 搜索前发送提示消息
        if deep_search_depth == -1:
            yield event.plain_result(f"正在深度搜索标签「{tag_str}」，将获取所有页面的结果，这可能需要一些时间...")
        else:
            yield event.plain_result(f"正在深度搜索标签「{tag_str}」，将获取 {deep_search_depth} 页结果，这可能需要一些时间...")
        
        try:
            # 准备搜索参数
            search_params = {
                "word": " ".join(tag_list),
                "search_target": "partial_match_for_tags",
                "sort": "popular_desc",
                "filter": "for_ios",
                "req_auth": True
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
                if not json_result or not hasattr(json_result, 'illusts'):
                    break
                
                # 收集当前页的插画
                current_illusts = json_result.illusts
                if current_illusts:
                    all_illusts.extend(current_illusts)
                    page_count += 1
                    logger.info(f"Pixiv 插件：已获取第 {page_count} 页，找到 {len(current_illusts)} 个插画")
                    
                    # 发送进度更新
                    if page_count % 3 == 0:  # 每3页发送一次进度更新
                        yield event.plain_result(f"搜索进行中：已获取 {page_count} 页，共 {len(all_illusts)} 个结果...")
                else:
                    break  # 当前页没有结果，结束循环
                
                # 获取下一页参数
                next_url = json_result.next_url
                next_params = self.client.parse_qs(next_url) if next_url else None
                
                # 避免请求过于频繁
                if next_params:
                    await asyncio.sleep(1)  # 添加延迟，避免请求过快
            
            # 检查是否有结果
            if not all_illusts:
                yield event.plain_result(f"未找到与「{tag_str}」相关的插画。")
                return
            
            # 记录找到的总数量
            initial_count = len(all_illusts)
            logger.info(f"Pixiv 插件：深度搜索完成，共找到 {initial_count} 个插画，开始过滤处理...")
            yield event.plain_result(f"搜索完成！共获取 {page_count} 页，找到 {initial_count} 个结果，正在处理...")
            
            # 进行 R18 和 AI 过滤
            filtered_illusts = self._filter_illusts(all_illusts)
            filtered_count = len(filtered_illusts)
            
            # 如果过滤后结果为空，提供反馈
            if not filtered_illusts:
                if initial_count > 0:
                    yield event.plain_result(f"根据当前的过滤设置 (R18: '{self.r18_mode}', AI: '{self.ai_filter_mode}')，所有找到的作品 ({initial_count} 个) 均已被排除。")
                return
            
            # 打乱顺序，随机选择作品
            random.shuffle(filtered_illusts)
            count_to_send = min(filtered_count, self.return_count)
            selected_illusts = filtered_illusts[:count_to_send]
            
            # 发送过滤信息
            if filtered_count < initial_count:
                if self.r18_mode == "过滤 R18" or self.ai_filter_mode != "显示 AI 作品":
                    filter_msg = f"部分作品已被过滤 (找到 {initial_count} 个，过滤后剩 {filtered_count} 个)。"
                    yield event.plain_result(filter_msg)

            # 发送结果
            if not selected_illusts:
                 logger.info("深度搜索后没有符合条件的插画可供发送。")

            for illust in selected_illusts:
                # 优化标签格式
                tags_str = self._format_tags(illust.tags)

                # 构建详情信息
                detail_message = f"作品标题: {illust.title}\n作者: {illust.user.name}\n标签: {tags_str}\n链接: https://www.pixiv.net/artworks/{illust.id}"

                # 尝试下载并发送图片
                # 优先尝试 large，如果失败或不存在则尝试 medium
                image_url = illust.image_urls.large if hasattr(illust.image_urls, 'large') else illust.image_urls.medium
                try:
                    async with aiohttp.ClientSession() as session:
                        # 添加 Referer 头，模拟浏览器请求，提高成功率
                        async with session.get(image_url, headers={'Referer': 'https://app-api.pixiv.net/'}) as response:
                            if response.status == 200:
                                img_data = await response.read()
                                # 发送图片和文字
                                yield event.chain_result([Comp.Image.fromBytes(img_data), Comp.Plain(detail_message)])
                            else:
                                logger.error(f"Pixiv 插件：下载图片失败 - 状态码: {response.status}, URL: {image_url}")
                                # 如果下载失败，只发送文字信息
                                yield event.plain_result(f"图片下载失败，仅发送信息：\n{detail_message}")
                except Exception as img_e:
                    logger.error(f"Pixiv 插件：下载或处理图片时发生错误 - {img_e}, URL: {image_url}")
                    yield event.plain_result(f"图片处理失败，仅发送信息：\n{detail_message}")
                await asyncio.sleep(0.5)

        except Exception as e:
            logger.error(f"Pixiv 插件：深度搜索时发生错误 - {e}")
            yield event.plain_result(f"深度搜索时发生错误: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())

    async def terminate(self):
        """插件终止时调用的清理函数"""
        logger.info("Pixiv 搜索插件已停用。")
        pass
