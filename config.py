import os
import json

# 1. 临时图片缓存目录，自动创建
TEMP_DIR = os.path.join(os.path.dirname(__file__), "tmp")
os.makedirs(TEMP_DIR, exist_ok=True)

# 2. 动态读取图片发送数量


def get_return_count():
    conf_path = os.path.join(os.path.dirname(__file__), "_conf_schema.json")
    with open(conf_path, "r", encoding="utf-8") as f:
        conf = json.load(f)
    val = conf.get("return_count", 1)
    if isinstance(val, dict):
        return val.get("default", 1)
    return int(val)


# 3. 缓存目录清理，保证最多20张图片


def clean_temp_dir(max_files=20):
    files = [
        os.path.join(TEMP_DIR, f)
        for f in os.listdir(TEMP_DIR)
        if os.path.isfile(os.path.join(TEMP_DIR, f))
    ]
    if len(files) >= max_files:
        files.sort(key=lambda x: os.path.getctime(x))
        for f in files[: len(files) - max_files + 1]:
            try:
                os.remove(f)
            except Exception as e:
                print(f"[PixivPlugin] 删除临时图片失败: {f}，原因: {e}")
