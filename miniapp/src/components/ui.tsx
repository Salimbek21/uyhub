/** Small shared presentational pieces: chips, skeletons, empty and error states. */

import type { ReactNode } from 'react'

import { useI18n } from '../i18n/useI18n'

export function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={[
        'shrink-0 rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors',
        active
          ? 'bg-tg-button text-tg-button-text'
          : 'bg-tg-section text-tg-text border border-tg-border',
      ].join(' ')}
    >
      {children}
    </button>
  )
}

export function CardSkeleton() {
  return (
    <div className="flex gap-3 rounded-2xl bg-tg-section p-3">
      <div className="skeleton h-24 w-28 shrink-0 rounded-xl" />
      <div className="flex-1 space-y-2 py-1">
        <div className="skeleton h-4 w-4/5 rounded" />
        <div className="skeleton h-3 w-3/5 rounded" />
        <div className="skeleton h-3 w-2/5 rounded" />
        <div className="skeleton h-5 w-1/2 rounded" />
      </div>
    </div>
  )
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string
  hint: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center px-8 py-16 text-center">
      <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-tg-section">
        <svg viewBox="0 0 24 24" className="h-8 w-8 text-tg-hint" fill="none" aria-hidden="true">
          <path
            d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1Z"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinejoin="round"
          />
        </svg>
      </div>
      <p className="text-base font-semibold">{title}</p>
      <p className="mt-1.5 max-w-xs text-sm text-tg-hint">{hint}</p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  )
}

export function ErrorState({ onRetry }: { onRetry: () => void }) {
  const { t } = useI18n()
  return (
    <div className="flex flex-col items-center px-8 py-16 text-center">
      <p className="text-base font-semibold">{t.loadError}</p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-4 rounded-xl bg-tg-button px-5 py-2.5 text-sm font-semibold text-tg-button-text"
      >
        {t.retry}
      </button>
    </div>
  )
}

/** Explains that the data is fake. Removed when the real API lands in Phase 4. */
export function PrototypeBanner() {
  const { t } = useI18n()
  return (
    <div className="mx-3 mt-3 rounded-xl border border-dashed border-tg-border bg-tg-section px-3 py-2">
      <p className="text-xs leading-snug text-tg-hint">{t.prototypeNotice}</p>
    </div>
  )
}
