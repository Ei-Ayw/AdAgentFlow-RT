"""商品与参考视频素材上传 API。"""
from pathlib import Path
from typing import Literal
import os
import uuid

from fastapi import APIRouter, File, HTTPException, Query, UploadFile


router = APIRouter()
UPLOAD_ROOT = Path(os.getenv("ADAGENTFLOW_UPLOAD_DIR", "var/uploads")).resolve()
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
VIDEO_TYPES = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
}
LIMITS = {"product": 20 * 1024 * 1024, "reference": 200 * 1024 * 1024}


@router.post("/upload")
async def upload_asset(
    file: UploadFile = File(...),
    kind: Literal["product", "reference"] = Query("product"),
):
    """保存创作素材，并返回可持久化到任务输入中的站内 URL。"""
    allowed = IMAGE_TYPES if kind == "product" else VIDEO_TYPES
    content_type = (file.content_type or "").lower()
    if content_type not in allowed:
        expected = "JPG、PNG、WEBP" if kind == "product" else "MP4、MOV、WEBM"
        raise HTTPException(415, f"不支持该文件类型，请上传 {expected}")

    asset_id = uuid.uuid4().hex
    destination = UPLOAD_ROOT / f"{asset_id}{allowed[content_type]}"
    size = 0
    try:
        with destination.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > LIMITS[kind]:
                    raise HTTPException(
                        413,
                        "商品图片不能超过 20MB" if kind == "product" else "参考视频不能超过 200MB",
                    )
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    return {
        "asset_id": asset_id,
        "name": file.filename or destination.name,
        "kind": kind,
        "content_type": content_type,
        "size": size,
        "url": f"/uploads/{destination.name}",
    }
