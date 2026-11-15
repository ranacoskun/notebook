# Graph publishing

Put `_graph/`, `.github/` and `.gitignore` in the root of your Obsidian vault.

Preview locally:
    pip install pyyaml
    python _graph/build.py
    cd _graph/site && python -m http.server 8000     # open http://localhost:8000

Online: push the vault to GitHub, then Settings -> Pages -> Source: GitHub Actions.
Every push rebuilds the site.

What counts as a graph link: only the properties listed in `schema.yaml`
(grounded_in, uses_method, measures, ...). Change that file to add relation types.
Links to notes that don't exist yet show up as faded dashed nodes.
