# Releasing

mDisplay is published the way the owner's other mFruit OS apps are
(RadioConnect, AI Chatbot): a GitHub release whose tag matches the manifest
version, with the package archive and `SHA256SUMS`. The repository is
`github.com/Mengkungkao/mDisplay`.

## Steps

1. Bump `version` in `manifest.json` and `__version__` in `app/__init__.py`
   (a test checks they match) and add a `## [x.y.z]` section to
   `CHANGELOG.md` (it becomes the release notes).
2. `bash tools/check.sh` with an mFruit OS checkout; all checks pass.
3. Commit and push to `main` of `github.com/Mengkungkao/mDisplay`.
   `.github/workflows/release.yml` runs the checks, builds the package with
   `tools/build-release.sh` (mFruit OS's `check-app.py` + `test.sh` on the
   exact contents) and publishes `v<version>` with
   `mdisplay-<version>.tar.gz` and `SHA256SUMS`. Never tag by hand.
4. Add the GitHub topic `whisplay-app` so mFruit OS can discover it.

Locally: `bash tools/build-release.sh` writes the same files to `dist/`;
`mfruitctl sideload dist/mdisplay-<version>.tar.gz` installs that archive on a
device.

## Into the Fruit Store

The Fruit Store lists the apps in mFruit OS's `config/catalog.json`; that is a
change to the mFruit OS repository, made when the owner asks. An entry for
mDisplay would follow RadioConnect's, with its system packages so the Store
can say what the device needs first (mFruit OS ADR 0011):

```json
{
  "id": "mdisplay",
  "name": "mDisplay",
  "description": "Galaxies, night skies and auroras on an HDMI screen",
  "repository": "https://github.com/Mengkungkao/mDisplay",
  "ref": "<commit of the release>",
  "url": "https://github.com/Mengkungkao/mDisplay/releases/download/v<version>/mdisplay-<version>.tar.gz",
  "sha256": "<from SHA256SUMS>",
  "native": true,
  "version": "<version>",
  "system_packages": ["libsdl2-2.0-0", "python3-numpy", "python3-pil"]
}
```

mFruit OS's hourly catalogue sync moves the pin of the owner's native apps to
new releases after checking them.

## Update and rollback

mFruit OS installs each version in its own folder and switches only after
`install.sh` and `test.sh` pass; a failure keeps the previous version and
restores the data folder from the snapshot taken before the hooks. mDisplay's
data is one settings file whose unknown keys are kept, so a downgrade keeps
newer settings for a later upgrade. There is no `update.sh`: no migration has
been needed. Uninstalling removes the code; *Delete data* removes the settings
(and the NumPy venv, if any).
