import os
import shutil
import subprocess
import base64
from pathlib import Path
from typing import List, Tuple
from google.genai import Client
from google.genai.interactions import Interaction


# 1. Initialize the client
# (Make sure your GEMINI_API_KEY environment variable is set - use RISK_BOYS_API_KEY to set it like this: export GEMINI_API_KEY="YOUR_API_KEY")
client = Client()
DEFAULT_MODEL = "gemini-omni-flash-preview"

def cut_intro(script: str, *, delimiter: str = "--INTRO") -> Tuple[str, List[str]]:
    """
    Extracts intro to the script. The intro is at the top of the script, 
     and is separated by --INTRO from the rest. 
    """

    if script is None:
        raise TypeError("script must be a string, got None")
    if not isinstance(script, str):
        raise TypeError(f"script must be a string, got {type(script)!r}")

    normalized = script.replace("\r\n", "\n").replace("\r", "\n").strip()
    parts = [p.strip() for p in normalized.split(delimiter)]
    if len(parts) == 1:
        raise ValueError(
            f"No intro found. Expected delimiter {delimiter!r} in script."
        )

    intro = parts[0].strip()

    return intro, parts[1]  # the parts[1:] should really be just 1 element.


def cut_scenes(script: str, *, delimiter: str = "--SCENE") -> List[str]:
    """
    Split a script into a list of scene chunks.

    The script is expected to be delimited by `delimiter`. Each chunk is treated as a scene.

    Example format:

        --SCENE
        Scene 1 text...

        --SCENE
        Scene 2 text...

    Args:
        script: Full script text containing one or more scenes.
        delimiter: Scene delimiter token.

    Returns:
        scenes is a list of non-empty scene strings (whitespace-trimmed)

    Raises:
        ValueError: if no scenes are found.
    """

    if script is None:
        raise TypeError("script must be a string, got None")
    if not isinstance(script, str):
        raise TypeError(f"script must be a string, got {type(script)!r}")

    # Normalize newlines for consistency
    normalized = script.replace("\r\n", "\n").replace("\r", "\n").strip()

    parts = [p.strip() for p in normalized.split(delimiter) if p.strip() != ""]

    return parts


def cut_scene(
    script: str, *, 
    delimiter_prelude: str = "--PRELUDE", 
    delimiter_dialogue: str = "--DIALOGUE"
) -> Tuple[str, List[str]]:

    """
    Split a script into a prelude and a dialogue chunk.

    The script is expected to be delimited by `delimiter_prelude` and `delimiter_dialogue`. 
    Everything before the first delimiter is treated as the "prelude" (movie-wide context like characters/setting).
    Everything after the second delimiter is treated as the "dialogue" (the actual scene dialogue).

    Example format:

        Prelude about the movie, characters, setting...

        --PRELUDE
        Scene description...

        --DIALOGUE
        Scene dialogue...
    """

    if script is None:
        raise TypeError("script must be a string, got None")
    if not isinstance(script, str):
        raise TypeError(f"script must be a string, got {type(script)!r}")

    # Normalize newlines for consistency
    normalized = script.replace("\r\n", "\n").replace("\r", "\n").strip()

    parts = [p.strip() for p in normalized.split(delimiter_prelude)]
    if len(parts) == 1:
        raise ValueError(
            f"No prelude found. Expected delimiter {delimiter_prelude!r} in script."
        )

    prelude = parts[0].strip()
    dialogue_parts = [p.strip() for p in parts[1].split(delimiter_dialogue)]
    if len(dialogue_parts) == 1:
        raise ValueError(
            f"No dialogue found. Expected delimiter {delimiter_dialogue!r} in script."
        )

    return prelude, dialogue_parts


def cut_script(
    script: str, 
    *, 
    intro_delimiter: str = "--INTRO",
    scene_delimiter: str = "--SCENE",
    prelude_delimiter: str = "--PRELUDE",
    dialogue_delimiter: str = "--DIALOGUE",
    ) -> Tuple[str, List[str]]:
    """
    Split a script into a prelude and a list of scene chunks.

    The script is expected to be delimited by `intro_delimiter` and `scene_delimiter`. Everything before the first
    delimiter is treated as the "prelude" (movie-wide context like characters/setting).

    Example format:

        Prelude about the movie, characters, setting...

        --INTRO
        Scene 1 text...

        --SCENE
        Scene 2 text...

        --DIALOGUE 
        scene is split in dialogue bits. this is to help the model 
        since it's restricted by time.

    Args:
        script: Full script text containing a prelude and one or more scenes.
        intro_delimiter: Intro delimiter token.
        scene_delimiter: Scene delimiter token.
        dialogue_delimiter: Dialogue delimiter token.

    Returns:
        (prelude, scenes) where:
          - prelude is a string (may be empty)
          - scenes is a list of non-empty scene strings (whitespace-trimmed)

    Raises:
        ValueError: if no scenes are found.
    """

    # Normalize newlines for consistency
    normalized = script.replace("\r\n", "\n").replace("\r", "\n").strip()

    intro, rest = cut_intro(normalized, delimiter=intro_delimiter)
    scenes: List[str] = cut_scenes(rest, delimiter=scene_delimiter)
    scene_splits = []
    for scene in scenes:
        scene_splits.append(
            cut_scene(scene, 
                      delimiter_prelude=prelude_delimiter, 
                      delimiter_dialogue=dialogue_delimiter
                      )
        )

    return intro, scene_splits


