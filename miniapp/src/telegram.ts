/**
 * Telegram Mini App integration.
 *
 * Types are written by hand against Telegram's published WebApp API rather than
 * pulled from a third-party package.
 *
 * Note that loading the SDK script defines `window.Telegram.WebApp` on ANY page,
 * including a plain browser tab, where it is an inert stub that warns on every
 * unsupported call. Feature guards therefore test `initData`, not the object's
 * existence — see `insideTelegram` below. That is what lets `npm run dev` work in
 * a desktop browser with a clean console.
 */

export interface ThemeParams {
  bg_color?: string
  text_color?: string
  hint_color?: string
  link_color?: string
  button_color?: string
  button_text_color?: string
  secondary_bg_color?: string
  header_bg_color?: string
  section_bg_color?: string
  destructive_text_color?: string
}

type HapticStyle = 'light' | 'medium' | 'heavy' | 'rigid' | 'soft'
type NotificationType = 'error' | 'success' | 'warning'

interface WebApp {
  initData: string
  colorScheme: 'light' | 'dark'
  themeParams: ThemeParams
  isExpanded: boolean
  viewportStableHeight: number
  ready(): void
  expand(): void
  close(): void
  onEvent(event: string, handler: () => void): void
  offEvent(event: string, handler: () => void): void
  openTelegramLink(url: string): void
  openLink(url: string): void
  BackButton: { show(): void; hide(): void; onClick(cb: () => void): void; offClick(cb: () => void): void }
  MainButton: {
    text: string
    show(): void
    hide(): void
    setText(text: string): void
    onClick(cb: () => void): void
    offClick(cb: () => void): void
    enable(): void
    disable(): void
  }
  HapticFeedback: {
    impactOccurred(style: HapticStyle): void
    notificationOccurred(type: NotificationType): void
    selectionChanged(): void
  }
}

declare global {
  interface Window {
    Telegram?: { WebApp?: WebApp }
  }
}

/** The raw SDK object. Present whenever the script loaded, even in a plain browser. */
function sdk(): WebApp | undefined {
  return window.Telegram?.WebApp
}

/**
 * True only when actually running inside a Telegram client.
 *
 * The SDK script defines `window.Telegram.WebApp` on any page, but outside
 * Telegram it is an inert stub that reports version 6.0 and logs a warning for
 * every unsupported call. `initData` is non-empty only in a real client, so it is
 * what the feature guards below test.
 */
export const insideTelegram = (): boolean => Boolean(sdk()?.initData)

/**
 * The signed credential the API authenticates with (SPEC 9.1).
 *
 * Empty outside Telegram, which is exactly the case the API's
 * `API_ALLOW_INSECURE_AUTH` development flag covers. It is a credential, so it
 * belongs in the `Authorization` header and never in a URL or a log.
 */
export const initData = (): string => sdk()?.initData ?? ''

/** The SDK, but only when it can actually do anything. */
function app(): WebApp | undefined {
  return insideTelegram() ? sdk() : undefined
}

/** Call once on mount: tells Telegram the app has painted and asks for full height. */
export function initTelegram(): void {
  const wa = app()
  if (!wa) return
  wa.ready()
  wa.expand()
}

export function colorScheme(): 'light' | 'dark' {
  return (
    app()?.colorScheme ??
    (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
  )
}

/**
 * Publishes Telegram's theme as CSS custom properties.
 *
 * SPEC section 10 requires the app to follow Telegram's colours so it does not
 * look foreign inside the client. Outside Telegram these fall back to values
 * defined in index.css.
 */
export function applyTheme(): void {
  const params = app()?.themeParams
  if (!params) return
  const root = document.documentElement
  const map: [keyof ThemeParams, string][] = [
    ['bg_color', '--tg-bg'],
    ['text_color', '--tg-text'],
    ['hint_color', '--tg-hint'],
    ['link_color', '--tg-link'],
    ['button_color', '--tg-button'],
    ['button_text_color', '--tg-button-text'],
    ['secondary_bg_color', '--tg-secondary-bg'],
    ['section_bg_color', '--tg-section-bg'],
    ['destructive_text_color', '--tg-destructive'],
  ]
  for (const [key, cssVar] of map) {
    const value = params[key]
    if (value) root.style.setProperty(cssVar, value)
  }
  root.dataset.theme = colorScheme()
}

/** Telegram's own back arrow in the header — the native way to go back. */
export function backButton(visible: boolean, onClick: () => void): () => void {
  const wa = app()
  if (!wa) return () => {}
  if (visible) {
    wa.BackButton.onClick(onClick)
    wa.BackButton.show()
  } else {
    wa.BackButton.hide()
  }
  return () => {
    wa.BackButton.offClick(onClick)
    wa.BackButton.hide()
  }
}

export function mainButton(
  config: { text: string; visible: boolean } | null,
  onClick: () => void,
): () => void {
  const wa = app()
  if (!wa || !config) return () => {}
  if (config.visible) {
    wa.MainButton.setText(config.text)
    wa.MainButton.onClick(onClick)
    wa.MainButton.show()
  } else {
    wa.MainButton.hide()
  }
  return () => {
    wa.MainButton.offClick(onClick)
    wa.MainButton.hide()
  }
}

export const haptic = {
  impact(style: HapticStyle = 'light'): void {
    app()?.HapticFeedback.impactOccurred(style)
  },
  notify(type: NotificationType): void {
    app()?.HapticFeedback.notificationOccurred(type)
  },
  select(): void {
    app()?.HapticFeedback.selectionChanged()
  },
}

/** Subscribes to Telegram's theme changes. No-op outside Telegram. */
export function onThemeChanged(handler: () => void): () => void {
  const wa = app()
  if (!wa) return () => {}
  wa.onEvent('themeChanged', handler)
  return () => wa.offEvent('themeChanged', handler)
}

/** Opens a t.me link in Telegram itself when available, otherwise a new tab. */
export function openLink(url: string): void {
  const wa = app()
  if (wa && url.includes('t.me')) {
    wa.openTelegramLink(url)
    return
  }
  if (wa) {
    wa.openLink(url)
    return
  }
  window.open(url, '_blank', 'noopener')
}
