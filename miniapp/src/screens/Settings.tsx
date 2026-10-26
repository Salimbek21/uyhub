/** Settings: language, notifications, privacy (SPEC section 10). */

import { useState } from 'react'

import { useI18n } from '../i18n/useI18n'
import { haptic } from '../telegram'
import type { Language } from '../types'

function Row({
  label,
  hint,
  control,
}: {
  label: string
  hint?: string
  control: React.ReactNode
}) {
  return (
    <div className="flex items-center justify-between gap-4 px-4 py-3.5">
      <div className="min-w-0">
        <p className="text-[15px] font-medium">{label}</p>
        {hint ? <p className="mt-0.5 text-xs leading-snug text-tg-hint">{hint}</p> : null}
      </div>
      <div className="shrink-0">{control}</div>
    </div>
  )
}

export function Settings() {
  const { t, lang, setLang } = useI18n()
  const [notifications, setNotifications] = useState(true)

  const languages: { id: Language; label: string }[] = [
    { id: 'uz', label: "O'zbekcha" },
    { id: 'ru', label: 'Русский' },
  ]

  return (
    <>
      <header className="sticky top-0 z-20 border-b border-tg-border bg-tg-secondary/95 px-4 py-3 backdrop-blur">
        <h1 className="text-base font-semibold">{t.navSettings}</h1>
      </header>

      <div className="p-3">
        <div className="divide-y divide-tg-border overflow-hidden rounded-2xl bg-tg-section">
          <Row
            label={t.language}
            control={
              <div className="flex overflow-hidden rounded-lg border border-tg-border">
                {languages.map(({ id, label }) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => {
                      haptic.select()
                      setLang(id)
                    }}
                    className={[
                      'px-3 py-1.5 text-sm font-medium',
                      lang === id ? 'bg-tg-button text-tg-button-text' : 'text-tg-text',
                    ].join(' ')}
                  >
                    {label}
                  </button>
                ))}
              </div>
            }
          />

          <Row
            label={t.notifications}
            hint={t.notificationsHint}
            control={
              <button
                type="button"
                role="switch"
                aria-checked={notifications}
                onClick={() => {
                  haptic.impact('light')
                  setNotifications((v) => !v)
                }}
                className={[
                  'relative h-7 w-12 rounded-full transition-colors',
                  notifications ? 'bg-tg-button' : 'bg-tg-secondary border border-tg-border',
                ].join(' ')}
              >
                <span
                  className={[
                    'absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition-all',
                    notifications ? 'left-[22px]' : 'left-0.5',
                  ].join(' ')}
                />
              </button>
            }
          />
        </div>

        <div className="mt-3 overflow-hidden rounded-2xl bg-tg-section">
          <button type="button" className="w-full px-4 py-3.5 text-left text-[15px] text-tg-link">
            {t.privacyPolicy}
          </button>
        </div>

        <p className="mt-4 px-2 text-center text-xs leading-relaxed text-tg-hint">{t.aboutHint}</p>
        <p className="mt-2 text-center text-[11px] text-tg-hint">UyHub 0.1.0 · prototype</p>
      </div>
    </>
  )
}
