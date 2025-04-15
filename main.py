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
    "1.0.1",
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
        self.proxy = self.config.get("proxy", None)
        self.refresh_token = self.config.get("refresh_token", None)
        self.return_count = self.config.get("return_count", 1)
        self.r18_mode = self.config.get("r18_mode", "过滤 R18")
        
        # 记录初始化信息
        logger.info(f"Pixiv 插件配置加载：refresh_token={'已设置' if self.refresh_token else '未设置'}, return_count={self.return_count}, r18_mode='{self.r18_mode}'")
        
    @staticmethod
    def info() -> Dict[str, Any]:
        """返回插件元数据"""
        return {
            "name": "pixiv_search",
            "author": "vmoranv",
            "description": "Pixiv 图片搜索",
            "version": "1.0.0",
            "homepage": "https://github.com/vmoranv/astrbot_plugin_pixiv_search"
        }

    async def _authenticate(self) -> bool:
        """尝试使用配置的凭据进行 Pixiv API 认证"""
        if self.authenticated:
            return True

        logger.info("Pixiv 插件：尝试进行 Pixiv API 认证...")
        try:
            if self.refresh_token:
                logger.info("使用 Refresh Token 进行认证...")
                self.client.auth(refresh_token=self.refresh_token)  # 仅使用 refresh_token
                self.authenticated = True
                logger.info("Pixiv 插件：认证成功。")
                return True
            else:
                logger.error("Pixiv 插件：未提供有效的 Refresh Token，无法进行认证。")
                return False

        except Exception as e:
            logger.error(f"Pixiv 插件：认证失败 - 异常类型: {type(e)}, 错误信息: {e}, 异常详情: {e.__dict__}")
            logger.warning("Pixiv 插件：API 认证失败，请检查配置中的凭据信息。")
            return False

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
            filtered_illusts = []
            for illust in search_result.illusts:
                # 检查 illust.tags 是否为 None，并确保 tags 是一个列表
                tags_list = illust.tags if illust.tags else []

                # 添加日志：打印 illust.tags 的值和类型
                logger.debug(f"illust.tags: {illust.tags}, type: {type(illust.tags)}")
                if isinstance(illust.tags, list):
                    for tag_item in illust.tags:
                        logger.debug(f"  tag item: {tag_item}, type: {type(tag_item)}")

                # 检查 tags_list 中的每个元素是否为字符串且非 None
                safe_tags_list = [str(tag) for tag in tags_list if tag is not None]
                is_r18 = any(tag.lower() in ["r-18", "r18"] for tag in safe_tags_list)
                if self.r18_mode == "过滤 R18" and is_r18:
                    continue  # 跳过 R18 作品
                elif self.r18_mode == "仅 R18" and not is_r18:
                    continue  # 跳过非 R18 作品
                filtered_illusts.append(illust)

            if not filtered_illusts:
                yield event.plain_result("未找到符合过滤条件的插画。")
                return

            # 限制返回数量
            illusts_to_show = filtered_illusts[:self.return_count]

            # 处理每个插画
            for illust in illusts_to_show:
                try:
                    # 获取图片 URL
                    image_url = illust.image_urls.large
                    
                    # 下载图片
                    async with aiohttp.ClientSession() as session:
                        async with session.get(image_url, headers={'Referer': 'https://app-api.pixiv.net/'}, proxy=self.proxy) as response:
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
                                
                                # 构建详情信息
                                detail_message = f"作品标题: {illust.title}\n作者: {illust.user.name}\n标签: {tags_str}\n链接: https://www.pixiv.net/artworks/{illust.id}"
                                
                                # 返回图片和详情
                                yield event.chain_result([Comp.Image.fromBytes(img_data), Comp.Plain(detail_message)])
                            else:
                                logger.error(f"Pixiv 插件：下载图片失败 - 状态码: {response.status}")
                                yield event.plain_result(f"下载图片失败 - 状态码: {response.status}")
                except Exception as e:
                    logger.error(f"Pixiv 插件：处理插画时发生错误 - {e}")
                    yield event.plain_result(f"处理插画时发生错误: {str(e)}")
        except Exception as e:
            logger.error(f"Pixiv 插件：搜索标签时发生错误 - {e}")
            yield event.plain_result(f"搜索标签时发生错误: {str(e)}")

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

## 配置说明
- 当前 R18 模式: {r18_mode}
- 当前返回数量: {return_count}

