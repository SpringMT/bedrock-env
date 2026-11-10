# Releasing to PyPI

Releases are built with `uv` and uploaded with `twine` from a local machine. GitHub Actions does not publish.

## Prerequisites

- [uv](https://docs.astral.sh/uv/)
- A PyPI account with 2FA enabled, and an API token. Create one at https://pypi.org/manage/account/token/
  - The first upload needs an "Entire account" token because the project does not exist yet. After that, replace it with a token scoped to `bedrock-env`.
- For TestPyPI (optional), a separate account and token at https://test.pypi.org/manage/account/token/
- `~/.pypirc` with the tokens, which `twine` reads:

```ini
[pypi]
username = __token__
password = pypi-XXXXXXXXXXXXXXXX

[testpypi]
username = __token__
password = pypi-XXXXXXXXXXXXXXXX
```

## Release Steps

### 1. Update version

Update the version in **both** files:

- `pyproject.toml` (`version = "X.Y.Z"`)
- `src/bedrock_env/__init__.py` (`__version__ = "X.Y.Z"`)

`uv version --bump patch` (or `minor` / `major`) updates `pyproject.toml` and `uv.lock`, but not `__init__.py`.

### 2. Run tests

```bash
uv run pytest -q
```

### 3. Commit and tag

```bash
git add pyproject.toml uv.lock src/bedrock_env/__init__.py
git commit -m "bump version to X.Y.Z"
git tag vX.Y.Z
git push origin main --tags
```

### 4. Clean previous builds

`twine upload dist/*` uploads everything in `dist/`, so remove old artifacts first.

```bash
rm -rf dist/
```

### 5. Build

```bash
uv build
```

This creates `dist/bedrock_env-X.Y.Z.tar.gz` and `dist/bedrock_env-X.Y.Z-py3-none-any.whl`.

### 6. Verify the package (optional)

```bash
uvx twine check dist/*
uv run --isolated --no-project --with dist/*.whl bedrock-env --version
```

### 7. Upload to TestPyPI (optional)

```bash
uvx twine upload --repository testpypi dist/*
```

Verify at https://test.pypi.org/project/bedrock-env/

### 8. Upload to PyPI

```bash
uvx twine upload dist/*
```

A version number can be uploaded only once. If a release is broken, bump the version and release again (and yank the broken one on PyPI).

### 9. Verify

```bash
uvx --refresh bedrock-env@X.Y.Z --version
```
