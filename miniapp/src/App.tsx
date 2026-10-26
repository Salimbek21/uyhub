/**
 * Application shell: tabs, the detail push, and Telegram's BackButton.
 *
 * Navigation is local state rather than a router. The Mini App has one deep-link
 * entry point (a listing id passed in `start_param`), which Phase 5 wires up; a
 * full router would add weight the prototype does not need.
 */

import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'

import { BottomNav } from './components/BottomNav'
import type { Tab } from './components/BottomNav'
import { FilterSheet } from './components/FilterSheet'
import { createSavedSearch } from './data/client'
import { useI18n } from './i18n/useI18n'
import { Detail } from './screens/Detail'
import { Favorites } from './screens/Favorites'
import { Feed } from './screens/Feed'
import { SavedSearches } from './screens/SavedSearches'
import { Settings } from './screens/Settings'
import { applyTheme, backButton, haptic, onThemeChanged } from './telegram'
import type { Filters } from './types'
import { DEFAULT_FILTERS } from './types'

export default function App() {
  const { t } = useI18n()
  const queryClient = useQueryClient()

  const [tab, setTab] = useState<Tab>('feed')
  const [openId, setOpenId] = useState<string | null>(null)
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS)
  const [sheetFromSearches, setSheetFromSearches] = useState(false)

  const closeDetail = useCallback(() => {
    setOpenId(null)
    haptic.impact('light')
  }, [])

  // Telegram's own back arrow drives the detail screen, which is what users expect
  // inside the client. The browser fallback is the in-page button in Detail.
  useEffect(() => backButton(openId !== null, closeDetail), [openId, closeDetail])

  // Telegram can change theme while the app is open.
  useEffect(() => onThemeChanged(applyTheme), [])

  const saveSearch = useCallback(
    async (next: Filters) => {
      const name = window.prompt(t.searchNamePrompt, t.navSearches)
      if (!name) return
      await createSavedSearch(name, next, 'instant')
      await queryClient.invalidateQueries({ queryKey: ['saved-searches'] })
      haptic.notify('success')
      setTab('searches')
    },
    [queryClient, t],
  )

  if (openId) {
    return (
      <main className="min-h-full bg-tg-secondary">
        <Detail id={openId} onBack={closeDetail} />
      </main>
    )
  }

  return (
    <div className="flex min-h-full flex-col bg-tg-secondary">
      <main className="flex-1">
        {tab === 'feed' ? (
          <Feed
            filters={filters}
            onFiltersChange={setFilters}
            onOpen={setOpenId}
            onSaveSearch={(next) => void saveSearch(next)}
          />
        ) : null}

        {tab === 'favorites' ? <Favorites onOpen={setOpenId} /> : null}

        {tab === 'searches' ? (
          <SavedSearches onOpenFilters={() => setSheetFromSearches(true)} />
        ) : null}

        {tab === 'settings' ? <Settings /> : null}
      </main>

      <BottomNav tab={tab} onChange={setTab} />

      {sheetFromSearches ? (
        <FilterSheet
          initial={filters}
          onClose={() => setSheetFromSearches(false)}
          onApply={(next) => {
            setFilters(next)
            setSheetFromSearches(false)
            setTab('feed')
          }}
          onSaveSearch={(next) => {
            setSheetFromSearches(false)
            void saveSearch(next)
          }}
        />
      ) : null}
    </div>
  )
}