## 注意事项
- 标签可以使用中文、英文或日文
- 多个标签使用英文逗号(,)分隔
- 获取用户作品或相关作品时，ID必须为数字
- 日期必须采用 YYYY-MM-DD 格式
- 使用 `/命令` 或 `/命令 help` 可获取每个命令的详细说明
    """.format(
            r18_mode=self.r18_mode,
            return_count=self.return_count
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
            # 调用 API 获取推荐作品
            json_result = self.client.illust_recommended()
            initial_illusts = json_result.illusts if json_result.illusts else []
            initial_count = len(initial_illusts)

            if not initial_illusts:
                yield event.plain_result("未找到推荐作品。")
                return

            # 根据 R18 模式过滤作品
            filtered_illusts = []
            for illust in json_result.illusts:
                tags_list = illust.tags if illust.tags else []
                safe_tags_list = [str(tag.get("name", tag)) if isinstance(tag, dict) else str(tag) for tag in tags_list if tag is not None]
                is_r18 = any(tag.lower() in ["r-18", "r18"] for tag in safe_tags_list)
                if self.r18_mode == "过滤 R18" and is_r18:
                    continue
                elif self.r18_mode == "仅 R18" and not is_r18_or_g:
                    continue
                filtered_illusts.append(illust)

            filtered_count = len(filtered_illusts)

            # --- 开始：将过滤状态消息移到这里 ---
            if self.r18_mode == "过滤 R18" and initial_count > filtered_count:
                yield event.plain_result(f"部分 R18/R-18G 推荐作品已被过滤 (找到 {initial_count} 个，过滤后剩 {filtered_count} 个)。")
            # 可选：如果想在"仅 R18"模式下也提示，可以取消下面注释
            # elif self.r18_mode == "仅 R18":
            #     yield event.plain_result(f"仅显示 R18/R-18G 推荐作品 (找到 {filtered_count} 个)。")

            if not filtered_illusts:
                if self.r18_mode == "过滤 R18" and initial_count > 0:
                    yield event.plain_result("所有找到的推荐作品均为 R18/R-18G 内容，已被过滤。")
                elif self.r18_mode == "仅 R18" and initial_count > 0:
                     yield event.plain_result("未找到符合条件的 R18/R-18G 推荐作品。")
                return
            
            count_to_send = min(self.return_count, filtered_count) # 确定实际要发送的数量
            if count_to_send > 0:
                illusts_to_send = random.sample(filtered_illusts, count_to_send)
            else:
                illusts_to_send = []

            # 处理每个选定的推荐作品
            if not illusts_to_send:
                 logger.info("没有符合条件的推荐作品可供发送。")

            for illust in illusts_to_send:
                try:
                    # 优先选择 large，其次 medium
                    image_url = illust.image_urls.large if hasattr(illust.image_urls, 'large') else illust.image_urls.medium
                    async with aiohttp.ClientSession() as session:
                        # 使用正确的 Referer
                        async with session.get(image_url, headers={'Referer': 'https://app-api.pixiv.net/'}, proxy=self.proxy) as response:
                            if response.status == 200:
                                img_data = await response.read()

                                # 使用辅助函数格式化标签
                                tags_str = self._format_tags(illust.tags)

                                detail_message = f"作品标题: {illust.title}\n作者: {illust.user.name}\n标签: {tags_str}\n链接: https://www.pixiv.net/artworks/{illust.id}"
                                yield event.chain_result([Comp.Image.fromBytes(img_data), Comp.Plain(detail_message)])
                            else:
                                logger.error(f"Pixiv 插件：下载图片失败 - 状态码: {response.status}")
                                yield event.plain_result(f"下载图片失败 - 状态码: {response.status}")
                except Exception as e:
                    logger.error(f"Pixiv 插件：处理推荐作品时发生错误 - {e}")
                    yield event.plain_result(f"处理推荐作品时发生错误: {str(e)}")
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
            filtered_illusts = []
            for illust in json_result.illusts:
                tags_list = illust.tags if illust.tags else []
                safe_tags_list = [str(tag) for tag in tags_list if tag is not None]
                # 定义所有可能的 R18 标签变体
                r18_tags = ["r-18", "r18", "R-18", "R18", "R_18", "r_18"]
                is_r18 = any(tag.lower() in r18_tags for tag in safe_tags_list)
                if self.r18_mode == "过滤 R18" and is_r18:
                    continue
                elif self.r18_mode == "仅 R18" and not is_r18:
                    continue
                filtered_illusts.append(illust)
            
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
            if not ranking_result.illusts:
                yield event.plain_result(f"未找到排行榜作品 - 模式: {mode}, 日期: {date if date else '最新'}")
                return

            # 根据 R18 模式过滤作品
            filtered_illusts = []
            for illust in ranking_result.illusts:
                # 检查作品是否为 R18
                is_r18 = False
                if hasattr(illust, 'tags') and illust.tags:
                    for tag in illust.tags:
                        tag_name = tag.get('name', '') if isinstance(tag, dict) else tag
                        if isinstance(tag_name, str) and ('R-18' in tag_name or 'r-18' in tag_name):
                            is_r18 = True
                            break
                
                # 根据 R18 模式过滤
                if self.r18_mode == "过滤 R18" and is_r18:
                    continue  # 跳过 R18 作品
                elif self.r18_mode == "仅 R18" and not is_r18:
                    continue  # 跳过非 R18 作品
                filtered_illusts.append(illust)
            
            if not filtered_illusts:
                yield event.plain_result(f"未找到符合当前 R18 模式的排行榜作品 - 模式: {mode}, 日期: {date if date else '最新'}")
                return

            # 限制返回数量
            count = min(len(filtered_illusts), self.return_count)
            illusts_to_show = filtered_illusts[:count]
            
            # 返回结果
            async with aiohttp.ClientSession() as session:
                for illust in illusts_to_show:
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
                    detail_message += f"排名: {illusts_to_show.index(illust) + 1}\n"
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
    async def pixiv_related(self, event: AstrMessageEvent, illust_id: str):
        """处理 /pixiv_related <作品ID> 命令，获取相关作品"""
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
            json_result = self.client.illust_related(illust_id)
            initial_illusts = json_result.illusts if json_result.illusts else []
            initial_count = len(initial_illusts)

            if not initial_illusts:
                yield event.plain_result(f"未找到与作品 {illust_id} 相关的作品。")
                return

            # 根据 R18 模式过滤作品
            filtered_illusts = []
            for illust in json_result.illusts:
                tags_list = illust.tags if illust.tags else []
                safe_tags_list = [str(tag) for tag in tags_list if tag is not None]
                is_r18 = any(tag.lower() in ["r-18", "r18"] for tag in safe_tags_list)
                if self.r18_mode == "过滤 R18" and is_r18:
                    continue
                elif self.r18_mode == "仅 R18" and not is_r18_or_g:
                    continue
                filtered_illusts.append(illust)

            filtered_count = len(filtered_illusts)

            if self.r18_mode == "过滤 R18" and initial_count > filtered_count:
                yield event.plain_result(f"部分 R18/R-18G 相关作品已被过滤 (找到 {initial_count} 个，过滤后剩 {filtered_count} 个)。")

            if not filtered_illusts:
                if self.r18_mode == "过滤 R18" and initial_count > 0:
                    yield event.plain_result(f"所有找到的相关作品均为 R18/R-18G 内容，已被过滤。")
                elif self.r18_mode == "仅 R18" and initial_count > 0:
                     yield event.plain_result(f"未找到符合条件的 R18/R-18G 相关作品。")
                return
            
            # 限制返回数量
            illusts_to_show = filtered_illusts[:self.return_count]
            
            # 处理每个相关作品
            for illust in illusts_to_show:
                try:
                    # 优先选择 large，其次 medium
                    image_url = illust.image_urls.large if hasattr(illust.image_urls, 'large') else illust.image_urls.medium
                    async with aiohttp.ClientSession() as session:
                         # 使用正确的 Referer
                        async with session.get(image_url, headers={'Referer': 'https://app-api.pixiv.net/'}, proxy=self.proxy) as response:
                            if response.status == 200:
                                img_data = await response.read()

                                # 使用辅助函数格式化标签
                                tags_str = self._format_tags(illust.tags)

                                detail_message = f"作品标题: {illust.title}\n作者: {illust.user.name}\n标签: {tags_str}\n链接: https://www.pixiv.net/artworks/{illust.id}"
                                yield event.chain_result([Comp.Image.fromBytes(img_data), Comp.Plain(detail_message)])
                            else:
                                logger.error(f"Pixiv 插件：下载图片失败 - 状态码: {response.status}")
                                yield event.plain_result(f"下载图片失败 - 状态码: {response.status}")
                except Exception as e:
                    logger.error(f"Pixiv 插件：处理相关作品时发生错误 - {e}")
                    yield event.plain_result(f"处理相关作品时发生错误: {str(e)}")
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
        """获取 Pixiv 用户作品"""
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
            # 调用 Pixiv API 获取用户作品
            json_result = self.client.user_illusts(user_id)
            if not json_result or not hasattr(json_result, 'illusts') or not json_result.illusts:
                yield event.plain_result(f"未找到用户作品 - ID: {user_id}")
                return
            
            # 获取用户名称
            user_name = json_result.illusts[0].user.name if json_result.illusts and hasattr(json_result.illusts[0], 'user') else "未知用户"
            
            # 根据 R18 模式过滤作品
            filtered_illusts = []
            for illust in json_result.illusts:
                # 检查 illust.tags 是否为 None，并确保 tags 是一个列表
                tags_list = illust.tags if illust.tags else []
                
                # 检查 tags_list 中的每个元素是否为字符串且非 None
                safe_tags_list = []
                for tag in tags_list:
                    if isinstance(tag, dict) and 'name' in tag:
                        safe_tags_list.append(tag['name'])
                    elif isinstance(tag, str):
                        safe_tags_list.append(tag)
                
                # 定义所有可能的 R18 标签变体
                r18_tags = ["r-18", "r18", "R-18", "R18", "R_18", "r_18"]
                is_r18 = any(tag.lower() in r18_tags for tag in safe_tags_list)
                if self.r18_mode == "过滤 R18" and is_r18:
                    continue  # 跳过 R18 作品
                elif self.r18_mode == "仅 R18" and not is_r18:
                    continue  # 跳过非 R18 作品
                filtered_illusts.append(illust)
            
            if not filtered_illusts:
                yield event.plain_result(f"未找到符合当前 R18 模式的作品 - 用户: {user_name}({user_id})")
                return
            
            # 限制返回数量
            count = min(len(filtered_illusts), self.return_count)
            illusts_to_show = filtered_illusts[:count]
            filtered_count = len(filtered_illusts)

            if self.r18_mode == "过滤 R18" and len(json_result.illusts) > filtered_count:
                yield event.plain_result(f"部分 R18 内容已被过滤 (找到 {len(json_result.illusts)} 个，过滤后剩 {filtered_count} 个)。")

            count_to_send = min(self.return_count, filtered_count) 
            if count_to_send > 0:
                illusts_to_send = random.sample(filtered_illusts, count_to_send)
            else:
                illusts_to_send = [] # 如果过滤后为0，则发送空列表

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
                        async with session.get(image_url, headers={'Referer': 'https://app-api.pixiv.net/'}, proxy=self.proxy) as response:
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

            # 根据 R18 模式过滤小说
            filtered_novels = []
            for novel in json_result.novels:
                # 检查 novel.tags 是否为 None，并确保 tags 是一个列表
                tags_list = novel.tags if hasattr(novel, 'tags') and novel.tags else []
                
                # 检查 tags_list 中的每个元素是否为字符串且非 None
                safe_tags_list = []
                for tag in tags_list:
                    if isinstance(tag, dict) and 'name' in tag:
                        safe_tags_list.append(tag['name'])
                    elif isinstance(tag, str):
                        safe_tags_list.append(tag)
                
                is_r18 = any(tag.lower() in ["r-18", "r18"] for tag in safe_tags_list)
                if self.r18_mode == "过滤 R18" and is_r18:
                    continue  # 跳过 R18 小说
                elif self.r18_mode == "仅 R18" and not is_r18:
                    continue  # 跳过非 R18 小说
                filtered_novels.append(novel)

            filtered_count = len(filtered_novels)

            if self.r18_mode == "过滤 R18" and initial_count > filtered_count:
                yield event.plain_result(f"部分 R18/R-18G 内容已被过滤 (找到 {initial_count} 个，过滤后剩 {filtered_count} 个)。")

            if not filtered_novels:
                yield event.plain_result(f"未找到符合当前 R18 模式的小说: {tags}")
                return
            
            # 限制返回数量
            count = min(len(filtered_novels), self.return_count)
            novels_to_show = filtered_novels[:count]
            
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

    async def terminate(self):
        """插件终止时调用的清理函数"""
        logger.info("Pixiv 搜索插件已停用。")
        pass
