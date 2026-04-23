# Rentlio Overview HACS publishing checklist

## Current state from the uploaded package

### Good
- `custom_components/rentlio_overview/` exists
- `manifest.json` exists
- `config_flow.py` exists
- `brand/icon.png` exists
- `brand/logo.png` exists
- `translations/en.json` exists
- Only one integration is present in `custom_components/`

### Must fix before publishing
- Put `custom_components/` at the **repository root**
- Add a root `README.md`
- Add a root `hacs.json`
- Add GitHub workflow files for HACS validation and Hassfest
- Replace placeholder values in `custom_components/rentlio_overview/manifest.json`

## Manifest fields that must be updated
Replace these placeholders:
- `documentation`
- `issue_tracker`
- `codeowners`

Example:
```json
{
  "documentation": "https://github.com/<YOUR_GITHUB_USERNAME>/<YOUR_REPO_NAME>",
  "issue_tracker": "https://github.com/<YOUR_GITHUB_USERNAME>/<YOUR_REPO_NAME>/issues",
  "codeowners": ["@<YOUR_GITHUB_USERNAME>"]
}
```

## Recommended repository tree

```text
<repo-root>/
├── .github/
│   └── workflows/
│       ├── hassfest.yaml
│       └── validate.yaml
├── custom_components/
│   └── rentlio_overview/
│       ├── __init__.py
│       ├── api.py
│       ├── calendar.py
│       ├── config_flow.py
│       ├── const.py
│       ├── coordinator.py
│       ├── manifest.json
│       ├── sensor.py
│       ├── brand/
│       │   ├── icon.png
│       │   └── logo.png
│       └── translations/
│           └── en.json
├── hacs.json
└── README.md
```

## Important
The versioned wrapper folder used in your ZIP packages is fine for manual downloads, but it should **not** be part of the GitHub repository structure used by HACS.
