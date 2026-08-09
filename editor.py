import argparse
import os
import sys
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk

from movie.scene import generate_scene


@dataclass(frozen=True)
class SceneInputs:
    dialogue: str
    context: str
    scene_descr: str
    output_fname: str
    model: str
    duration_seconds: int
    number_of_videos: int
    start_image_path: str | None


def _read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="movie.editor",
        description=(
            "Simple GUI editor for running generate_scene() and saving the resulting video."
        ),
    )

    parser.add_argument("--dialogue", help="Dialogue text (overrides --dialogue-file).")
    parser.add_argument(
        "--dialogue-file", help="Path to a file containing the dialogue text."
    )

    parser.add_argument("--context", help="Context text (overrides --context-file).")
    parser.add_argument("--context-file", help="Path to a file containing the context.")

    parser.add_argument(
        "--scene-descr",
        help="Scene description text (overrides --scene-descr-file).",
    )
    parser.add_argument(
        "--scene-descr-file",
        help="Path to a file containing the scene description.",
    )

    parser.add_argument(
        "--output",
        default="out/scene.mp4",
        help="Output video filename (default: out/scene.mp4).",
    )
    parser.add_argument(
        "--model",
        default="veo-3.1-generate-preview",
        help="Model name (default: veo-3.1-generate-preview).",
    )

    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=8,
        help="Video duration in seconds (default: 8).",
    )
    parser.add_argument(
        "--number-of-videos",
        type=int,
        default=1,
        help="Number of videos to generate (default: 1).",
    )

    parser.add_argument(
        "--start-image",
        default=None,
        help="Optional start image path.",
    )

    return parser


def _coalesce_text(direct_text: str | None, file_path: str | None) -> str:
    if direct_text and direct_text.strip():
        return direct_text
    if file_path and file_path.strip():
        return _read_text_file(file_path)
    return ""


