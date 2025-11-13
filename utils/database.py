import peewee as pw
from astrbot.api import logger
from astrbot.api.star import StarTools
from pathlib import Path

# 使用 StarTools 获取标准数据目录
data_dir = StarTools.get_data_dir("pixiv_search")
data_dir.mkdir(parents=True, exist_ok=True)

# 数据库文件路径
db_path = data_dir / "subscriptions.db"
db = pw.SqliteDatabase(str(db_path))

class BaseModel(pw.Model):
    class Meta:
        database = db

class Subscription(BaseModel):
    """订阅模型"""
    chat_id = pw.CharField()  # 订阅来源的聊天ID (群号或用户QQ号)
    session_id = pw.TextField()  # 用于发送通知的完整会话ID (JSON字符串)
    sub_type = pw.CharField()  # 订阅类型: 'artist'
    target_id = pw.CharField()  # 订阅目标 ID (画师ID)
    target_name = pw.CharField(null=True) # 订阅目标的名称（画师名）
    last_notified_illust_id = pw.BigIntegerField(default=0)  # 最后通知的作品 ID
    
    class Meta:
        primary_key = pw.CompositeKey('chat_id', 'sub_type', 'target_id')

def initialize_database():
    """初始化数据库，创建表"""
    try:
        db.connect(reuse_if_open=True)
        if not Subscription.table_exists():
            db.create_tables([Subscription])
            logger.info("数据库初始化成功，数据表已创建。")
        # 兼容旧版，检查并添加 chat_id 列
        elif 'chat_id' not in [c.name for c in db.get_columns('subscription')]:
             logger.info("正在更新数据库表结构，添加 chat_id 列...")
             db.evolve(
                 pw.SQL('ALTER TABLE subscription ADD COLUMN chat_id VARCHAR(255) DEFAULT ""')
             )
             logger.info("数据库表结构更新完成。")

    except Exception as e:
        logger.error(f"数据库初始化或迁移失败: {e}")
    finally:
        if not db.is_closed():
            db.close()

def add_subscription(chat_id: str, session_id_json: str, sub_type: str, target_id: str, target_name: str = None, initial_illust_id: int = 0) -> (bool, str):
    """
    添加订阅

    :param chat_id: 订阅来源的聊天ID
    :param session_id_json: 订阅者的会话ID (JSON字符串)
    :param sub_type: 订阅类型 (当前仅支持 'artist')
    :param target_id: 目标 ID
    :param target_name: 目标名称
    :param initial_illust_id: 初始的最后通知作品ID
    :return: (是否成功, 消息)
    """
    try:
        with db.atomic():
            Subscription.create(
                chat_id=chat_id,
                session_id=session_id_json,
                sub_type=sub_type,
                target_id=target_id,
                target_name=target_name or target_id,
                last_notified_illust_id=initial_illust_id
            )
        logger.info(f"聊天 {chat_id} 成功添加对 artist: {target_id} 的订阅，初始作品ID: {initial_illust_id}。")
        return True, f"成功订阅画师: {target_name or target_id}！"
    except pw.IntegrityError:
        logger.warning(f"聊天 {chat_id} 尝试重复订阅 artist: {target_id}。")
        return False, f"您已经订阅过画师: {target_name or target_id}。"
    except Exception as e:
        logger.error(f"添加订阅时发生错误: {e}")
        return False, f"添加订阅时发生未知错误: {e}"

def remove_subscription(chat_id: str, sub_type: str, target_id: str) -> (bool, str):
    """
    移除订阅

    :param chat_id: 订阅来源的聊天ID
    :param sub_type: 订阅类型 (当前仅支持 'artist')
    :param target_id: 目标 ID
    :return: (是否成功, 消息)
    """
    try:
        query = Subscription.delete().where(
            (Subscription.chat_id == chat_id) &
            (Subscription.sub_type == sub_type) &
            (Subscription.target_id == target_id)
        )
        deleted_rows = query.execute()
        if deleted_rows > 0:
            logger.info(f"聊天 {chat_id} 成功移除了对 artist: {target_id} 的订阅。")
            return True, f"成功取消对画师: {target_id} 的订阅。"
        else:
            logger.warning(f"聊天 {chat_id} 尝试移除不存在的订阅 artist: {target_id}。")
            return False, f"您没有订阅画师: {target_id}。"
    except Exception as e:
        logger.error(f"移除订阅时发生错误: {e}")
        return False, f"移除订阅时发生未知错误: {e}"

def list_subscriptions(chat_id: str) -> list:
    """
    列出指定聊天的订阅

    :param chat_id: 订阅来源的聊天ID
    :return: 订阅列表
    """
    try:
        subscriptions = Subscription.select().where(Subscription.chat_id == chat_id)
        return list(subscriptions)
    except Exception as e:
        logger.error(f"列出订阅时发生错误: {e}")
        return []

def get_all_subscriptions() -> list:
    """
    获取所有订阅
    """
    try:
        return list(Subscription.select())
    except Exception as e:
        logger.error(f"获取所有订阅时发生错误: {e}")
        return []

def update_last_notified_id(chat_id: str, sub_type: str, target_id: str, new_id: int):
    """
    更新最后通知的作品ID
    """
    try:
        query = Subscription.update(last_notified_illust_id=new_id).where(
            (Subscription.chat_id == chat_id) &
            (Subscription.sub_type == sub_type) &
            (Subscription.target_id == target_id)
        )
        query.execute()
    except Exception as e:
        logger.error(f"更新 last_notified_illust_id 时出错: {e}")