from typing import Any, List, Union
import hashlib
import io
import base64
from pathlib import Path
from pydantic import Field
from pydantic.dataclasses import dataclass
from fpdf import FPDF

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.api import logger

from .tag import build_detail_message, FilterConfig, filter_illusts_with_reason, sample_illusts
from .pixiv_utils import send_pixiv_image, generate_safe_filename

@dataclass
class PixivIllustSearchTool(FunctionTool[AstrAgentContext]):
    """
    Pixiv插画搜索工具
    """
    pixiv_client: Any = None
    pixiv_config: Any = None

    name: str = "pixiv_search_illust"
    description: str = "Pixiv插画搜索工具。用于搜索Pixiv上的插画作品。直接使用用户提供的关键词或标签。"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或标签。必须直接使用用户输入的原文。",
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
            logger.info(f"Pixiv插画搜索工具：搜索 '{query}'")
            
            if not self.pixiv_client:
                return "错误: Pixiv客户端未初始化"
            
            tags = query.strip()
            return await self._search_illust(tags, query, context)
            
        except Exception as e:
            logger.error(f"Pixiv插画搜索失败: {e}")
            return f"搜索失败: {str(e)}"

    async def _search_illust(self, tags, query, context):
        import asyncio
        try:
            search_result = await asyncio.to_thread(
                self.pixiv_client.search_illust,
                tags,
                search_target="partial_match_for_tags"
            )
            
            if search_result and search_result.illusts:
                event = self._get_event(context)
                if event:
                    return await self._send_pixiv_result(event, search_result.illusts, query, tags)
                else:
                    return self._format_text_results(search_result.illusts, query, tags)
            else:
                return f"未找到关于 '{query}' 的插画。"
        except Exception as e:
            return f"API调用错误: {str(e)}"

    async def _send_pixiv_result(self, event, items, query, tags):
        logger.info("PixivIllustSearchTool: 准备发送图片")
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
            detail_message = build_detail_message(selected_item, is_novel=False)
            
            title = getattr(selected_item, 'title', '未知标题')
            author = getattr(selected_item.user, 'name', '未知作者') if hasattr(selected_item, 'user') else '未知作者'
            item_id = getattr(selected_item, 'id', '未知ID')
            
            text_result = f"找到了！为您搜索到{query}的相关作品：\n\n**{title}** - {author}\n\nID: {item_id}\n您可以通过这个ID在Pixiv上查看完整内容。"
            
            try:
                results = []
                async for result in send_pixiv_image(
                    self.pixiv_client, event, selected_item, detail_message,
                    show_details=self.pixiv_config.show_details if self.pixiv_config else True
                ):
                    results.append(result)
                
                if results:
                    if hasattr(event, 'send'):
                        try:
                            await event.send(results[0])
                        except Exception as e:
                            logger.warning(f"手动发送图片失败: {e}")
                            return f"发送图片失败，但已找到结果: {text_result}"
                    return text_result
                return text_result
            except Exception as e:
                logger.error(f"发送失败: {e}")
                return text_result
        else:
            return f"找到插画但被过滤了 (可能是R18或AI作品)。"

    def _get_event(self, context):
        try:
            agent_context = context.context if hasattr(context, 'context') else context
            if hasattr(context, 'event') and context.event:
                return context.event
            elif hasattr(agent_context, 'event') and agent_context.event:
                return agent_context.event
        except:
            pass
        return None

    def _format_text_results(self, items, query, tags):
        result = f"找到以下插画:\n"
        for i, item in enumerate(items[:5], 1):
            title = getattr(item, 'title', '未知标题')
            result += f"{i}. {title} (ID: {item.id})\n"
        return result


