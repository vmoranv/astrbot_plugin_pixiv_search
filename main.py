import asyncio
import random
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any # 确保导入 Optional
import aiohttp # 导入 aiohttp

# AstrBot 核心库导入
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
import astrbot.api.message_components as Comp
from astrbot.core.utils.logger import log

# 尝试导入 pixiv-api 库
try:
    from pixivapi import Client, Size, PixivError
except ImportError:
    # 如果导入失败，记录错误并抛出异常，阻止插件加载
    log.error("Pixiv 插件依赖库 'pixiv-api' 未安装。请确保 requirements.txt 文件存在且内容正确，然后重载插件或重启 AstrBot。您也可以尝试手动安装： pip install pixiv-api")
    raise ImportError("pixiv-api not found, please install it.")



@register(
    id="pixiv_search", 
    author="vmoranv", 
    name="Pixiv 图片搜索", 
    version="1.0.0", 
    description="通过标签在 Pixiv 上搜索插画。用法: /pixiv tag1,tag2,... 可在配置中设置认证信息、返回数量和 R18 过滤模式。", 
    repo="https://github.com/vmoranv/astrbot_plugin_pixiv_search"
)
class PixivSearchPlugin(Star):
    """
    AstrBot 插件，用于通过 Pixiv API 搜索插画。
    配置通过 AstrBot WebUI 进行管理。
    """
    def __init__(self, context: Context):
        """插件初始化"""
        super().__init__(context)
        self.client = Client() # 初始化 Pixiv API 客户端
        self.authenticated: bool = False # 认证状态标志

        # --- 从 AstrBot 配置中读取设置 ---
        # 获取本插件的配置字典，如果不存在则返回空字典
        self.config = self.context.get_config('pixiv_search', {})

        # 读取认证信息 (优先使用 refresh_token)
        self.refresh_token: Optional[str] = self.config.get('refresh_token')
        self.username: Optional[str] = self.config.get('username')
        self.password: Optional[str] = self.config.get('password')

        # 读取功能配置，使用 .get() 并提供默认值以防配置缺失
        self.return_count: int = self.config.get('return_count', 1) # 默认返回 1 张
        # R18 模式: 0 = 过滤 R18 (默认), 1 = 允许 R18
        self.r18_mode: int = self.config.get('r18_mode', 0)
        # --------------------------------

        # 在后台启动认证过程，避免阻塞 AstrBot 启动
        asyncio.create_task(self._authenticate())

    async def _authenticate(self):
        """
        异步执行 Pixiv API 认证。
        优先使用 Refresh Token，其次使用用户名/密码 (从配置中读取)。
        """
        try:
            # 优先使用 Refresh Token 认证 (从 self.refresh_token 读取)
            if self.refresh_token:
                log.info("Pixiv 插件：尝试使用配置中的 refresh token 进行认证...")
                await asyncio.to_thread(self.client.authenticate, self.refresh_token)
                # 认证成功后，保存可能更新的 refresh token (仅在内存中更新)
                # 注意：这不会自动写回配置文件
                self.refresh_token = self.client.refresh_token
                log.info("Pixiv 插件：使用 refresh token 认证成功。")
            # 如果没有 Token，则尝试使用用户名和密码 (从 self.username 和 self.password 读取)
            elif self.username and self.password:
                log.info("Pixiv 插件：尝试使用配置中的用户名和密码进行认证...")
                await asyncio.to_thread(self.client.login, self.username, self.password)
                # 认证成功后，保存获取到的 refresh token (仅在内存中更新)
                self.refresh_token = self.client.refresh_token
                log.info(f"Pixiv 插件：使用用户名密码认证成功。新的 Refresh Token 已获取。")
            else:
                # 如果两种认证方式都未配置
                log.warning("Pixiv 插件：未在配置中找到有效的 Pixiv 用户名/密码或 refresh token，无法进行认证。请在 AstrBot 管理面板配置插件。")
                self.authenticated = False
                return # 无法认证，直接返回

            # 标记为认证成功
            self.authenticated = True

        except PixivError as e:
            # 处理 Pixiv API 特定的认证错误
            log.error(f"Pixiv 插件：认证失败 - {e}. 请检查 AstrBot 管理面板中的插件配置。")
            self.authenticated = False
        except Exception as e:
            # 处理其他可能的异常
            log.error(f"Pixiv 插件：认证过程中发生未知错误 - {e}", exc_info=True)
            self.authenticated = False

    @filter.command("pixiv")
    async def search_pixiv(self, event: AstrMessageEvent, tags: str):
        '''
        处理 /pixiv 指令，根据提供的标签搜索 Pixiv 插画。
        标签之间用逗号分隔。
        '''
        # 检查认证状态，如果未认证，尝试重新认证
        if not self.authenticated:
            log.warning("Pixiv 插件：尚未认证，尝试重新认证...")
            await self._authenticate()
            # 如果再次认证失败，则提示用户并返回
            if not self.authenticated:
                yield event.plain_result("Pixiv 插件未认证或认证失败，请检查 AstrBot 管理面板中的插件配置或联系管理员。")
                return

        # 检查用户是否提供了标签
        if not tags:
            yield event.plain_result("请输入要搜索的标签，用逗号分隔。\n例如：`/pixiv 初音ミク,VOCALOID`")
            return

        # 处理标签：去除首尾空格，用空格连接，作为搜索关键词
        search_term = " ".join(tag.strip() for tag in tags.split(',') if tag.strip())
        if not search_term:
            yield event.plain_result("输入的标签无效，请重新输入。")
            return

        log.info(f"Pixiv 插件：收到搜索请求，原始标签: '{tags}', 处理后搜索词: '{search_term}'")

        try:
            # 执行搜索 (同步操作，放入线程执行)
            log.debug(f"Pixiv 插件：开始在 Pixiv 上搜索插画 '{search_term}'...")
            search_result = await asyncio.to_thread(
                self.client.search_illust,
                word=search_term,
                search_target='partial_match_for_tags', # 搜索模式：标签部分匹配
                sort='date_desc', # 排序方式：按日期降序
                # duration=None, # 可选时间范围: 'within_last_day', 'within_last_week', 'within_last_month'
            )
            log.debug(f"Pixiv 插件：搜索 API 调用完成。")

            illustrations = search_result.get("illustrations", [])
            if not illustrations:
                log.info(f"Pixiv 插件：未找到与 '{search_term}' 相关的插画。")
                yield event.plain_result(f"抱歉，找不到与 '{search_term}' 相关的插画。")
                return

            log.info(f"Pixiv 插件：找到 {len(illustrations)} 个初步匹配的插画。")

            # --- 结果过滤和选择 (使用配置中的 r18_mode) ---
            valid_illustrations = []
            filter_r18_enabled = (self.r18_mode == 0) # 0 表示过滤 R18
            log.debug(f"Pixiv 插件：R18 过滤模式: {'启用' if filter_r18_enabled else '禁用'} (配置值: {self.r18_mode})")

            for illust in illustrations:
                # 检查是否需要过滤 R18 内容 (根据配置决定)
                # illust.sanity_level: 2=R-18, 4=R-18G
                if filter_r18_enabled and illust.sanity_level >= 2:
                    log.debug(f"Pixiv 插件：过滤 R18/R18G 插画 ID: {illust.id} (Sanity Level: {illust.sanity_level})")
                    continue # 跳过 R18 内容

                # 检查插画类型是否为 illustration (排除漫画等)
                if illust.type != 'illust':
                    log.debug(f"Pixiv 插件：过滤非插画类型 ID: {illust.id} (Type: {illust.type})")
                    continue

                valid_illustrations.append(illust)

            if not valid_illustrations:
                log.info(f"Pixiv 插件：过滤后没有符合条件的插画。")
                # 根据过滤模式调整提示信息
                if filter_r18_enabled:
                    yield event.plain_result(f"找不到符合条件的非 R18 插画。")
                else:
                    yield event.plain_result(f"找不到符合条件的插画。")
                return

            log.info(f"Pixiv 插件：过滤后剩下 {len(valid_illustrations)} 个有效插画。")

            # 从有效插画中随机选择指定数量的插画 (使用配置中的 return_count)
            selected_illusts = random.sample(valid_illustrations, min(self.return_count, len(valid_illustrations)))
            log.info(f"Pixiv 插件：已随机选择 {len(selected_illusts)} 张插画进行发送 (根据配置 return_count={self.return_count})。")

            # --- 构建并发送消息 ---
            message_chain = []
            # 可以添加一个提示信息
            message_chain.append(Comp.Plain(f"为您找到与 '{search_term}' 相关的图片{' (已过滤 R18)' if filter_r18_enabled else ''}：\n"))

            image_send_tasks = []
            for illust in selected_illusts:
                # 获取图片 URL，优先获取原始尺寸
                img_url: Optional[str] = None
                try:
                    # 处理单页插画
                    if illust.meta_single_page and illust.meta_single_page.get('original_image_url'):
                        img_url = illust.meta_single_page['original_image_url']
                    # 处理多页插画（默认取第一页）
                    elif illust.meta_pages and len(illust.meta_pages) > 0:
                        img_url = illust.meta_pages[0].image_urls.original
                    # 备选方案：使用大尺寸图片 URL
                    elif illust.image_urls and illust.image_urls.large:
                        img_url = illust.image_urls.large

                    if img_url:
                        log.info(f"Pixiv 插件：准备发送插画 ID: {illust.id}, Title: {illust.title}, URL: {img_url}")
                        # !! 注意：直接使用 Pixiv 的 URL 可能因为缺少 Referer 而无法被 AstrBot 或消息平台直接加载 !!
                        # 尝试直接发送 URL。如果失败，需要考虑下载到本地再发送。
                        message_chain.append(Comp.Image.fromURL(img_url))
                        # 可以附加一些图片信息
                        message_chain.append(Comp.Plain(f"Title: {illust.title}\nAuthor: {illust.user.name} (ID: {illust.user.id})\nPID: {illust.id}\n"))
                    else:
                        log.warning(f"Pixiv 插件：无法获取插画 ID: {illust.id} 的有效图片 URL。")

                except Exception as url_err:
                    log.error(f"Pixiv 插件：处理插画 ID {illust.id} 的 URL 时出错: {url_err}", exc_info=True)


            # 检查是否有成功获取到图片 URL
            if len(message_chain) <= 1: # 只有提示语，没有图片
                 yield event.plain_result("抱歉，获取选定图片的 URL 时遇到问题。")
                 return

            # 发送包含图片的消息链
            yield event.chain_result(message_chain)

        except PixivError as e:
            # 处理 Pixiv API 调用期间的错误
            log.error(f"Pixiv 插件：API 调用失败 - {e}")
            # 特别处理认证失效的情况
            if "authenticate" in str(e).lower() or "token" in str(e).lower() or "OAuth" in str(e):
                 self.authenticated = False # 标记为未认证
                 log.warning("Pixiv 插件：认证似乎已失效，请检查 AstrBot 管理面板中的插件配置或重新生成 Refresh Token。")
                 yield event.plain_result(f"Pixiv API 调用失败：认证可能已失效或凭据错误，请检查配置。错误: {e}")
            else:
                 yield event.plain_result(f"Pixiv API 调用失败：{e}")
        except Exception as e:
            # 处理其他意外错误
            log.error(f"Pixiv 插件：处理 /pixiv 命令时发生未知错误 - {e}", exc_info=True)
            yield event.plain_result("处理 Pixiv 搜索时发生内部错误，请查看日志。")

    async def terminate(self):
        """插件终止时调用的清理函数"""
        log.info("Pixiv 搜索插件已停用。")
        # 可选：可以在这里添加关闭 Pixiv 客户端连接的代码（如果 pixiv-api 需要）
        pass
