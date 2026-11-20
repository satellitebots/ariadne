# Status and roadmap

## Proven

- The full suite: **295 tests**, model-free, in about three minutes.
- The drill: brief -> plan -> sign-off -> execute -> gates, proven against a scripted model with `HERMES_EXE` pointed
  at a path that does not exist (the fallback runtime path).
- The worker on Hermes: `hermes.exe` at the pin reports v0.23.2 and `import run_agent` resolves; the default runner is
  `hermes_run`.
- The overlay: an overlaid module wins while the rest still resolves upstream, with the ledger checked by tests.
- The model index on this machine: RTX 3070 Laptop, 8 GB VRAM, 31.9 GB RAM - 4 models `gpu`, 6 `hybrid`, none too
  large.

## Deferred (needs the GPU or a live model)

- The first end-to-end run of each flow against a real model.
- Watchdog thresholds under real VRAM pressure.
- A live CI provider (Jenkins/GitHub/GitLab) and a live embedding model.
- The LAN smoke test.

## Next

- The first real overlay entry, when a module genuinely has to differ.
- Optionally, moving `hermes_run` from the `hermes` CLI to in-process `AIAgent`; the bootstrap and overlay are
  already in place for it.
- Keep this wiki honest as the code moves.
