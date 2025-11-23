from typing import Any, List, Union
import hashlib
import io
import base64
from pathlib import Path
from pydantic import Field
from pydantic.dataclasses import dataclass
from fpdf import FPDF

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.api import logger

from .tag import build_detail_message, FilterConfig, filter_illusts_with_reason, sample_illusts
from .pixiv_utils import send_pixiv_image, generate_safe_filename

ToolExecResult = Union[str, Any]

@dataclass
class PixivSearchTool(FunctionTool[AstrAgentContext]):
    """
    Pixiv搜索工具，用于智能搜索Pixiv作品（插画或小说）
    """
    pixiv_client: Any = None
    pixiv_config: Any = None

    name: str = "pixiv_search"
    description: str = "Pixiv搜索工具。直接使用用户提供的原始关键词或标签进行搜索。严禁对用户的搜索词进行翻译、改写或扩展。"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或标签。必须直接使用用户输入的原文，不要进行任何翻译、同义词替换或扩展。",
                },
                "search_type": {
                    "type": "string",
                    "description": "搜索类型，可选值: 'illust' (插画), 'novel' (小说)",
                    "default": "illust",
                },
                "filters": {
                    "type": "string",
                    "description": "过滤条件，如 'safe', 'r18' 等",
                },
            },
            "required": ["query"],
        }
    )

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        try:
            query = kwargs.get("query", "")
            search_type = kwargs.get("search_type", "illust")
            
            logger.info(f"Pixiv搜索工具：搜索 '{query}'，类型: {search_type}")
            
            if not self.pixiv_client:
                logger.error("PixivSearchTool: 无法获取pixiv_client")
                return "错误: Pixiv客户端未初始化，无法执行搜索"
            
            tags = query.strip()
            
            if search_type == "novel":
                return await self._search_novel(tags, query, context)
            else:
                return await self._search_illust(tags, query, context)
            
        except Exception as e:
            error_msg = f"Pixiv搜索工具执行失败: {str(e)}"
            logger.error(error_msg)
            return error_msg
    
    async def _search_illust(self, tags, query, context):
        """搜索插画"""
        try:
            import asyncio
            search_result = await asyncio.to_thread(
                self.pixiv_client.search_illust,
                tags,
                search_target="partial_match_for_tags"
            )
            
            if search_result and search_result.illusts:
                event = self._get_event(context)
                
                if event:
                    return await self._send_pixiv_result(
                        event, search_result.illusts, query, tags, is_novel=False
                    )
                else:
                    logger.warning("PixivSearchTool: 未找到事件对象，无法发送图片")
                    return self._format_text_results(search_result.illusts, query, tags, is_novel=False)
            else:
                return f"根据查询 '{query}' (标签: '{tags}') 未找到相关插画。"
        except Exception as api_error:
            logger.error(f"Pixiv API调用失败: {api_error}")
            return f"搜索插画时发生API错误: {str(api_error)}"

    async def _search_novel(self, tags, query, context):
        """搜索小说"""
        try:
            import asyncio
            
            # 检查 query 是否为纯数字 ID
            if query.isdigit():
                logger.info(f"PixivSearchTool: 检测到数字ID {query}，尝试直接获取小说详情")
                try:
                    novel_detail = await asyncio.to_thread(self.pixiv_client.novel_detail, int(query))
                    logger.info(f"PixivSearchTool: novel_detail返回结果: {bool(novel_detail)}")
                    
                    if novel_detail and novel_detail.novel:
                        logger.info(f"PixivSearchTool: 找到小说 {novel_detail.novel.title} (ID: {novel_detail.novel.id})")
                        event = self._get_event(context)
                        if event:
                            # 将单个小说对象包装成列表
                            return await self._send_novel_result(
                                event, [novel_detail.novel], query, tags
                            )
                        else:
                            return self._format_text_results([novel_detail.novel], query, tags, is_novel=True)
                    else:
                        logger.info(f"PixivSearchTool: ID {query} 未找到小说 (novel_detail为空或无novel字段)")
                        return f"未找到ID为 {query} 的小说。请确认ID是否正确。"
                except Exception as e:
                    logger.error(f"PixivSearchTool: 获取小说详情失败: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    return f"获取小说详情失败: {str(e)}"
            
            # 如果不是ID，则作为标签搜索
            logger.info(f"PixivSearchTool: 作为标签搜索小说: {tags}")
            search_result = await asyncio.to_thread(
                self.pixiv_client.search_novel,
                tags,
                search_target="partial_match_for_tags"
            )
            
            if search_result and search_result.novels:
                event = self._get_event(context)
                
                if event:
                    return await self._send_novel_result(
                        event, search_result.novels, query, tags
                    )
                else:
                    logger.warning("PixivSearchTool: 未找到事件对象，无法发送小说信息")
                    return self._format_text_results(search_result.novels, query, tags, is_novel=True)
            else:
                return f"根据查询 '{query}' (标签: '{tags}') 未找到相关小说。"
        except Exception as api_error:
            logger.error(f"Pixiv API调用失败: {api_error}")
            return f"搜索小说时发生API错误: {str(api_error)}"

    def _get_event(self, context):
        """获取事件对象"""
        event = None
        try:
            agent_context = context.context if hasattr(context, 'context') else context
            
            if hasattr(context, 'event') and context.event:
                event = context.event
            elif hasattr(agent_context, 'event') and agent_context.event:
                event = agent_context.event
        except Exception as e:
            logger.warning(f"PixivSearchTool: 获取事件对象时出错: {e}")
        return event
    
    def _create_pdf_from_text(self, title: str, text: str) -> bytes:
        """使用 fpdf2 将文本转换为 PDF 字节流"""
        # 字体路径：utils/llm_tool.py -> utils/ -> 插件根目录 -> data/SmileySans-Oblique.ttf
        font_path = Path(__file__).parent.parent / "data" / "SmileySans-Oblique.ttf"
        
        if not font_path.exists():
            logger.error(f"字体文件不存在，无法创建PDF: {font_path}")
            raise FileNotFoundError(f"字体文件不存在: {font_path}")

        pdf = FPDF()
        pdf.add_page()

        # 添加并使用我们自己下载的字体
        pdf.add_font("SmileySans", "", str(font_path), uni=True)
        pdf.set_font("SmileySans", size=20)

        # 添加标题
        pdf.multi_cell(0, 10, title, align="C")
        pdf.ln(10)

        # 设置正文样式
        pdf.set_font_size(12)
        
        # 添加正文
        pdf.multi_cell(0, 10, text)

        # 返回 PDF 内容的字节
        return pdf.output(dest='S')

    async def _send_novel_result(self, event, items, query, tags):
        """发送小说结果（转换为PDF）"""
        import asyncio
        logger.info(f"PixivSearchTool: 进入 _send_novel_result，项目数: {len(items)}")
        
        # 直接使用第一个项目，跳过过滤逻辑（因为main.py的下载命令也不过滤）
        # 如果需要过滤，应该在search阶段做，但对于ID直达，我们假设用户知道自己在做什么
        if not items:
            return f"未找到小说。"
            
        selected_item = items[0]
        novel_id = str(selected_item.id)
        novel_title = selected_item.title
        
        logger.info(f"PixivSearchTool: 准备下载并发送小说 {novel_title} (ID: {novel_id})")
        
        try:
            # 获取小说内容
            novel_content_result = await asyncio.to_thread(self.pixiv_client.webview_novel, novel_id)
            if not novel_content_result or not hasattr(novel_content_result, "text"):
                return f"无法获取小说 {novel_title} (ID: {novel_id}) 的内容。"
            
            novel_text = novel_content_result.text
            
            # 生成PDF
            try:
                pdf_bytes = await asyncio.to_thread(self._create_pdf_from_text, novel_title, novel_text)
            except FileNotFoundError:
                return f"无法生成PDF：字体文件丢失。请联系管理员检查插件安装。"
            except Exception as e:
                logger.error(f"生成PDF失败: {e}")
                return f"生成PDF失败: {str(e)}"
            
            # 加密PDF
            password = hashlib.md5(novel_id.encode()).hexdigest()
            final_pdf_bytes = None
            password_notice = ""
            
            try:
                from PyPDF2 import PdfReader, PdfWriter
                
                reader = PdfReader(io.BytesIO(pdf_bytes))
                writer = PdfWriter()
                for page in reader.pages:
                    writer.add_page(page)
                writer.encrypt(password)
                
                with io.BytesIO() as bytes_stream:
                    writer.write(bytes_stream)
                    final_pdf_bytes = bytes_stream.getvalue()
                
                password_notice = f"PDF已加密，密码为小说ID的MD5值: {password}"
            except ImportError:
                logger.warning("PyPDF2 未安装，发送未加密PDF")
                final_pdf_bytes = pdf_bytes
                password_notice = "注意：PDF未加密（PyPDF2未安装）。"
            except Exception as e:
                logger.warning(f"PDF加密失败: {e}")
                final_pdf_bytes = pdf_bytes
                password_notice = "注意：PDF加密失败，发送未加密版本。"
            
            # 发送文件
            safe_title = generate_safe_filename(novel_title, "novel")
            file_name = f"{safe_title}_{novel_id}.pdf"
            
            # 尝试发送文件
            file_sent = False
            platform_name = event.get_platform_name()
            logger.info(f"PixivSearchTool: 准备发送文件 {file_name}，平台: {platform_name}")
            
            if platform_name == "aiocqhttp" and event.get_group_id():
                try:
                    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
                    if isinstance(event, AiocqhttpMessageEvent):
                        client_bot = event.bot
                        group_id = event.get_group_id()
                        
                        file_base64 = base64.b64encode(final_pdf_bytes).decode('utf-8')
                        base64_uri = f"base64://{file_base64}"
                        
                        logger.info(f"PixivSearchTool: 上传群文件 {file_name}")
                        await client_bot.upload_group_file(group_id=group_id, file=base64_uri, name=file_name)
                        file_sent = True
                        logger.info("PixivSearchTool: 群文件上传成功")
                except Exception as e:
                    logger.error(f"上传群文件失败: {e}")
            
            author = getattr(selected_item.user, 'name', '未知作者') if hasattr(selected_item, 'user') else '未知作者'
            
            if file_sent:
                return f"已为您下载小说：\n**{novel_title}** - {author}\nID: {novel_id}\n\n文件已上传到群文件。\n{password_notice}"
            else:
                logger.warning("PixivSearchTool: 未能通过群文件发送，返回文本提示")
                return f"已找到小说：\n**{novel_title}** - {author}\nID: {novel_id}\n\n由于平台限制或网络原因，无法直接发送文件。请尝试使用命令 `/pixiv_novel_download {novel_id}` 下载。\n(密码提示: {password})"

        except Exception as e:
            logger.error(f"处理小说发送时出错: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return f"处理小说发送时出错: {str(e)}"

    async def _send_pixiv_result(self, event, items, query, tags, is_novel=False):
        """发送Pixiv搜索结果"""
        logger.info(f"PixivSearchTool: 找到事件对象，准备发送{'小说' if is_novel else '图片'}")
        
        config = FilterConfig(
            r18_mode=self.pixiv_config.r18_mode if self.pixiv_config else "过滤 R18",
            ai_filter_mode=self.pixiv_config.ai_filter_mode if self.pixiv_config else "过滤 AI 作品",
            display_tag_str=f"搜索:{query}",
            return_count=self.pixiv_config.return_count if self.pixiv_config else 1,
            logger=logger,
            show_filter_result=False,
            excluded_tags=[]
        )
        
        filtered_items, _ = filter_illusts_with_reason(items, config)
        
        if filtered_items:
            selected_item = sample_illusts(filtered_items, 1, shuffle=True)[0]
            detail_message = build_detail_message(selected_item, is_novel=is_novel)
            
            title = getattr(selected_item, 'title', '未知标题')
            author = getattr(selected_item.user, 'name', '未知作者') if hasattr(selected_item, 'user') else '未知作者'
            item_id = getattr(selected_item, 'id', '未知ID')
            
            text_result = f"找到了！为您搜索到{query}的相关{'小说' if is_novel else '作品'}：\n\n**{title}** - {author}\n\nID: {item_id}\n您可以通过这个ID在Pixiv上查看完整内容。"
            
            try:
                logger.info("PixivSearchTool: 开始发送内容")
                
                results = []
                async for result in send_pixiv_image(
                    self.pixiv_client, event, selected_item, detail_message,
                    show_details=self.pixiv_config.show_details if self.pixiv_config else True
                ):
                    results.append(result)
                    logger.info(f"PixivSearchTool: 获取到发送结果: {type(result)}")
                
                if results:
                    try:
                        if hasattr(event, 'send'):
                            await event.send(results[0])
                            logger.info("PixivSearchTool: 已手动发送图片结果")
                    except Exception as manual_send_error:
                        logger.warning(f"PixivSearchTool: 手动发送图片失败: {manual_send_error}")
                        return results[0]
                    
                    return text_result
                else:
                    return text_result
                    
            except Exception as send_error:
                logger.error(f"发送失败: {send_error}")
                return text_result
            
        else:
            return f"根据查询 '{query}' (标签: '{tags}') 找到{'小说' if is_novel else '作品'}，但都被过滤了。"
    
    def _format_text_results(self, items, query, tags, is_novel=False):
        """格式化文本结果"""
        result = f"根据查询 '{query}' (标签: '{tags}') 找到以下{'小说' if is_novel else '作品'}:\n\n"
        for i, item in enumerate(items[:5], 1):
            detail_msg = build_detail_message(item, is_novel=is_novel)
            title = getattr(item, 'title', '未知标题')
            if title == '无题' and detail_msg:
                lines = detail_msg.split('\n')
                if lines and lines[0].strip():
                    title = lines[0].strip()
            
            author = getattr(item.user, 'name', '未知作者') if hasattr(item, 'user') else '未知作者'
            item_id = getattr(item, 'id', '未知ID')
            result += f"{i}. {title} - {author} (ID: {item_id})\n"
        
        if len(items) > 5:
            result += f"\n... 还有 {len(items) - 5} 个{'小说' if is_novel else '作品'}"
        
        return result
    
def create_pixiv_llm_tools(pixiv_client=None, pixiv_config=None) -> List[FunctionTool]:
    """
    创建Pixiv相关的LLM工具列表
    """
    logger.info(f"创建Pixiv LLM工具，pixiv_client: {'已设置' if pixiv_client else '未设置'}")
    
    tools = [
        PixivSearchTool(pixiv_client=pixiv_client, pixiv_config=pixiv_config),
    ]
    logger.info(f"已创建 {len(tools)} 个LLM工具")
    return tools