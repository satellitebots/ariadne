"""MCP server: generate images through stable-diffusion.cpp with a catalog image model (stdio).
Run: python -m ariadne.image_mcp

Frees the GPU first (asks llama-swap to unload its model), so only one model is on the GPU at a time."""
import shlex
import subprocess
import urllib.request
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from . import models, paths

server = MCPServer("ariadne-image", instructions="Generate an image from a text prompt with a local image model.")

# catalog weight part -> sd-cli flag
FLAGS = {"model": "-m", "diffusion": "--diffusion-model", "llm": "--llm", "vae": "--vae", "clip_l": "--clip_l",
         "t5xxl": "--t5xxl"}


def _size_error(width, height):
    for name, v in (("width", width), ("height", height)):
        if v % 64 or not 256 <= v <= 1536:
            return f"{name} must be a multiple of 64 between 256 and 1536 (got {v})"
    return ""


def _free_gpu():
    try:
        url = paths.LLM_BASE_URL.removesuffix("/v1") + "/api/models/unload"
        urllib.request.urlopen(urllib.request.Request(url, data=b"", method="POST"), timeout=30)
    except Exception:
        pass


def sd_args(m, prompt, out, width, height, seed):
    args = []
    for part in m.parts:
        args += [FLAGS[part], str(m.part_path(part))]
    return args + ["-p", prompt, "-o", str(out), "-W", str(width), "-H", str(height), "-s", str(seed),
                   *shlex.split(m.sd_args)]


from .activity import instrument as _instrument  # noqa: E402
_instrument(server, "image")

@server.tool()
def generate_image(prompt: str, output: str, model: str = "", width: int = 1024, height: int = 1024,
                   seed: int = -1) -> str:
    """Render `prompt` to the PNG file `output`. model: an image model from the catalog (default: the catalog's
    image default, Z-Image-Turbo). width/height: multiples of 64, 256-1536. Returns the path."""
    from .deps import find_bin
    err = _size_error(width, height)
    if err:
        return err
    cat = models.load()
    try:
        m = cat.get(model or cat.default_for("image"))
    except models.ModelError as e:
        return str(e)
    if m.kind != "image":
        return f"{m.name} is not an image model"
    sd = find_bin("sd.cpp", "sd-cli")
    if not sd:
        return "stable-diffusion.cpp is not installed: run  python -m ariadne install"
    if not m.installed():
        return f"{m.name} is not installed: run  python -m ariadne models install {m.name}"
    _free_gpu()
    out = Path(output)
    if not out.is_absolute():  # a relative path would land in this server's own folder, not the workspace
        return f"output must be an absolute path inside your workspace (got '{output}')"
    out.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.run([str(sd), *sd_args(m, prompt, out, width, height, seed)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=1200)
    if p.returncode != 0 or not out.exists():
        return f"sd-cli failed (exit {p.returncode}): {p.stderr[-2000:]}"
    return f"wrote {out} ({out.stat().st_size} bytes) with {m.name}"


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
