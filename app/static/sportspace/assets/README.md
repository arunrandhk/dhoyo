# Arena background

The `fonts/` directory bundles the Ubuntu Sans variable font for consistent
typography without an external font service. It supports weight and width
variations. The font is distributed under the Ubuntu Font Licence; its
copyright notice and full license are included in `fonts/LICENSE.txt`.

`game-arena.webp` is an original background generated with the built-in imagegen
tool for the dhoyo login and community frontend. The PNG was encoded as WebP at
quality 0.88 using browser canvas. The shipped asset is 1672 × 941 pixels and
238,232 bytes; it loads locally without a third-party image service.

Final generation prompt:

```text
Use case: stylized-concept
Asset type: cinematic game environment background for a sports community website login page.
Primary request: a beautiful immersive game-oriented background: an original futuristic sports arena under a midnight sky, like polished AAA video game environment key art.
Scene/backdrop: a vast open-air football stadium embedded among distant rocky mountains, glowing cyan and lime perimeter lights, dark indigo night sky, gentle atmospheric haze and distant stars. A subtle arc of stadium light structures frames the scene. A clean stylized football resting in the lower left foreground on a dark illuminated pitch. Pale lime field lines sweep diagonally into the depth.
Style/medium: premium stylized 3D game environment render, architectural, detailed yet calm, crisp lighting, painterly atmospheric depth.
Composition/framing: wide landscape 16:9 composition. Architecture concentrated in lower two thirds and left of center. Upper-left sky has dark uncluttered negative space for white headline overlay. Rightmost third dark and understated to sit behind a login card. No character subjects. Main stadium readable in center and lower left.
Lighting/mood: dramatic night-time floodlights, soft cyan mist, subtle lime light trails, inviting competitive energy, sophisticated muted colors.
Color palette: midnight navy, black green, cool teal, restrained electric lime highlights; no bright purple.
Constraints: no text, no letters, no logos, no watermarks, no UI, no buttons, no people, no weapons. This is artwork only, not a webpage screenshot.
```

The `stickers/` directory contains eight original, hand-authored SVG sports
stickers with transparent backgrounds, white outlines and the app's lime, teal
and warm accent colors. `../stickers.json` is their shared catalog for the login
preview, private message picker and server send whitelist. These assets are
bundled locally and contain no third-party images or external SVG references.
