/** Bottom tab bar. Hidden on the detail screen, which is a push, not a tab. */

import { useI18n } from '../i18n/useI18n'
import { haptic } from '../telegram'
import { BellIcon, GearIcon, HeartIcon, HomeIcon } from './Icons'

export type Tab = 'feed' | 'favorites' | 'searches' | 'settings'

export function BottomNav({ tab, onChange }: { tab: Tab; onChange: (tab: Tab) => void }) {
  const { t } = useI18n()

  const items: { id: Tab; label: string; icon: typeof HomeIcon }[] = [
    { id: 'feed', label: t.navFeed, icon: HomeIcon },
    { id: 'favorites', label: t.navFavorites, icon: HeartIcon },
    { id: 'searches', label: t.navSearches, icon: BellIcon },
    { id: 'settings', label: t.navSettings, icon: GearIcon },
  ]

  return (
    <nav className="sticky bottom-0 z-30 flex border-t border-tg-border bg-tg-section pb-[env(safe-area-inset-bottom)]">
      {items.map(({ id, label, icon: Icon }) => {
        const active = tab === id
        return (
          <button
            key={id}
            type="button"
            onClick={() => {
              haptic.select()
              onChange(id)
            }}
            aria-current={active ? 'page' : undefined}
            className={[
              'flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] font-medium',
              active ? 'text-tg-link' : 'text-tg-hint',
            ].join(' ')}
          >
            <Icon className="h-6 w-6" />
            {label}
          </button>
        )
      })}
    </nav>
  )
}
