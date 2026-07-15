"""Deterministic local media production agents.

These agents turn uploaded product imagery into real, browser-playable MP4 output.
They intentionally use local Pillow/FFmpeg processing so the core production path
still works when an optional external image/video model is unavailable.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Dict, Optional

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from app.agents.contracts import AgentResult, AgentSpec


UPLOAD_ROOT = Path(os.getenv("ADAGENTFLOW_UPLOAD_DIR", "var/uploads")).resolve()
GENERATED_ROOT = Path(os.getenv("ADAGENTFLOW_GENERATED_DIR", "var/generated")).resolve()
WEB_ASSET_ROOT = (Path(__file__).resolve().parents[1] / "web" / "dist" / "assets").resolve()


def _result(output: Dict[str, Any], started: float, model: str) -> AgentResult:
    return AgentResult(
        success=True,
        output=output,
        latency_ms=int((time.perf_counter() - started) * 1000),
        model=model,
        prompt_version="media-v1",
    )


def _failure(exc: Exception, started: float, model: str) -> AgentResult:
    return AgentResult(
        success=False,
        failure_reason="MEDIA_PRODUCTION_ERROR",
        error_message=str(exc),
        latency_ms=int((time.perf_counter() - started) * 1000),
        model=model,
        prompt_version="media-v1",
        needs_retry=True,
    )


def _product_asset_path(url: str) -> Path:
    """Resolve a user upload or a trusted, bundled demo image."""
    roots = []
    if url.startswith("/uploads/"):
        roots.append(UPLOAD_ROOT)
    elif url.startswith("/web/assets/"):
        roots.append(WEB_ASSET_ROOT)
    else:
        raise ValueError("商品素材必须来自站内上传或内置示例素材")

    root = roots[0]
    path = (root / Path(url).name).resolve()
    if path.parent != root or not path.is_file():
        raise FileNotFoundError(f"找不到商品素材: {url}")
    return path


def _render_frames(source_path: Path, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(source_path) as opened:
        source = ImageOps.exif_transpose(opened).convert("RGB")
        frames = []
        for index in range(3):
            background = ImageOps.fit(source, (720, 1280), method=Image.Resampling.LANCZOS)
            background = background.filter(ImageFilter.GaussianBlur(24))
            background = ImageEnhance.Brightness(background).enhance(0.32 + index * 0.05)

            foreground = source.copy()
            max_size = (620, 820) if index != 1 else (690, 980)
            foreground.thumbnail(max_size, Image.Resampling.LANCZOS)
            foreground = ImageEnhance.Contrast(foreground).enhance(1.04)
            x = (720 - foreground.width) // 2
            y_positions = [220, 145, 300]
            y = min(y_positions[index], 1280 - foreground.height - 80)
            background.paste(foreground, (x, max(80, y)))

            # Restrained monochrome treatment consistent with the product UI.
            if index == 2:
                background = ImageOps.grayscale(background).convert("RGB")
            frame_path = output_dir / f"frame-{index + 1:02d}.jpg"
            background.save(frame_path, "JPEG", quality=91, optimize=True)
            frames.append(frame_path)
        return frames


def _run_ffmpeg(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout)[-1200:]
        raise RuntimeError(f"FFmpeg 处理失败: {detail}")


class ImageGenerationAgent:
    step_id = "image_generation"
    prompt_version = "media-v1"

    def __init__(self, *, spec: Optional[AgentSpec] = None):
        self.spec = spec

    async def run(self, ctx: Dict[str, Any], tracer=None) -> AgentResult:
        started = time.perf_counter()
        try:
            assets = ctx.get("product", {}).get("product_assets") or []
            if not assets:
                raise ValueError("至少需要一张商品图片才能生产画面")
            source = _product_asset_path(assets[0])
            task_dir = GENERATED_ROOT / ctx["task_id"]
            frames = await asyncio.to_thread(_render_frames, source, task_dir / "frames")
            return _result({
                "frames": [f"/generated/{ctx['task_id']}/frames/{path.name}" for path in frames],
                "source_asset": assets[0],
                "count": len(frames),
                "resolution": "720x1280",
            }, started, "pillow-local-v1")
        except Exception as exc:
            return _failure(exc, started, "pillow-local-v1")


class VideoGenerationAgent:
    step_id = "video_generation"
    prompt_version = "media-v1"

    def __init__(self, *, spec: Optional[AgentSpec] = None):
        self.spec = spec

    async def run(self, ctx: Dict[str, Any], tracer=None) -> AgentResult:
        started = time.perf_counter()
        try:
            task_id = ctx["task_id"]
            frame_urls = ctx.get("history", {}).get("image_generation", {}).get("frames") or []
            if not frame_urls:
                raise ValueError("图片生成节点没有产出可用画面")
            duration = max(5, min(60, int(ctx.get("product", {}).get("duration", 15))))
            clip_seconds = duration / len(frame_urls)
            clip_dir = GENERATED_ROOT / task_id / "clips"
            clip_dir.mkdir(parents=True, exist_ok=True)
            clips = []
            for index, frame_url in enumerate(frame_urls):
                frame = GENERATED_ROOT / task_id / "frames" / Path(frame_url).name
                clip = clip_dir / f"clip-{index + 1:02d}.mp4"
                command = [
                    "ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(frame),
                    "-t", f"{clip_seconds:.3f}", "-r", "25", "-vf", "scale=720:1280",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(clip),
                ]
                await asyncio.to_thread(_run_ffmpeg, command)
                clips.append(f"/generated/{task_id}/clips/{clip.name}")
            return _result({
                "clips": clips,
                "count": len(clips),
                "duration_seconds": duration,
                "codec": "H.264",
            }, started, "ffmpeg-local-v1")
        except Exception as exc:
            return _failure(exc, started, "ffmpeg-local-v1")


class CompositionAgent:
    step_id = "composition"
    prompt_version = "media-v1"

    def __init__(self, *, spec: Optional[AgentSpec] = None):
        self.spec = spec

    async def run(self, ctx: Dict[str, Any], tracer=None) -> AgentResult:
        started = time.perf_counter()
        try:
            task_id = ctx["task_id"]
            task_dir = GENERATED_ROOT / task_id
            clip_urls = ctx.get("history", {}).get("video_generation", {}).get("clips") or []
            if not clip_urls:
                raise ValueError("视频生成节点没有产出可用片段")
            clip_paths = [task_dir / "clips" / Path(url).name for url in clip_urls]
            concat_file = task_dir / "concat.txt"
            concat_file.write_text("".join(f"file '{path.as_posix()}'\n" for path in clip_paths), encoding="utf-8")
            final_path = task_dir / "final.mp4"
            command = [
                "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                "-i", str(concat_file), "-c", "copy", "-movflags", "+faststart", str(final_path),
            ]
            await asyncio.to_thread(_run_ffmpeg, command)
            poster = ctx.get("history", {}).get("image_generation", {}).get("frames", [None])[0]
            return _result({
                "final_video_url": f"/generated/{task_id}/final.mp4",
                "poster_url": poster,
                "duration_seconds": ctx.get("history", {}).get("video_generation", {}).get("duration_seconds"),
                "format": "MP4",
                "codec": "H.264",
                "size_bytes": final_path.stat().st_size,
            }, started, "ffmpeg-compose-v1")
        except Exception as exc:
            return _failure(exc, started, "ffmpeg-compose-v1")
