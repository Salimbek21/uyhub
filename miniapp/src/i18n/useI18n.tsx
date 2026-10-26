/** Language context and formatting helpers. */

import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import type { Language } from '../types'
import { STRINGS } from './strings'
import type { Strings } from './strings'

const LANG_KEY = 'uyhub.lang'

interface I18nValue {
  lang: Language
  t: Strings
  setLang: (lang: Language) => void
  /** `65 000 $` / `650 000 000 so'm` — spaced thousands, per SPEC section 10. */
  formatPrice: (amount: number, currency: 'USD' | 'UZS') => string
  formatNumber: (value: number) => string
  /** Relative time in the active language. */
  formatSince: (iso: string) => string
}

const I18nContext = createContext<I18nValue | null>(null)

function initialLang(): Language {
  const stored = localStorage.getItem(LANG_KEY)
  if (stored === 'uz' || stored === 'ru') return stored
  // Telegram exposes the client language; Russian speakers get Russian, everyone
  // else gets Uzbek, which is the default per SPEC 1.3.
  return navigator.language.startsWith('ru') ? 'ru' : 'uz'
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Language>(initialLang)

  const setLang = useCallback((next: Language) => {
    setLangState(next)
    localStorage.setItem(LANG_KEY, next)
    document.documentElement.lang = next
  }, [])

  const value = useMemo<I18nValue>(() => {
    const t = STRINGS[lang]
    // ru-RU groups thousands with a space, but ICU versions disagree on which
    // space character. Normalise to U+00A0 so "65 000 $" never wraps mid-number.
    const group = (value: number) =>
      value.toLocaleString('ru-RU').replace(/[\u0020\u202F\u2009\u00A0]/g, '\u00A0')

    return {
      lang,
      t,
      setLang,
      formatNumber: group,
      formatPrice: (amount, currency) =>
        currency === 'USD'
          ? `${group(Math.round(amount))} $`
          : `${group(Math.round(amount))} ${lang === 'uz' ? "so'm" : 'сум'}`,
      formatSince: (iso) => {
        const minutes = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000))
        if (minutes < 2) return t.time.justNow
        if (minutes < 60) return t.time.minutesAgo(minutes)
        const hours = Math.round(minutes / 60)
        if (hours < 24) return t.time.hoursAgo(hours)
        return t.time.daysAgo(Math.round(hours / 24))
      },
    }
  }, [lang, setLang])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext)
  if (!value) throw new Error('useI18n must be used inside I18nProvider')
  return value
}
