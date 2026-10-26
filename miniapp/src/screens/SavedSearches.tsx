/**
 * Saved searches (SPEC section 10 and 11).
 *
 * A saved search is what the bot matches new listings against: instant mode sends
 * a card as soon as one arrives, daily mode batches into a 09:00 digest.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { TrashIcon } from '../components/Icons'
import { EmptyState } from '../components/ui'
import { deleteSavedSearch, listSavedSearches } from '../data/client'
import { useI18n } from '../i18n/useI18n'
import type { Filters, SavedSearch } from '../types'

function describe(filters: Filters, t: ReturnType<typeof useI18n>['t']): string {
  const parts: string[] = [filters.deal_type === 'sale' ? t.sale : t.rent]
  if (filters.property_type) parts.push(t.properties[filters.property_type])
  if (filters.rooms.length) {
    parts.push(filters.rooms.sort((a, b) => a - b).map((r) => (r >= 4 ? '4+' : r)).join('/') + ' xona')
  }
  if (filters.districts.length) {
    parts.push(filters.districts.map((d) => t.districts[d]).join(', '))
  }
  if (filters.price_min !== null || filters.price_max !== null) {
    parts.push(`${filters.price_min ?? 0}–${filters.price_max ?? '∞'} $`)
  }
  return parts.join(' · ')
}

export function SavedSearches({ onOpenFilters }: { onOpenFilters: () => void }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()

  const query = useQuery({ queryKey: ['saved-searches'], queryFn: listSavedSearches })

  const remove = useMutation({
    mutationFn: deleteSavedSearch,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['saved-searches'] }),
  })

  const searches: SavedSearch[] = query.data ?? []

  return (
    <>
      <header className="sticky top-0 z-20 border-b border-tg-border bg-tg-secondary/95 px-4 py-3 backdrop-blur">
        <h1 className="text-base font-semibold">{t.navSearches}</h1>
      </header>

      {searches.length === 0 ? (
        <EmptyState
          title={t.noSearches}
          hint={t.noSearchesHint}
          action={
            <button
              type="button"
              onClick={onOpenFilters}
              className="rounded-xl bg-tg-button px-5 py-2.5 text-sm font-semibold text-tg-button-text"
            >
              {t.createFromFilters}
            </button>
          }
        />
      ) : (
        <div className="space-y-2.5 p-3">
          {searches.map((search) => (
            <article key={search.id} className="rounded-2xl bg-tg-section p-3.5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="truncate text-[15px] font-semibold">{search.name}</h3>
                  <p className="mt-1 text-[13px] leading-snug text-tg-hint">
                    {describe(search.filters, t)}
                  </p>
                </div>
                <button
                  type="button"
                  aria-label={t.deleteSearch}
                  onClick={() => remove.mutate(search.id)}
                  className="shrink-0 p-1 text-tg-hint"
                >
                  <TrashIcon className="h-5 w-5" />
                </button>
              </div>
              <p className="mt-2.5 inline-block rounded-md bg-tg-secondary px-2 py-0.5 text-xs font-medium text-tg-hint">
                {search.mode === 'instant' ? t.notifyInstant : t.notifyDaily}
              </p>
            </article>
          ))}
          <p className="px-1 pt-1 text-center text-xs text-tg-hint">{t.maxSearches}</p>
        </div>
      )}
    </>
  )
}
