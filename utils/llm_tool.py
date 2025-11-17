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
            
            logger.info(f"Pixiv搜索工具：搜索 '{query}'，类型: {search_type}")
            
            # 尝试从上下文获取pixiv_client
            pixiv_client = None
            agent_context = None
            
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
                            logger.info("PixivSearchTool: 从上下文获取到pixiv_client")
                    
                    # 如果上述方法失败，尝试从agent_context的star属性获取
                    elif hasattr(agent_context, 'star') and agent_context.star:
                        plugin_instance = agent_context.star
                        if hasattr(plugin_instance, 'client'):
                            pixiv_client = plugin_instance.client
                            logger.info("PixivSearchTool: 从star属性获取到pixiv_client")
                    
                except Exception as e:
                    logger.warning(f"PixivSearchTool: 从上下文获取pixiv_client失败: {e}")
            
            # 如果仍然无法获取客户端，尝试从全局变量获取
            if pixiv_client is None:
                pixiv_client = get_global_pixiv_client()
                if pixiv_client:
                    logger.info("PixivSearchTool: 从全局变量获取到pixiv_client")
            
            # 检查pixiv_client是否可用
            if pixiv_client is None:
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
                        # 尝试获取事件对象用于发送图片
                        event = None
                        plugin_config = None
                        
                        # 尝试多种方式获取事件对象和配置
                        try:
                            # 方法1: 从context获取
                            if hasattr(context, 'event') and context.event:
                                event = context.event
                                logger.info("PixivSearchTool: 从context.event获取到事件对象")
                            
                            # 方法2: 从agent_context获取
                            if not event and agent_context:
                                if hasattr(agent_context, 'event') and agent_context.event:
                                    event = agent_context.event
                                    logger.info("PixivSearchTool: 从agent_context.event获取到事件对象")
                                
                                # 尝试获取插件配置
                                if hasattr(agent_context, 'plugin_instance') and agent_context.plugin_instance:
                                    plugin_instance = agent_context.plugin_instance
                                    if hasattr(plugin_instance, 'pixiv_config'):
                                        plugin_config = plugin_instance.pixiv_config
                                        logger.info("PixivSearchTool: 从plugin_instance获取到配置")
                                elif hasattr(agent_context, 'star') and agent_context.star:
                                    plugin_instance = agent_context.star
                                    if hasattr(plugin_instance, 'pixiv_config'):
                                        plugin_config = plugin_instance.pixiv_config
                                        logger.info("PixivSearchTool: 从star获取到配置")
                            
                            # 方法3: 尝试从context的context属性获取
                            if not event and hasattr(context, 'context'):
                                inner_context = context.context
                                if hasattr(inner_context, 'event') and inner_context.event:
                                    event = inner_context.event
                                    logger.info("PixivSearchTool: 从context.context.event获取到事件对象")
                                    
                                if not plugin_config and hasattr(inner_context, 'plugin_instance') and inner_context.plugin_instance:
                                    plugin_instance = inner_context.plugin_instance
                                    if hasattr(plugin_instance, 'pixiv_config'):
                                        plugin_config = plugin_instance.pixiv_config
                                        logger.info("PixivSearchTool: 从context.context.plugin_instance获取到配置")
                                    
                            # 方法4: 尝试从context的任何属性中查找事件对象
                            if not event:
                                for attr_name in dir(context):
                                    if 'event' in attr_name.lower():
                                        try:
                                            attr_value = getattr(context, attr_name)
                                            if hasattr(attr_value, 'plain_result') or hasattr(attr_value, 'chain_result'):
                                                event = attr_value
                                                logger.info(f"PixivSearchTool: 从context.{attr_name}获取到事件对象")
                                                break
                                        except:
                                            continue
                            
                            # 方法5: 尝试从agent_context的任何属性中查找事件对象
                            if not event and agent_context:
                                for attr_name in dir(agent_context):
                                    if 'event' in attr_name.lower():
                                        try:
                                            attr_value = getattr(agent_context, attr_name)
                                            if hasattr(attr_value, 'plain_result') or hasattr(attr_value, 'chain_result'):
                                                event = attr_value
                                                logger.info(f"PixivSearchTool: 从agent_context.{attr_name}获取到事件对象")
                                                break
                                        except:
                                            continue
                            
                            # 方法6: 尝试从context的__dict__中查找事件对象
                            if not event:
                                for key, value in context.__dict__.items():
                                    if 'event' in key.lower() and hasattr(value, 'plain_result'):
                                        event = value
                                        logger.info(f"PixivSearchTool: 从context.__dict__.{key}获取到事件对象")
                                        break
                            
                            # 方法7: 尝试从agent_context的__dict__中查找事件对象
                            if not event and agent_context:
                                for key, value in agent_context.__dict__.items():
                                    if 'event' in key.lower() and hasattr(value, 'plain_result'):
                                        event = value
                                        logger.info(f"PixivSearchTool: 从agent_context.__dict__.{key}获取到事件对象")
                                        break
                        except Exception as e:
                            logger.warning(f"PixivSearchTool: 获取事件对象和配置时出错: {e}")
                        
                        # 如果有事件对象，尝试发送实际图片
                        if event:
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
                            filtered_illusts, _ = filter_illusts_with_reason(search_result.illusts, config)
                            
                            if filtered_illusts:
                                # 随机选择一个作品
                                selected_illust = sample_illusts(filtered_illusts, 1, shuffle=True)[0]
                                
                                # 构建详情消息
                                detail_message = build_detail_message(selected_illust, is_novel=False)
                                
                                # 尝试发送图片
                                try:
                                    logger.info("PixivSearchTool: 开始发送图片")
                                    # 直接发送图片，不使用嵌套的生成器
                                    sent_successfully = False
                                    results = []
                                    async for result in send_pixiv_image(
                                        pixiv_client, event, selected_illust, detail_message,
                                        show_details=plugin_config.show_details if plugin_config else True
                                    ):
                                        logger.info("PixivSearchTool: 图片发送成功")
                                        sent_successfully = True
                                        results.append(result)
                                    
                                    # 返回简单的文本结果，让Agent知道搜索成功
                                    if sent_successfully:
                                        # 如果有发送结果，返回第一个结果（通常是图片和描述）
                                        if results:
                                            return results[0]
                                        else:
                                            return f"已成功发送搜索结果: {detail_message.split()[0] if detail_message else 'Pixiv作品'}"
                                    else:
                                        return f"搜索完成但发送可能失败: {detail_message.split()[0] if detail_message else 'Pixiv作品'}"
                                        
                                except Exception as send_error:
                                    logger.error(f"发送图片失败: {send_error}")
                                    # 如果发送图片失败，返回文本信息
                                    return f"找到作品但发送图片失败: {detail_message}"
                            else:
                                return f"根据查询 '{query}' 转换的标签 '{tags}' 找到作品，但都被过滤了。"
                        else:
                            logger.warning("PixivSearchTool: 未找到事件对象，无法发送图片")
                            
                            # 没有事件对象，返回文本描述
                            result = f"根据查询 '{query}' 转换的标签 '{tags}' 找到以下作品:\n\n"
                            for i, illust in enumerate(search_result.illusts[:5], 1):
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
                            
                            if len(search_result.illusts) > 5:
                                result += f"\n... 还有 {len(search_result.illusts) - 5} 个作品"
                            
                            return result
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
    
    async def _convert_query_to_tags(self, query: str) -> str:
        """
        将自然语言查询转换为Pixiv标签
        
        Args:
            query: 自然语言查询
            
        Returns:
            str: 转换后的标签
        """
        # 这里可以集成实际的LLM API进行转换
        # 目前使用简单的关键词映射
        query_lower = query.lower()
        
        # 简单的关键词映射
        tag_mapping = {
            "蓝色头发": "蓝色头发",
            "少女": "少女",
            "风景": "風景",
            "猫": "猫",
            "可爱": "可愛い",
            "动漫": "オリジナル",
            "插画": "イラスト",
            "漫画": "漫画",
            "角色": "女の子",
        }
        
        # 提取关键词
        tags = []
        for keyword, tag in tag_mapping.items():
            if keyword in query_lower:
                tags.append(tag)
        
        # 如果没有匹配的关键词，使用原查询作为标签
        if not tags:
            tags = [query]
        
        return " ".join(tags)


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