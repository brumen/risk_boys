import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import List, Tuple
from google import genai
from google.genai import types

# 1. Initialize the client
# (Make sure your GEMINI_API_KEY environment variable is set)
client = genai.Client()


def cut_script(script: str, *, delimiter: str = "--SWITCH") -> Tuple[str, List[str]]:
    """
    Split a script into a prelude and a list of scene chunks.

    The script is expected to be delimited by `delimiter`. Everything before the first
    delimiter is treated as the "prelude" (movie-wide context like characters/setting).

    Example format:

        Prelude about the movie, characters, setting...

        ---CUT_SCENE
        Scene 1 text...

        ---CUT_SCENE
        Scene 2 text...

    Args:
        script: Full script text containing a prelude and one or more scenes.
        delimiter: Scene delimiter token.

    Returns:
        (prelude, scenes) where:
          - prelude is a string (may be empty)
          - scenes is a list of non-empty scene strings (whitespace-trimmed)

    Raises:
        ValueError: if no scenes are found.
    """
    if script is None:
        raise TypeError("script must be a string, got None")
    if not isinstance(script, str):
        raise TypeError(f"script must be a string, got {type(script)!r}")

    # Normalize newlines for consistency
    normalized = script.replace("\r\n", "\n").replace("\r", "\n").strip()

    parts = [p.strip() for p in normalized.split(delimiter)]
    if len(parts) == 1:
        raise ValueError(
            f"No scenes found. Expected delimiter {delimiter!r} in script."
        )

    prelude = parts[0].strip()
    scenes = [p for p in parts[1:] if p.strip()]

    if not scenes:
        raise ValueError("No non-empty scenes found after the delimiter.")

    return prelude, scenes


def generate_scene(
    dialogue: str,  # dialogue of the scene
    context: str,  # conetxt of the series.
    scene_descr: str,
    output_fname: str,  # output of the veo scene.
    model="veo-3.1-generate-preview",
    video_params={
        "duration_seconds": 8,
        "number_of_videos": 1,
        # "enhance_prompt": True,
    },
    start_image_path=None,  # image with which the video is starting.
):

    combined_prompt = f"""The following is the context of the series:

    {context}

    ----------
    The following is the scene description:
    {scene_descr}

    ----------
    Implement only the following dialogue between characters (they precede the text described):

    {dialogue}
    """

    operation = client.models.generate_videos(
        model=model,
        prompt=combined_prompt,
        config=types.GenerateVideosConfig(**video_params),
        # source=source,
        image=types.Image.from_file(location=start_image_path),
    )

    while not operation.done:
        time.sleep(1)
        operation = client.operations.get(operation)
        print(f"Still processing {output_fname}...")

    # 4. Retrieve and save the generated video file
    generated_video = operation.response.generated_videos[0]
    video_bytes = client.files.download(file=generated_video.video.uri)
    with open(output_fname, "wb") as f:
        f.write(video_bytes)


def stich_scenes(
    prompts: list[str],
    *,
    output_path: str | os.PathLike = "stitched.mp4",
    work_dir: str | os.PathLike = "out/scenes",
    scene_basename: str = "scene",
    video_ext: str = ".mp4",
    fps: int | None = None,
    context: str | None = None,
    model: str = "veo-3.1-generate-preview",
    video_params: dict | None = None,
) -> str:
    """
    Generate one video per prompt via `generate_scene()` and stitch them into a single MP4.

    This uses `ffmpeg`'s concat demuxer, which avoids re-encoding when possible.
    If `fps` is provided, it will force a consistent output frame rate (requires re-encode).

    Returns:
        The output file path as a string.
    """
    if not prompts:
        raise ValueError("prompts must be a non-empty list of strings")

    work_dir_path = Path(work_dir)
    work_dir_path.mkdir(parents=True, exist_ok=True)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    video_params = video_params or {
        "duration_seconds": 6,
        "number_of_videos": 1,
        "enhance_prompt": True,
    }

    # 1) Generate each scene
    scene_paths: list[Path] = []
    for idx, prompt in enumerate(prompts, start=1):
        # Ensure we always write an MP4 path (generate_scene writes raw bytes as provided).
        scene_path = work_dir_path / f"{scene_basename}_{idx:03d}{video_ext}"
        generate_scene(
            prompt=prompt,
            context=context or "",
            output_fname=str(scene_path),
            model=model,
            video_params=video_params,
        )
        scene_paths.append(scene_path)

    # 2) Create concat list file for ffmpeg
    concat_list_path = work_dir_path / "concat_list.txt"
    concat_list_path.write_text(
        "".join([f"file '{p.resolve().as_posix()}'\n" for p in scene_paths]),
        encoding="utf-8",
    )

    # 3) Stitch via ffmpeg
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError(
            "ffmpeg not found on PATH. Install ffmpeg to stitch scenes "
            "(e.g., `sudo apt-get install -y ffmpeg`)."
        )

    cmd: list[str] = [
        ffmpeg_path,
        "-hide_banner",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list_path),
    ]

    if fps is None:
        # Fast path: stream copy (no re-encode). Requires compatible codecs/params across clips.
        cmd += ["-c", "copy"]
    else:
        # Force a uniform output. This re-encodes video (and audio if present) for compatibility.
        cmd += [
            "-r",
            str(fps),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
        ]

    cmd.append(str(output_path))

    subprocess.run(cmd, check=True)

    return str(output_path)


def main():
    script = open("three_scenes.txt", "r").read()
    prelude, scenes = cut_script(script)
    scene_descr = scenes[0]
    scene = scenes[1]
    gen_video = generate_scene(
        dialogue=scene,
        context=prelude,
        scene_descr=scene_descr,
        output_fname="scene_11.mp4",
        start_image_path="first_scene.jpg",
    )  # generates the video and saves it to scene_11.mp4
