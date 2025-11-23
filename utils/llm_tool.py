from typing import Any, List, Union
from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.api import logger

from .tag import build_detail_message, FilterConfig, filter_illusts_with_reason, sample_illusts
from .pixiv_utils import send_pixiv_image

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
            search_result = await asyncio.to_thread(
                self.pixiv_client.search_novel,
                tags,
                search_target="partial_match_for_tags"
            )
            
            if search_result and search_result.novels:
                event = self._get_event(context)
                
                if event:
                    return await self._send_pixiv_result(
                        event, search_result.novels, query, tags, is_novel=True
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
                        # 尝试手动发送图片结果，确保Agent能收到文本回复的同时图片也能发出
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