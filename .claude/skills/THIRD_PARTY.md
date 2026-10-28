# Third-party design skills

Vendored copies, pinned to the commits below. Update by re-copying from the
upstream repo at a newer commit; licenses are in `_licenses/`.

| Skills | Upstream | Commit |
|---|---|---|
| `emil-design-eng`, `animate`, `review-animations`, `improve-animations`, `find-animation-opportunities`, `animation-performance`, `animation-vocabulary`, `animate-expo`, `apple-design`, `ask-sonner`, `break-ui`, `mobile-native`, `pick-ui-library`, `prototype`, `write-swift` | [emilkowalski/skills](https://github.com/emilkowalski/skills) | `2d228630ba1446365f614a108cb8252f1feda202` |
| `impeccable` (+ `../agents/impeccable-*.md`) | [pbakaus/impeccable](https://github.com/pbakaus/impeccable) | `5adaee704634e9031ec8943721c4ffa1a3c22221` |
| `taste-skill` (skill name `design-taste-frontend`) | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) | `12af471f627f866411b4bd785b19646d3672784c` |

Notes:

- Impeccable's design-detector hooks (upstream `.claude/settings.json`:
  SessionStart / PostToolUse / Stop) are deliberately **not** installed. They
  download and run the `impeccable` engine binary from GitHub releases on
  every edit. The skill's launcher still fetches that binary (sha256-checked
  against `impeccable/scripts/engine-checksums.txt`) the first time the skill
  runs `scripts/impeccable`. Enable the hooks per developer with
  `/impeccable hooks on` if wanted.
- `taste-skill` scripts need Node 22+; `scripts/assets.mjs` fetches openly
  licensed photos from Openverse, Wikimedia Commons, the Met, AIC, NASA and
  archive.org, and `scripts/inspect.mjs` drives a local Chromium for browser
  checks.
