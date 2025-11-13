import asyncio
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from astrbot.api import logger
from pixivpy3 import AppPixivAPI

from .database import get_all_subscriptions, update_last_notified_id
from .tag import build_detail_message

class SubscriptionService:
    def __init__(self, plugin_instance):
        self.plugin = plugin_instance
        self.scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self.job = None

    def start(self):
        """启动后台任务"""
        if not self.scheduler.running:
            self.job = self.scheduler.add_job(
                self.check_subscriptions,
                "interval",
                minutes=self.plugin.config.get("subscription_check_interval_minutes", 30),
                next_run_time=datetime.now() + timedelta(seconds=10) # 10秒后第一次运行
            )
            self.scheduler.start()

    def stop(self):
        """停止后台任务"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("订阅检查服务已停止。")

    async def check_subscriptions(self):
        """检查所有订阅并推送更新"""
        if not await self.plugin._authenticate():
            logger.error("订阅检查失败：Pixiv API 认证失败。")
            return

        subscriptions = get_all_subscriptions()
        if not subscriptions:
            return

        for sub in subscriptions:
            try:
                if sub.sub_type == 'artist':
                    await self.check_artist_updates(sub)
            except Exception as e:
                logger.error(f"检查订阅 {sub.sub_type}: {sub.target_id} 时发生错误: {e}")
            await asyncio.sleep(5)

    async def check_artist_updates(self, sub):
        """检查画师更新"""
        api: AppPixivAPI = self.plugin.client
        json_result = await asyncio.to_thread(api.user_illusts, sub.target_id)

        if not json_result or not json_result.illusts:
            return

        new_illusts = []
        for illust in json_result.illusts:
            if illust.id > sub.last_notified_illust_id:
                new_illusts.append(illust)
            else:
                break
        
        if new_illusts:
            new_illusts.reverse()
            latest_id = new_illusts[-1].id
            update_last_notified_id(sub.chat_id, sub.sub_type, sub.target_id, latest_id)

            for illust in new_illusts:
                filtered_illusts, _ = self.plugin.filter_items([illust], f"画师订阅: {sub.target_name}")
                if filtered_illusts:
                    await self.send_update(sub, filtered_illusts[0])
                    await asyncio.sleep(2)

    async def send_update(self, sub, illust):
        """发送更新通知"""
        try:
            # 导入 MessageChain 类
            from astrbot.core.message.message_event_result import MessageChain
            
            # 创建模拟事件对象（用于捕获消息链）
            class MockEvent:
                def chain_result(self, chain):
                    message_chain = MessageChain()
                    message_chain.chain = chain
                    return message_chain
                
                def plain_result(self, text):
                    message_chain = MessageChain()
                    message_chain.message(text)
                    return message_chain
                    
            mock_event = MockEvent()

            session_id_str = sub.session_id
            detail_message = f"您订阅的 {sub.sub_type} [{sub.target_name}] 有新作品啦！\n"
            detail_message += build_detail_message(illust, is_novel=False)

            # 使用 async for 循环来驱动 send_pixiv_image 生成器
            # 并通过 mock_event 捕获其 yield 的结果
            async for message_content in self.plugin.send_pixiv_image(
                mock_event, illust, detail_message, self.plugin.show_details
            ):
                if message_content:
                    if hasattr(message_content, 'chain'):
                        await self.plugin.context.send_message(session_id_str, message_content)
                    else:
                        # 如果不是 MessageChain 对象，创建一个
                        message_chain = MessageChain()
                        message_chain.message(str(message_content))
                        await self.plugin.context.send_message(session_id_str, message_chain)

        except Exception as e:
            logger.error(f"发送订阅更新时出错: {e}")
            import traceback
            logger.error(traceback.format_exc())