@dataclass
class PixivNovelSearchTool(FunctionTool[AstrAgentContext]):
    """
    Pixiv小说搜索工具
    """
    pixiv_client: Any = None
    pixiv_config: Any = None

    name: str = "pixiv_search_novel"
    description: str = "Pixiv小说搜索工具。用于搜索Pixiv上的小说，或者通过ID直接下载小说。支持输入关键词或纯数字ID。"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或小说ID（纯数字）。",
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
            logger.info(f"Pixiv小说搜索工具：搜索 '{query}'")
            
            if not self.pixiv_client:
                return "错误: Pixiv客户端未初始化"
            
            tags = query.strip()
            return await self._search_novel(tags, query, context)
            
        except Exception as e:
            logger.error(f"Pixiv小说搜索失败: {e}")
            return f"搜索失败: {str(e)}"

    async def _search_novel(self, tags, query, context):
        import asyncio
        
        # ID 检查
        if query.isdigit():
            logger.info(f"检测到小说ID {query}")
            try:
                novel_detail = await asyncio.to_thread(self.pixiv_client.novel_detail, int(query))
                if novel_detail and novel_detail.novel:
                    event = self._get_event(context)
                    if event:
                        return await self._send_novel_result(event, [novel_detail.novel], query, tags)
                    else:
                        return f"找到小说: {novel_detail.novel.title} (ID: {query})，但无法发送文件(无事件上下文)。"
                else:
                    return f"未找到ID为 {query} 的小说。"
            except Exception as e:
                return f"获取小说详情失败: {str(e)}"
        
        # 标签搜索
        try:
            search_result = await asyncio.to_thread(
                self.pixiv_client.search_novel,
                tags,
                search_target="partial_match_for_tags"
            )
            
            if search_result and search_result.novels:
                event = self._get_event(context)
                if event:
                    return await self._send_novel_result(event, search_result.novels, query, tags)
                else:
                    return self._format_text_results(search_result.novels, query, tags)
            else:
                return f"未找到关于 '{query}' 的小说。"
        except Exception as e:
            return f"API调用错误: {str(e)}"

    async def _send_novel_result(self, event, items, query, tags):
        import asyncio
        if not items:
            return "未找到小说。"
        
        selected_item = items[0] # 取第一个
        novel_id = str(selected_item.id)
        novel_title = selected_item.title
        
        logger.info(f"准备下载小说 {novel_title} (ID: {novel_id})")
        
        try:
            novel_content_result = await asyncio.to_thread(self.pixiv_client.webview_novel, novel_id)
            if not novel_content_result or not hasattr(novel_content_result, "text"):
                return f"无法获取小说内容 (ID: {novel_id})。"
            
            novel_text = novel_content_result.text
            
            try:
                pdf_bytes = await asyncio.to_thread(self._create_pdf_from_text, novel_title, novel_text)
            except FileNotFoundError:
                return "无法生成PDF：字体文件丢失。"
            except Exception as e:
                return f"生成PDF失败: {str(e)}"
            
            # 加密
            password = hashlib.md5(novel_id.encode()).hexdigest()
            final_pdf_bytes = pdf_bytes
            password_notice = ""
            try:
                from PyPDF2 import PdfReader, PdfWriter
                reader = PdfReader(io.BytesIO(pdf_bytes))
                writer = PdfWriter()
                for page in reader.pages:
                    writer.add_page(page)
                writer.encrypt(password)
                with io.BytesIO() as bs:
                    writer.write(bs)
                    final_pdf_bytes = bs.getvalue()
                password_notice = f"PDF已加密，密码: {password}"
            except:
                password_notice = "PDF未加密。"
            
            # 发送
            safe_title = generate_safe_filename(novel_title, "novel")
            file_name = f"{safe_title}_{novel_id}.pdf"
            
            file_sent = False
            if event.get_platform_name() == "aiocqhttp" and event.get_group_id():
                try:
                    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
                    if isinstance(event, AiocqhttpMessageEvent):
                        client_bot = event.bot
                        group_id = event.get_group_id()
                        file_base64 = base64.b64encode(final_pdf_bytes).decode('utf-8')
                        await client_bot.upload_group_file(group_id=group_id, file=f"base64://{file_base64}", name=file_name)
                        file_sent = True
                except Exception as e:
                    logger.error(f"群文件上传失败: {e}")
            
            author = getattr(selected_item.user, 'name', '未知作者') if hasattr(selected_item, 'user') else '未知作者'
            
            if file_sent:
                return f"已下载小说：\n**{novel_title}** - {author}\nID: {novel_id}\n文件已上传到群文件。\n{password_notice}\n(任务完成)"
            else:
                return f"已找到小说：\n**{novel_title}** - {author}\nID: {novel_id}\n无法发送文件，请尝试手动下载。\n(任务完成)"
                
        except Exception as e:
            logger.error(f"处理小说失败: {e}")
            return f"处理小说失败: {str(e)}"

    def _create_pdf_from_text(self, title: str, text: str) -> bytes:
        font_path = Path(__file__).parent.parent / "data" / "SmileySans-Oblique.ttf"
        if not font_path.exists():
            raise FileNotFoundError(f"字体文件不存在: {font_path}")

        pdf = FPDF()
        pdf.add_page()
        pdf.add_font("SmileySans", "", str(font_path), uni=True)
        pdf.set_font("SmileySans", size=20)
        pdf.multi_cell(0, 10, title, align="C")
        pdf.ln(10)
        pdf.set_font_size(12)
        pdf.multi_cell(0, 10, text)
        return pdf.output(dest='S')

    def _get_event(self, context):
        try:
            agent_context = context.context if hasattr(context, 'context') else context
            if hasattr(context, 'event') and context.event:
                return context.event
            elif hasattr(agent_context, 'event') and agent_context.event:
                return agent_context.event
        except:
            pass
        return None

    def _format_text_results(self, items, query, tags):
        result = f"找到以下小说:\n"
        for i, item in enumerate(items[:5], 1):
            title = getattr(item, 'title', '未知标题')
            result += f"{i}. {title} (ID: {item.id})\n"
        return result

def create_pixiv_llm_tools(pixiv_client=None, pixiv_config=None) -> List[FunctionTool]:
    """
    创建Pixiv相关的LLM工具列表
    """
    logger.info(f"创建Pixiv LLM工具，pixiv_client: {'已设置' if pixiv_client else '未设置'}")
    
    tools = [
        PixivIllustSearchTool(pixiv_client=pixiv_client, pixiv_config=pixiv_config),
        PixivNovelSearchTool(pixiv_client=pixiv_client, pixiv_config=pixiv_config),
    ]
    logger.info(f"已创建 {len(tools)} 个LLM工具")
    return tools