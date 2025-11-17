from typing import Any, List, Union
from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.api import logger

# 导入必要的模块
from .tag import build_detail_message, FilterConfig, filter_illusts_with_reason, sample_illusts
from .pixiv_utils import send_pixiv_image

# 定义ToolExecResult类型别名，与AstrBot框架保持一致
ToolExecResult = Union[str, Any]

# 全局变量存储Pixiv客户端
_GLOBAL_PIXIV_CLIENT = None

def set_global_pixiv_client(client):
    """设置全局Pixiv客户端"""
    global _GLOBAL_PIXIV_CLIENT
    _GLOBAL_PIXIV_CLIENT = client
    logger.info(f"设置全局Pixiv客户端: {'已设置' if client else '未设置'}")

def get_global_pixiv_client():
    """获取全局Pixiv客户端"""
    return _GLOBAL_PIXIV_CLIENT


@dataclass
class PixivLLMTool(FunctionTool[AstrAgentContext]):
    """
    Pixiv LLM工具，用于处理与Pixiv相关的自然语言查询和生成描述
    """
    name: str = "pixiv_llm_tool"  # 工具名称
    description: str = "一个用于处理Pixiv相关查询和生成描述的LLM工具"  # 工具描述
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "要执行的操作类型，如 'describe', 'analyze', 'recommend' 等",
                },
                "content": {
                    "type": "string",
                    "description": "要处理的内容，如作品描述、标签等",
                },
                "context": {
                    "type": "string",
                    "description": "额外的上下文信息",
                },
            },
            "required": ["action", "content"],
        }
    )

    def __init__(self, pixiv_client=None):
        """初始化Pixiv LLM工具"""
        super().__init__()
        self.pixiv_client = pixiv_client
        logger.info(f"PixivLLMTool初始化，pixiv_client: {'已设置' if pixiv_client else '未设置'}")

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        """
        调用LLM工具处理Pixiv相关请求
        
        Args:
            context: AstrBot上下文包装器
            **kwargs: 包含action, content, context等参数
            
        Returns:
            ToolExecResult: 工具执行结果
        """
        try:
            action = kwargs.get("action", "")
            content = kwargs.get("content", "")
            extra_context = kwargs.get("context", "")
            
            logger.info(f"Pixiv LLM工具：执行操作 '{action}'，内容长度: {len(content)}")
            
            # 尝试从上下文获取pixiv_client
            pixiv_client = None
            
            # 首先尝试从自身属性获取
            if hasattr(self, 'pixiv_client') and self.pixiv_client is not None:
                pixiv_client = self.pixiv_client
            else:
                # 尝试从上下文获取插件实例，然后获取客户端
                try:
                    # 获取AstrAgentContext
                    agent_context = context.context if hasattr(context, 'context') else context
                    
                    # 尝试从agent_context获取插件实例
                    if hasattr(agent_context, 'plugin_instance') and agent_context.plugin_instance:
                        plugin_instance = agent_context.plugin_instance
                        if hasattr(plugin_instance, 'client'):
                            pixiv_client = plugin_instance.client
                            logger.info("PixivLLMTool: 从上下文获取到pixiv_client")
                    
                    # 如果上述方法失败，尝试从agent_context的star属性获取
                    elif hasattr(agent_context, 'star') and agent_context.star:
                        plugin_instance = agent_context.star
                        if hasattr(plugin_instance, 'client'):
                            pixiv_client = plugin_instance.client
                            logger.info("PixivLLMTool: 从star属性获取到pixiv_client")
                    
                except Exception as e:
                    logger.warning(f"PixivLLMTool: 从上下文获取pixiv_client失败: {e}")
            
            # 如果仍然无法获取客户端，尝试从全局变量获取
            if pixiv_client is None:
                pixiv_client = get_global_pixiv_client()
                if pixiv_client:
                    logger.info("PixivLLMTool: 从全局变量获取到pixiv_client")
            
            # 根据不同的操作类型处理请求
            if action == "describe":
                result = await self._generate_description(content, extra_context)
            elif action == "analyze":
                result = await self._analyze_content(content, extra_context)
            elif action == "recommend":
                result = await self._generate_recommendations(content, extra_context)
            elif action == "summarize":
                result = await self._summarize_content(content, extra_context)
            elif action == "translate":
                result = await self._translate_content(content, extra_context)
            else:
                result = f"不支持的操作类型: {action}。支持的操作类型: describe, analyze, recommend, summarize, translate"
            
            logger.info(f"Pixiv LLM工具：操作完成，结果长度: {len(result)}")
            return result
            
        except Exception as e:
            error_msg = f"Pixiv LLM工具执行失败: {str(e)}"
            logger.error(error_msg)
            return error_msg

    async def _generate_description(self, content: str, context: str = "") -> str:
        """为Pixiv作品生成描述"""
        # 这里可以集成实际的LLM API，目前返回模拟结果
        return f"基于内容生成的描述: {content[:50]}... 这是一个精美的Pixiv作品，展现了独特的艺术风格和创意。"

    async def _analyze_content(self, content: str, context: str = "") -> str:
        """分析Pixiv作品内容"""
        # 模拟分析结果
        return f"内容分析: 该作品可能包含{len(content)}个字符的描述，艺术风格独特，色彩搭配和谐。"

    async def _generate_recommendations(self, content: str, context: str = "") -> str:
        """基于内容生成推荐"""
        # 模拟推荐结果
        return "基于您的内容，推荐以下相关作品: 1. 相似风格作品 2. 相同标签作品 3. 同作者其他作品"

    async def _summarize_content(self, content: str, context: str = "") -> str:
        """总结内容"""
        # 模拟总结结果
        if len(content) > 100:
            return f"内容摘要: {content[:100]}..."
        else:
            return f"内容摘要: {content}"

    async def _translate_content(self, content: str, context: str = "") -> str:
        """翻译内容"""
        # 模拟翻译结果
        return f"翻译结果: [翻译] {content}"