class EditorApp(tk.Tk):
    def __init__(self, defaults: SceneInputs) -> None:
        super().__init__()
        self.title("Scene Generator")
        self.geometry("980x760")

        self._defaults = defaults

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        root = ttk.Frame(self, padding=12)
        root.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)

        self._vars: dict[str, tk.Variable] = {
            "output_fname": tk.StringVar(value=defaults.output_fname),
            "model": tk.StringVar(value=defaults.model),
            "duration_seconds": tk.IntVar(value=defaults.duration_seconds),
            "number_of_videos": tk.IntVar(value=defaults.number_of_videos),
            "start_image_path": tk.StringVar(value=defaults.start_image_path or ""),
        }

        # Top fields
        fields = ttk.LabelFrame(root, text="Parameters", padding=10)
        fields.grid(row=0, column=0, sticky="ew")
        fields.columnconfigure(1, weight=1)

        ttk.Label(fields, text="Output file").grid(row=0, column=0, sticky="w", padx=6)
        out_entry = ttk.Entry(fields, textvariable=self._vars["output_fname"])
        out_entry.grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(fields, text="Browse...", command=self._browse_output).grid(
            row=0, column=2, sticky="e", padx=6
        )

        ttk.Label(fields, text="Model").grid(row=1, column=0, sticky="w", padx=6)
        ttk.Entry(fields, textvariable=self._vars["model"]).grid(
            row=1, column=1, sticky="ew", padx=6
        )

        ttk.Label(fields, text="Duration (seconds)").grid(
            row=2, column=0, sticky="w", padx=6
        )
        ttk.Spinbox(
            fields,
            from_=1,
            to=120,
            textvariable=self._vars["duration_seconds"],
            width=8,
        ).grid(row=2, column=1, sticky="w", padx=6)

        ttk.Label(fields, text="Number of videos").grid(
            row=3, column=0, sticky="w", padx=6
        )
        ttk.Spinbox(
            fields,
            from_=1,
            to=10,
            textvariable=self._vars["number_of_videos"],
            width=8,
        ).grid(row=3, column=1, sticky="w", padx=6)

        ttk.Label(fields, text="Start image (optional)").grid(
            row=4, column=0, sticky="w", padx=6
        )
        img_entry = ttk.Entry(fields, textvariable=self._vars["start_image_path"])
        img_entry.grid(row=4, column=1, sticky="ew", padx=6)
        ttk.Button(fields, text="Browse...", command=self._browse_image).grid(
            row=4, column=2, sticky="e", padx=6
        )

        # Text areas
        texts = ttk.LabelFrame(root, text="Scene Text", padding=10)
        texts.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        texts.columnconfigure(0, weight=1)
        texts.rowconfigure(1, weight=1)
        texts.rowconfigure(3, weight=1)
        texts.rowconfigure(5, weight=1)

        ttk.Label(texts, text="Context").grid(row=0, column=0, sticky="w")
        self._context = tk.Text(texts, height=8, wrap="word")
        self._context.grid(row=1, column=0, sticky="nsew")
        self._context.insert("1.0", defaults.context)

        ttk.Label(texts, text="Scene description").grid(row=2, column=0, sticky="w")
        self._scene_descr = tk.Text(texts, height=8, wrap="word")
        self._scene_descr.grid(row=3, column=0, sticky="nsew")
        self._scene_descr.insert("1.0", defaults.scene_descr)

        ttk.Label(texts, text="Dialogue").grid(row=4, column=0, sticky="w")
        self._dialogue = tk.Text(texts, height=10, wrap="word")
        self._dialogue.grid(row=5, column=0, sticky="nsew")
        self._dialogue.insert("1.0", defaults.dialogue)

        # Actions
        actions = ttk.Frame(root)
        actions.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        actions.columnconfigure(0, weight=1)

        self._status = tk.StringVar(value="Ready.")
        ttk.Label(actions, textvariable=self._status).grid(
            row=0, column=0, sticky="w"
        )

        self._render_btn = ttk.Button(actions, text="Generate", command=self._render)
        self._render_btn.grid(row=0, column=1, sticky="e", padx=(12, 0))

    def _browse_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Choose output mp4",
            defaultextension=".mp4",
            filetypes=[("MP4 files", "*.mp4"), ("All files", "*.*")],
        )
        if path:
            self._vars["output_fname"].set(path)

    def _browse_image(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose start image",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.webp *.bmp"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self._vars["start_image_path"].set(path)

    def _render(self) -> None:
        dialogue = self._dialogue.get("1.0", "end").strip()
        context = self._context.get("1.0", "end").strip()
        scene_descr = self._scene_descr.get("1.0", "end").strip()

        output_fname = str(self._vars["output_fname"].get()).strip()
        model = str(self._vars["model"].get()).strip()

        duration_seconds = int(self._vars["duration_seconds"].get())
        number_of_videos = int(self._vars["number_of_videos"].get())

        start_image_path = str(self._vars["start_image_path"].get()).strip() or None

        if not output_fname:
            messagebox.showerror("Missing output", "Output file is required.")
            return

        out_dir = os.path.dirname(output_fname)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        if not dialogue:
            messagebox.showerror("Missing dialogue", "Dialogue is required.")
            return
        if not scene_descr:
            messagebox.showerror(
                "Missing scene description", "Scene description is required."
            )
            return

        if start_image_path is not None and not os.path.exists(start_image_path):
            messagebox.showerror("Missing file", f"Start image not found: {start_image_path}")
            return

        self._render_btn.configure(state="disabled")
        self._status.set("Rendering... (this can take a while)")

        try:
            generate_scene(
                dialogue=dialogue,
                context=context,
                scene_descr=scene_descr,
                output_fname=output_fname,
                model=model,
                video_params={
                    "duration_seconds": duration_seconds,
                    "number_of_videos": number_of_videos,
                },
                start_image_path=start_image_path,
            )
        except Exception as e:
            messagebox.showerror("Render failed", f"{type(e).__name__}: {e}")
            self._status.set("Render failed.")
            return
        finally:
            self._render_btn.configure(state="normal")

        self._status.set(f"Done. Saved: {output_fname}")
        messagebox.showinfo("Render complete", f"Saved video to:\n{output_fname}")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    defaults = SceneInputs(
        dialogue=_coalesce_text(args.dialogue, args.dialogue_file),
        context=_coalesce_text(args.context, args.context_file),
        scene_descr=_coalesce_text(args.scene_descr, args.scene_descr_file),
        output_fname=args.output,
        model=args.model,
        duration_seconds=args.duration_seconds,
        number_of_videos=args.number_of_videos,
        start_image_path=args.start_image,
    )

    app = EditorApp(defaults)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
