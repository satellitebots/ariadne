"""MCP server: generate images with SD Turbo through stable-diffusion.cpp (stdio). Run: python -m ariadne.image_mcp

Frees the GPU first (asks llama-swap to unload its model), so only one model is on the GPU at a time."""
import subprocess
import urllib.request
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from . import paths

server = MCPServer("ariadne-image", instructions="Generate an image from a text prompt with SD Turbo (local GPU).")


def _size_error(width, height):
    for name, v in (("width", width), ("height", height)):
        if v % 64 or not 256 <= v <= 1024:
            return f"{name} must be a multiple of 64 between 256 and 1024 (got {v})"
    return ""


def _free_gpu():
    try:
        url = paths.LLM_BASE_URL.removesuffix("/v1") + "/api/models/unload"
        urllib.request.urlopen(urllib.request.Request(url, data=b"", method="POST"), timeout=30)
    except Exception:
        pass


@server.tool()
def generate_image(prompt: str, output: str, width: int = 512, height: int = 512, seed: int = -1) -> str:
    """Render `prompt` to the PNG file `output` (width/height: multiples of 64, 256-1024). Returns the path."""
    from .deps import find_bin
    err = _size_error(width, height)
    if err:
        return err
    sd = find_bin("sd.cpp", "sd-cli")
    model = paths.MODELS / "sd_turbo.safetensors"
    if not sd or not model.exists():
        return "SD Turbo is not installed: run  python -m ariadne install"
    _free_gpu()
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    args = [str(sd), "-m", str(model), "-p", prompt, "-o", str(out), "-W", str(width), "-H", str(height),
            "--steps", "1", "--cfg-scale", "1.0", "--sampling-method", "euler_a", "-s", str(seed)]
    p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    if p.returncode != 0 or not out.exists():
        return f"sd-cli failed (exit {p.returncode}): {p.stderr[-2000:]}"
    return f"wrote {out} ({out.stat().st_size} bytes)"


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