def generate_scene(
    dialogue: str,  # dialogue of the scene
    context: str,  # context of the series.
    scene_descr: str,
    output_fname: str,  # output of the veo scene.
    previous_video_id: str | None = None,
    model=DEFAULT_MODEL,
) -> Interaction:

    combined_prompt = f"""The following is the context of the overall series:

    {context}

    ----------
    The following is the scene description:
    {scene_descr}

    ----------
    Implement only the following dialogue between characters (character names precede the text described):

    {dialogue}
    """

    operation = client.interactions.create(
        model=model,
        input=combined_prompt,
        previous_interaction_id=previous_video_id,
    )  # this is gonna block

    with open(output_fname, "wb") as f:
        generated_video = operation.output_video.data
        video_bytes = base64.b64decode(generated_video)
        f.write(video_bytes)

    return operation.id

def stitch_scenes(
    intro: str,
    scenes: List[Tuple[str, List[str]]],
    *,
    output_path: str | os.PathLike = "stitched.mp4",
    work_dir: str | os.PathLike = "out/scenes",
    scene_basename: str = "scene",
    video_ext: str = ".mp4",
    fps: int | None = None,
    model: str = DEFAULT_MODEL,
    video_params: dict | None = None,
) -> str:
    """
    Generate one video per prompt via `generate_scene()` and stitch them into a single MP4.

    This uses `ffmpeg`'s concat demuxer, which avoids re-encoding when possible.
    If `fps` is provided, it will force a consistent output frame rate (requires re-encode).

    Returns:
        The output file path as a string.
    """

    work_dir_path = Path(work_dir)
    work_dir_path.mkdir(parents=True, exist_ok=True)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    video_params = video_params or {
        "duration_seconds": 8,
        "number_of_videos": 1,
        "enhance_prompt": True,
    }

    # 1) Generate each scene
    scene_paths: list[Path] = []
    scene_id = None  # initial scene_id, 
    for scene_idx, (scene_descr, dialogue_splits) in enumerate(scenes, start=1):
        for dialog_idx, dialogue in enumerate(dialogue_splits, start=1):
            # Ensure we always write an MP4 path (generate_scene writes raw bytes as provided).
            scene_path = work_dir_path / f"{scene_basename}_{scene_idx:03d}_{dialog_idx:03d}{video_ext}"
            print(f"Generating: {scene_path}")
            try: 
                new_scene_id = generate_scene(
                    dialogue=dialogue,
                    context=intro or "",
                    scene_descr=scene_descr,
                    output_fname=str(scene_path),
                    model=model,
                    previous_video_id=scene_id,
                )
                scene_id = new_scene_id  # chain the next scene to the previous one
                scene_paths.append(scene_path)
            except Exception as e:  
                print(f"Error generating scene {scene_idx}, dialogue {dialog_idx}: {e}")
                continue  # Skip to the next dialogue split

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
    script = open("script/three_scenes.txt", "r").read()
    prelude, scenes = cut_script(script)
    scene_descr = scenes[0]
    scene = scenes[1]
    gen_video = generate_scene(
        dialogue=scene,
        context=prelude,
        scene_descr=scene_descr,
        output_fname="s1.mp4",
    )  # generates the video and saves it to scene_11.mp4


def main_test():
    script = open("script/four_scenes.txt", "r").read()
    intro, rest = cut_intro(script)
    scenes = cut_scenes(rest)
    prelude, dialogue_splits_scene1 = cut_scene(scenes[0])

    print(len(dialogue_splits_scene1))


# example of a working production
def main_working():
    script = open("script/five_scenes.txt", "r").read()
    intro, scenes = cut_script(script)
    # print(scenes)
    stitch_scenes(intro=intro, scenes=scenes, work_dir="out/scenes4")

main_working()
