/**
 * Placeholder photography.
 *
 * Real listing photos come from MinIO once the collector runs (Phase 1). Until
 * then these are generated SVG data URIs: deterministic per listing, visually
 * distinct, and with no network dependency, so the prototype renders identically
 * offline and behind a proxy.
 */

const PALETTES: [string, string][] = [
  ['#1e3a5f', '#4a7fb5'],
  ['#5c4033', '#a67c52'],
  ['#2d4a3e', '#6b9080'],
  ['#4a3f55', '#8b7a9e'],
  ['#5c3a3a', '#b08080'],
  ['#3a4a5c', '#7a95b0'],
  ['#4f4a2d', '#a89c6b'],
  ['#2f3e46', '#84a98c'],
]

/** A simple interior silhouette so a photo reads as a room, not a colour swatch. */
function interior(stroke: string): string {
  return `
    <g stroke="${stroke}" stroke-width="2" fill="none" opacity="0.35">
      <rect x="60" y="120" width="120" height="90" />
      <rect x="75" y="140" width="40" height="30" />
      <rect x="130" y="140" width="35" height="70" />
      <path d="M40 210 L200 210" />
      <path d="M220 210 L300 210 L300 150 L260 130 L220 150 Z" />
      <rect x="250" y="170" width="25" height="40" />
    </g>`
}

export function photoDataUri(seed: number, index: number, size: 'thumb' | 'large'): string {
  const palette = PALETTES[(seed + index) % PALETTES.length] ?? PALETTES[0]!
  const [dark, light] = palette
  const w = size === 'thumb' ? 400 : 1280
  const h = size === 'thumb' ? 300 : 960
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 340 240" width="${w}" height="${h}">
    <defs>
      <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="${light}" />
        <stop offset="1" stop-color="${dark}" />
      </linearGradient>
    </defs>
    <rect width="340" height="240" fill="url(#g)" />
    <circle cx="285" cy="45" r="22" fill="#ffffff" opacity="0.18" />
    ${interior('#ffffff')}
  </svg>`
  // `charset=utf-8`, not `utf8`: the latter is not a valid media-type parameter
  // under RFC 2397. Chrome renders it anyway, but Safari and the Telegram iOS
  // in-app WebView reject the URI and show nothing.
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}
