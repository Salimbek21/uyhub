/** Feed: quick filter chips plus an infinite list of cards (SPEC section 10). */

import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import { FilterSheet } from '../components/FilterSheet'
import { FilterIcon, SearchIcon } from '../components/Icons'
import { ListingCardView } from '../components/ListingCardView'
import { CardSkeleton, Chip, EmptyState, ErrorState, PrototypeBanner } from '../components/ui'
import { listListings, toggleFavorite } from '../data/client'
import { useI18n } from '../i18n/useI18n'
import { haptic } from '../telegram'
import type { Filters } from '../types'
import { DEFAULT_FILTERS } from '../types'

interface Props {
  filters: Filters
  onFiltersChange: (filters: Filters) => void
  onOpen: (id: string) => void
  onSaveSearch: (filters: Filters) => void
}

export function Feed({ filters, onFiltersChange, onOpen, onSaveSearch }: Props) {
  const { t, formatNumber } = useI18n()
  const queryClient = useQueryClient()
  const [sheetOpen, setSheetOpen] = useState(false)
  const [search, setSearch] = useState(filters.q)
  const sentinel = useRef<HTMLDivElement>(null)

  // Debounce the text box so typing does not fire a request per keystroke.
  useEffect(() => {
    const id = setTimeout(() => {
      if (search !== filters.q) onFiltersChange({ ...filters, q: search })
    }, 300)
    return () => clearTimeout(id)
  }, [search, filters, onFiltersChange])

  const query = useInfiniteQuery({
    queryKey: ['listings', filters],
    queryFn: ({ pageParam }) => listListings(filters, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  })

  const favorite = useMutation({
    mutationFn: toggleFavorite,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['listings'] }),
  })

  const { hasNextPage, isFetchingNextPage, fetchNextPage } = query

  useEffect(() => {
    const node = sentinel.current
    if (!node || !hasNextPage) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && !isFetchingNextPage) void fetchNextPage()
      },
      { rootMargin: '400px' },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [hasNextPage, isFetchingNextPage, fetchNextPage])

  const items = query.data?.pages.flatMap((page) => page.items) ?? []
  const total = query.data?.pages[0]?.total ?? 0

  const setDeal = (deal: Filters['deal_type']) => {
    haptic.select()
    onFiltersChange({ ...filters, deal_type: deal })
  }

  const toggleRoom = (n: number) => {
    haptic.select()
    onFiltersChange({
      ...filters,
      rooms: filters.rooms.includes(n) ? filters.rooms.filter((r) => r !== n) : [...filters.rooms, n],
    })
  }

  const activeFilterCount =
    filters.districts.length +
    (filters.price_min !== null || filters.price_max !== null ? 1 : 0) +
    (filters.area_min !== null || filters.area_max !== null ? 1 : 0) +
    (filters.has_photos ? 1 : 0) +
    (filters.property_type && filters.property_type !== 'apartment' ? 1 : 0)

  return (
    <>
      <header className="sticky top-0 z-20 bg-tg-secondary/95 backdrop-blur">
        <div className="flex items-center gap-2 px-3 pb-2 pt-3">
          <div className="relative flex-1">
            <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4.5 w-4.5 -translate-y-1/2 text-tg-hint" />
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t.searchPlaceholder}
              className="w-full rounded-xl border border-tg-border bg-tg-section py-2.5 pl-10 pr-3 text-[15px] outline-none focus:border-tg-button"
            />
          </div>
          <button
            type="button"
            onClick={() => setSheetOpen(true)}
            aria-label={t.filters}
            className="relative rounded-xl border border-tg-border bg-tg-section p-2.5"
          >
            <FilterIcon />
            {activeFilterCount > 0 ? (
              <span className="absolute -right-1 -top-1 flex h-4.5 min-w-4.5 items-center justify-center rounded-full bg-tg-button px-1 text-[10px] font-bold text-tg-button-text">
                {activeFilterCount}
              </span>
            ) : null}
          </button>
        </div>

        <div className="no-scrollbar flex gap-2 overflow-x-auto px-3 pb-2">
          <Chip active={filters.deal_type === 'sale'} onClick={() => setDeal('sale')}>
            {t.sale}
          </Chip>
          <Chip active={filters.deal_type === 'rent'} onClick={() => setDeal('rent')}>
            {t.rent}
          </Chip>
          <span className="my-1 w-px shrink-0 bg-tg-border" />
          {[1, 2, 3, 4].map((n) => (
            <Chip key={n} active={filters.rooms.includes(n)} onClick={() => toggleRoom(n)}>
              {n === 4 ? t.roomsPlus(4) : t.roomsShort(n)}
            </Chip>
          ))}
        </div>
      </header>

      <PrototypeBanner />

      {query.isError ? (
        <ErrorState onRetry={() => void query.refetch()} />
      ) : query.isPending ? (
        <div className="space-y-2.5 p-3">
          {[0, 1, 2, 3, 4].map((i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          title={t.nothingFound}
          hint={t.nothingFoundHint}
          action={
            <button
              type="button"
              onClick={() => onFiltersChange({ ...DEFAULT_FILTERS, deal_type: filters.deal_type })}
              className="rounded-xl bg-tg-button px-5 py-2.5 text-sm font-semibold text-tg-button-text"
            >
              {t.resetFilters}
            </button>
          }
        />
      ) : (
        <>
          <p className="px-4 pb-1 pt-3 text-xs font-medium text-tg-hint">
            {t.resultsCount(Number(formatNumber(total)) || total)}
          </p>
          <div className="space-y-2.5 px-3 pb-3">
            {items.map((listing) => (
              <ListingCardView
                key={listing.id}
                listing={listing}
                onOpen={onOpen}
                onToggleFavorite={(id) => favorite.mutate(id)}
              />
            ))}
          </div>

          <div ref={sentinel} />
          {isFetchingNextPage ? (
            <div className="space-y-2.5 px-3 pb-3">
              <CardSkeleton />
            </div>
          ) : null}
        </>
      )}

      {sheetOpen ? (
        <FilterSheet
          initial={filters}
          onClose={() => setSheetOpen(false)}
          onApply={(next) => {
            onFiltersChange(next)
            setSearch(next.q)
            setSheetOpen(false)
          }}
          onSaveSearch={(next) => {
            onSaveSearch(next)
            setSheetOpen(false)
          }}
        />
      ) : null}
    </>
  )
}
