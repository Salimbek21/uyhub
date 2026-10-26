/**
 * A listing photo, with a drawn placeholder when there is no image.
 *
 * The placeholder is inline SVG in the DOM rather than a `data:` URI. Data URIs
 * are surprisingly fragile in this position: Safari and older WebViews reject a
 * malformed media-type parameter outright, a strict `img-src` CSP blocks the
 * `data:` scheme entirely, and some extensions and enterprise policies do the
 * same. Inline SVG has none of those failure modes.
 *
 * This is not only a prototype concern. In production a listing can legitimately
 * have no photo, and that case needs to render as something deliberate rather
 * than as an empty box — which is exactly what this component does.
 */

const PALETTES: readonly (readonly [string, string])[] = [
  ['#1e3a5f', '#4a7fb5'],
  ['#5c4033', '#a67c52'],
  ['#2d4a3e', '#6b9080'],
  ['#4a3f55', '#8b7a9e'],
  ['#5c3a3a', '#b08080'],
  ['#3a4a5c', '#7a95b0'],
  ['#4f4a2d', '#a89c6b'],
  ['#2f3e46', '#84a98c'],
] as const

/** Stable small integer from a string, so one listing always draws the same art. */
function hash(key: string): number {
  let h = 0
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) | 0
  return Math.abs(h)
}

function Placeholder({ seedKey, className }: { seedKey: string; className?: string }) {
  const index = hash(seedKey) % PALETTES.length
  const [dark, light] = PALETTES[index] ?? PALETTES[0]!
  // Gradient ids must be unique per instance or several inline SVGs on one page
  // resolve `url(#…)` to whichever defined it first.
  const gradientId = `ph-${seedKey.replace(/[^a-zA-Z0-9]/g, '')}-${index}`

  return (
    <svg
      viewBox="0 0 340 240"
      preserveAspectRatio="xMidYMid slice"
      className={className}
      role="img"
      aria-label=""
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={light} />
          <stop offset="1" stopColor={dark} />
        </linearGradient>
      </defs>
      <rect width="340" height="240" fill={`url(#${gradientId})`} />
      <circle cx="285" cy="45" r="22" fill="#ffffff" opacity="0.18" />
      <g stroke="#ffffff" strokeWidth="2" fill="none" opacity="0.35">
        <rect x="60" y="120" width="120" height="90" />
        <rect x="75" y="140" width="40" height="30" />
        <rect x="130" y="140" width="35" height="70" />
        <path d="M40 210 L200 210" />
        <path d="M220 210 L300 210 L300 150 L260 130 L220 150 Z" />
        <rect x="250" y="170" width="25" height="40" />
      </g>
    </svg>
  )
}

interface Props {
  /** The image URL, or null when the listing has no photo yet. */
  src: string | null
  /** Anything stable and unique — listing id, or id plus photo index. */
  seedKey: string
  className?: string
  eager?: boolean
}

export function Photo({ src, seedKey, className, eager = false }: Props) {
  if (!src) return <Placeholder seedKey={seedKey} className={className} />
  return (
    <img
      src={src}
      alt=""
      loading={eager ? 'eager' : 'lazy'}
      decoding="async"
      className={className}
    />
  )
}
