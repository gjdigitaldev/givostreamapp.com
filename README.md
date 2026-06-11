# givostreamapp.com

Marketing site for **GiVo Stream** (iOS / iPadOS / tvOS IPTV player) and
**GiVo Server** (macOS / Windows DVR companion). Static HTML/CSS, hosted on
GitHub Pages with the custom domain `givostreamapp.com`.

- `index.html` — landing page
- `support.html` — support / FAQ
- `privacy.html` — privacy policy (App Store requirement)
- Server downloads are attached to GitHub **Releases** on this repo; the
  site's download buttons use `releases/latest/download/<asset>` so new
  releases go live without editing the site.

## Releasing a new server build

```
gh release create v1.0.X --title "GiVo Server 1.0 (build X)" \
  "GiVo-Server-macOS-Universal.dmg" "GiVo-Server-Setup-x64.exe"
```