@dataclass
class PixivSearchTool(FunctionTool[AstrAgentContext]):
    """
    Pixiv搜索工具，用于智能搜索Pixiv作品
    """
    name: str = "pixiv_search"  # 工具名称
    description: str = "一个用于智能搜索Pixiv作品的工具"  # 工具描述
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询，可以是自然语言描述",
                },
                "search_type": {
                    "type": "string",
                    "description": "搜索类型，如 'illust', 'novel', 'user' 等",
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

    def __init__(self, pixiv_client=None):
        """初始化Pixiv搜索工具"""
        super().__init__()
        self.pixiv_client = pixiv_client
        logger.info(f"PixivSearchTool初始化，pixiv_client: {'已设置' if pixiv_client else '未设置'}")
        # 存储上下文信息用于LLM调用
        self._last_context = None

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        """
        调用搜索工具处理Pixiv搜索请求，返回实际图片和正确标题
        
        Args:
            context: AstrBot上下文包装器
            **kwargs: 包含query, search_type, filters等参数
            
        Returns:
            ToolExecResult: 工具执行结果
        """
        try:
            query = kwargs.get("query", "")
            search_type = kwargs.get("search_type", "illust")
            filters = kwargs.get("filters", "")
            
            # 存储上下文信息，供_convert_query_to_tags使用
            self._last_context = context
            
            logger.info(f"Pixiv搜索工具：搜索 '{query}'，类型: {search_type}")
            
            # 获取Pixiv客户端
            pixiv_client = self._get_pixiv_client(context)
            if not pixiv_client:
                logger.error("PixivSearchTool: 无法获取pixiv_client")
                return "错误: Pixiv客户端未初始化，无法执行搜索"
            
            # 使用LLM将自然语言查询转换为Pixiv标签
            tags = await self._convert_query_to_tags(query)
            
            # 调用实际的Pixiv API搜索
            if search_type == "illust":
                try:
                    import asyncio
                    search_result = await asyncio.to_thread(
                        pixiv_client.search_illust,
                        tags,
                        search_target="partial_match_for_tags"
                    )
                    
                    if search_result and search_result.illusts:
                        # 获取事件对象和配置
                        event, plugin_config = self._get_event_and_config(context)
                        
                        # 如果有事件对象，尝试发送实际图片
                        if event:
                            return await self._send_pixiv_result(
                                pixiv_client, event, plugin_config,
                                search_result.illusts, query, tags
                            )
                        else:
                            logger.warning("PixivSearchTool: 未找到事件对象，无法发送图片")
                            return self._format_text_results(search_result.illusts, query, tags)
                    else:
                        return f"根据查询 '{query}' 转换的标签 '{tags}' 未找到相关作品。"
                except Exception as api_error:
                    logger.error(f"Pixiv API调用失败: {api_error}")
                    return f"搜索时发生API错误: {str(api_error)}"
            else:
                return f"搜索结果: 找到与 '{query}' 相关的{search_type}作品。\n转换的标签: {tags}"
            
        except Exception as e:
            error_msg = f"Pixiv搜索工具执行失败: {str(e)}"
            logger.error(error_msg)
            return error_msg
    
    def _get_pixiv_client(self, context):
        """获取Pixiv客户端"""
        # 首先尝试从自身属性获取
        if hasattr(self, 'pixiv_client') and self.pixiv_client is not None:
            return self.pixiv_client
        
        # 尝试从全局变量获取
        pixiv_client = get_global_pixiv_client()
        if pixiv_client:
            return pixiv_client
        
        return None
    
    def _get_event_and_config(self, context):
        """获取事件对象和配置"""
        event = None
        plugin_config = None
        
        try:
            # 获取AstrAgentContext
            agent_context = context.context if hasattr(context, 'context') else context
            
            # 尝试获取事件对象
            if hasattr(context, 'event') and context.event:
                event = context.event
            elif hasattr(agent_context, 'event') and agent_context.event:
                event = agent_context.event
            
            # 尝试获取插件配置
            if hasattr(agent_context, 'plugin_instance') and agent_context.plugin_instance:
                plugin_instance = agent_context.plugin_instance
                if hasattr(plugin_instance, 'pixiv_config'):
                    plugin_config = plugin_instance.pixiv_config
            elif hasattr(agent_context, 'star') and agent_context.star:
                plugin_instance = agent_context.star
                if hasattr(plugin_instance, 'pixiv_config'):
                    plugin_config = plugin_instance.pixiv_config
                    
        except Exception as e:
            logger.warning(f"PixivSearchTool: 获取事件对象和配置时出错: {e}")
        
        return event, plugin_config
    
    async def _send_pixiv_result(self, pixiv_client, event, plugin_config, illusts, query, tags):
        """发送Pixiv搜索结果"""
        logger.info("PixivSearchTool: 找到事件对象，准备发送图片")
        
        # 使用过滤配置
        config = FilterConfig(
            r18_mode=plugin_config.r18_mode if plugin_config else "过滤 R18",
            ai_filter_mode=plugin_config.ai_filter_mode if plugin_config else "过滤 AI 作品",
            display_tag_str=f"搜索:{query}",
            return_count=plugin_config.return_count if plugin_config else 1,
            logger=logger,
            show_filter_result=False,
            excluded_tags=[]
        )
        
        # 过滤作品
        filtered_illusts, _ = filter_illusts_with_reason(illusts, config)
        
        if filtered_illusts:
            # 随机选择一个作品
            selected_illust = sample_illusts(filtered_illusts, 1, shuffle=True)[0]
            
            # 构建详情消息
            detail_message = build_detail_message(selected_illust, is_novel=False)
            
            # 获取作品信息用于返回
            title = getattr(selected_illust, 'title', '未知标题')
            author = getattr(selected_illust.user, 'name', '未知作者') if hasattr(selected_illust, 'user') else '未知作者'
            illust_id = getattr(selected_illust, 'id', '未知ID')
            
            # 构建返回给Agent的文本信息
            text_result = f"找到了！为您搜索到{query}的相关作品：\n\n**{title}** - {author}\n\n作品ID: {illust_id}\n您可以通过这个ID在Pixiv上查看完整的图片内容。"
            
            # 尝试发送图片
            try:
                logger.info("PixivSearchTool: 开始发送图片")
                
                # 直接发送图片并收集结果
                results = []
                async for result in send_pixiv_image(
                    pixiv_client, event, selected_illust, detail_message,
                    show_details=plugin_config.show_details if plugin_config else True
                ):
                    results.append(result)
                    logger.info(f"PixivSearchTool: 获取到发送结果: {type(result)}")
                
                # 如果有发送结果，返回第一个结果（通常是图片和描述）
                if results:
                    return results[0]
                else:
                    return text_result
                    
            except Exception as send_error:
                logger.error(f"发送图片失败: {send_error}")
                # 如果发送图片失败，返回文本信息
                return text_result
            
        else:
            return f"根据查询 '{query}' 转换的标签 '{tags}' 找到作品，但都被过滤了。"
    
    
    def _format_text_results(self, illusts, query, tags):
        """格式化文本结果"""
        result = f"根据查询 '{query}' 转换的标签 '{tags}' 找到以下作品:\n\n"
        for i, illust in enumerate(illusts[:5], 1):
            # 使用build_detail_message获取正确标题
            detail_msg = build_detail_message(illust, is_novel=False)
            # 提取标题 - 从detail_msg中提取第一行的标题
            title = getattr(illust, 'title', '未知标题')
            if title == '无题' and detail_msg:
                # 尝试从detail_msg中提取标题
                lines = detail_msg.split('\n')
                if lines and lines[0].strip():
                    title = lines[0].strip()
            
            author = getattr(illust.user, 'name', '未知作者') if hasattr(illust, 'user') else '未知作者'
            illust_id = getattr(illust, 'id', '未知ID')
            result += f"{i}. {title} - {author} (ID: {illust_id})\n"
        
        if len(illusts) > 5:
            result += f"\n... 还有 {len(illusts) - 5} 个作品"
        
        return result
    
    async def _convert_query_to_tags(self, query: str) -> str:
        """
        使用AstrBot LLM API将自然语言查询转换为Pixiv标签
        
        Args:
            query: 自然语言查询
            
        Returns:
            str: 转换后的标签
        """
        # 添加缓存机制，避免重复调用LLM
        # 使用更简单的缓存键，只取查询的前20个字符以避免键过长
        cache_key = f"tag_conversion_{query[:20].strip()}"
        if hasattr(self, '_tag_cache') and cache_key in self._tag_cache:
            logger.info(f"使用缓存的标签转换结果: '{query}' -> '{self._tag_cache[cache_key]}'")
            return self._tag_cache[cache_key]
        
        # 初始化缓存
        if not hasattr(self, '_tag_cache'):
            self._tag_cache = {}
        
        # 构建转换提示词
        prompt = f"""请将以下自然语言查询转换为适合Pixiv搜索的标签。

查询: {query}

要求:
1. 准确翻译查询中的关键词
2. 优先使用日语标签（如: 女の子, 風景, 可愛い）
3. 标签之间用空格分隔
4. 只返回翻译后的标签，不要添加额外的标签
5. 不要添加任何其他文字

标签:"""
        
        try:
            # 获取上下文和事件对象
            actual_context = self._get_actual_context()
            if not actual_context:
                logger.warning("无法获取AstrAgentContext，使用原查询作为标签")
                result = query.strip()
                self._tag_cache[cache_key] = result
                return result
            
            # 获取聊天模型ID
            provider_id = await self._get_chat_provider_id(actual_context)
            
            # 调用LLM生成标签
            logger.info(f"开始调用LLM转换标签，provider_id: {provider_id}")
            llm_resp = await actual_context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
            logger.info("LLM调用成功")
            
            if llm_resp and hasattr(llm_resp, 'completion_text'):
                translated_tags = llm_resp.completion_text.strip()
                logger.info(f"LLM转换标签成功: '{query}' -> '{translated_tags}'")
                
                # 检查翻译结果是否有效
                if translated_tags and translated_tags != query:
                    # 同时使用原查询和翻译后的标签，提高搜索成功率
                    combined_tags = f"{query.strip()} {translated_tags}"
                    logger.info(f"组合搜索标签: '{combined_tags}'")
                    # 缓存结果
                    self._tag_cache[cache_key] = combined_tags
                    return combined_tags
                else:
                    logger.warning("LLM返回的翻译结果无效，使用原查询")
                    result = query.strip()
                    self._tag_cache[cache_key] = result
                    return result
            
            logger.warning("LLM返回空响应，使用原查询作为标签")
            result = query.strip()
            self._tag_cache[cache_key] = result
            return result
            
        except Exception as e:
            logger.error(f"LLM转换标签时发生错误: {e}")
            # 当LLM调用失败时，直接使用原查询
            result = query.strip()
            self._tag_cache[cache_key] = result
            return result
    
    def _get_actual_context(self):
        """获取实际的AstrAgentContext"""
        if not hasattr(self, '_last_context') or not self._last_context:
            return None
            
        agent_context = self._last_context.context if hasattr(self._last_context, 'context') else self._last_context
        
        if hasattr(agent_context, 'context'):
            return agent_context.context
        
        return agent_context if hasattr(agent_context, 'llm_generate') else None
    
    async def _get_chat_provider_id(self, actual_context):
        """获取聊天模型ID"""
        try:
            # 尝试从上下文中获取事件对象
            event = getattr(actual_context, 'event', None)
            if not event and hasattr(self, '_last_context') and self._last_context:
                agent_context = self._last_context.context if hasattr(self._last_context, 'context') else self._last_context
                event = getattr(agent_context, 'event', None)
            
            if event and hasattr(event, 'unified_msg_origin'):
                umo = event.unified_msg_origin
                return await actual_context.get_current_chat_provider_id(umo=umo)
        except Exception as e:
            logger.warning(f"获取聊天模型ID失败: {e}")
        
        return None
    



def create_pixiv_llm_tools(pixiv_client=None, pixiv_config=None) -> List[FunctionTool]:
    """
    创建Pixiv相关的LLM工具列表
    
    Args:
        pixiv_client: Pixiv API客户端
        pixiv_config: Pixiv配置对象
        
    Returns:
        List[FunctionTool]: 工具列表
    """
    logger.info(f"创建Pixiv LLM工具，pixiv_client: {'已设置' if pixiv_client else '未设置'}")
    
    # 设置全局Pixiv客户端
    set_global_pixiv_client(pixiv_client)
    
    tools = [
        PixivLLMTool(pixiv_client=pixiv_client),
        PixivSearchTool(pixiv_client=pixiv_client),
    ]
    logger.info(f"已创建 {len(tools)} 个LLM工具")
    return tools