import os
import asyncio
from astrbot.api import logger
from pathlib import Path


async def clean_temp_dir(temp_dir: Path, max_files: int = 20) -> None:
    """
    异步清理临时目录，保持文件数量在指定限制内。
    
    Args:
        temp_dir: 要清理的目录的 Path 对象。
        max_files: 最大保留文件数量。
    """
    if not temp_dir.exists():
        return
        
    try:
        # 使用 asyncio.to_thread 进行异步文件操作
        files = await asyncio.to_thread(_get_temp_files, temp_dir)
        
        if len(files) > max_files:
            # 按创建时间排序，删除最旧的文件
            files_to_delete = await asyncio.to_thread(_sort_files_by_ctime, files)
            num_to_delete = len(files_to_delete) - max_files
            
            for i in range(num_to_delete):
                try:
                    await asyncio.to_thread(os.remove, files_to_delete[i])
                    logger.debug(f"[PixivPlugin] 已删除临时文件: {files_to_delete[i]}")
                except OSError as e:
                    logger.warning(f"[PixivPlugin] 删除临时图片失败: {files_to_delete[i]}，原因: {e}")
                    
            logger.info(f"[PixivPlugin] 临时目录清理完成，删除了 {num_to_delete} 个文件")
            
    except Exception as e:
        logger.error(f"[PixivPlugin] 清理临时目录时发生错误: {e}", exc_info=True)


def _get_temp_files(temp_dir: Path) -> list[str]:
    """获取临时目录中的所有文件路径"""
    return [str(f) for f in temp_dir.iterdir() if f.is_file()]


def _sort_files_by_ctime(files: list[str]) -> list[str]:
    """按创建时间排序文件列表"""
    return sorted(files, key=lambda x: os.path.getctime(x))


async def smart_clean_temp_dir(temp_dir: Path, probability: float = 0.1, max_files: int = 20) -> None:
    """
    智能清理临时目录，使用概率性触发以减少频繁的文件系统操作。
    
    Args:
        temp_dir: 要清理的目录的 Path 对象。
        probability: 触发清理的概率 (0.0-1.0)。
        max_files: 最大保留文件数量。
    """
    import random
    
    if random.random() < probability:
        await clean_temp_dir(temp_dir, max_files)
