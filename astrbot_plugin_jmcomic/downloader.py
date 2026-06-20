"""JM 漫画下载 + ZIP 打包封装"""
import os
from typing import Tuple

from ._imports import ensure_jmcomic_import


async def download_and_zip(
    jm_id: str,
    config: dict,
) -> Tuple[str, str, int]:
    """
    异步下载漫画并打包 ZIP。

    :param jm_id: JM 漫画 ID
    :param config: 插件配置字典
    :returns: (album_name, zip_file_path, file_size_in_bytes)
    """
    ensure_jmcomic_import(config)

    from jmcomic import JmModuleConfig, download_album_async
    from jmcomic.jm_feature import PluginFeature
    from jmcomic.jm_plugin import ZipPlugin

    # ---- 1. 构建下载目录 ----
    download_dir = os.path.abspath(config.get("download_dir", "./jm_downloads"))
    zip_dir = os.path.abspath(config.get("zip_dir", download_dir))

    # ---- 2. 记录下载前的 ZIP 文件，用于定位新生成的 ZIP ----
    existing_zips: set = set()
    if os.path.isdir(zip_dir):
        existing_zips = {os.path.join(zip_dir, f) for f in os.listdir(zip_dir) if f.endswith(".zip")}

    # ---- 3. 构建 JmOption ----
    client_domain_str: str = (config.get("client_domain", "") or "").strip()
    client_domains = [d.strip() for d in client_domain_str.split(",") if d.strip()] if client_domain_str else []

    proxy = (config.get("proxy", "") or "").strip() or None
    cookies = (config.get("cookies", "") or "").strip() or None

    client_config: dict = {
        "impl": "api",
        "retry_times": config.get("retry_times", 5),
    }
    if client_domains:
        client_config["domain"] = {"api": client_domains}

    postman_meta: dict = {"impersonate": "chrome"}
    if proxy:
        postman_meta["proxies"] = {"https://": proxy}
    if cookies:
        postman_meta["cookies"] = cookies
    client_config["postman"] = {"type": "curl_cffi", "meta_data": postman_meta}

    option_dict = {
        "dir_rule": {
            "base_dir": download_dir,
            "rule": "Bd_Aauthor_Ptitle_Pindex",
        },
        "download": {
            "cache": True,
            "image": {"decode": True},
            "threading": {
                "image": config.get("image_concurrency", 30),
                "photo": config.get("photo_concurrency", 8),
            },
        },
        "client": client_config,
    }

    option = JmModuleConfig.option_class().construct(option_dict)

    # ---- 4. 构建 ZIP Feature ----
    zip_feature = PluginFeature(
        ZipPlugin.plugin_key,
        zip_dir=zip_dir,
        delete_original_file=True,
        filename_rule="Atitle",
        suffix="zip",
    )

    # ---- 5. 执行下载 ----
    album, dler = await download_album_async(
        jm_id,
        option,
        extra=zip_feature,
        check_exception=True,
    )

    # ---- 6. 定位生成的 ZIP 文件 ----
    zip_path = ""
    if os.path.isdir(zip_dir):
        current_zips = {os.path.join(zip_dir, f) for f in os.listdir(zip_dir) if f.endswith(".zip")}
        new_zips = current_zips - existing_zips
        if new_zips:
            zip_path = max(new_zips, key=os.path.getmtime)

    if not zip_path or not os.path.isfile(zip_path):
        # fallback: 按漫画名构造预期路径
        safe_name = _sanitize_filename(album.name)
        zip_path = os.path.join(zip_dir, f"{safe_name}.zip")

    file_size = os.path.getsize(zip_path) if os.path.isfile(zip_path) else 0

    return album.name, zip_path, file_size


def _sanitize_filename(name: str) -> str:
    """移除文件名中的非法字符"""
    illegal = '<>:"/\\|?*'
    for ch in illegal:
        name = name.replace(ch, "_")
    return name.strip().rstrip(".")
