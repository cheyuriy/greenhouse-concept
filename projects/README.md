# Projects (fallback workspace)

Spec projects normally live in a **workspace** outside this repo — their own
git repo, marked by a `greenhouse.toml`:

```bash
uv run greenhouse workspace init ~/specs --use   # mark it, point this checkout at it
git -C ~/specs init                              # make it a repo when ready
```

This folder is only the zero-config fallback: with no workspace configured,
`greenhouse new` scaffolds here and everything under it is git-ignored, so the
tooling repo stays shareable. See `uv run greenhouse workspace show`.
