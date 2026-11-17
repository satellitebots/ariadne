# Ariadne

A local-only agent harness built on [Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research.

Ariadne does not fork Hermes. It runs a pinned, unmodified Hermes (`upstream\`, see `hermes.lock`) and adds:
plugins (graph memory, context engine, offline guard, routing), workflow profiles (coding, designing, writing,
investigating), a skill tap, LAN model serving configs and an offline install bundle.

- Plan and rules: `PLAN.md`
- Progress: `WORKLOG.md`

## License

Hermes Agent is MIT-licensed, Copyright (c) 2025 Nous Research; its license is in `upstream\LICENSE` and ships
with any Ariadne bundle. Ariadne's own code: Copyright (c) 2026 Adnan Alam. License to be decided.
