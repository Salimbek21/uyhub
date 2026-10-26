/** Listing detail (SPEC section 10 "Listing detail"). */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { Gallery } from '../components/Gallery'
import { ExternalIcon, HeartIcon, PhoneIcon } from '../components/Icons'
import { ErrorState } from '../components/ui'
import { getListing, revealContact, toggleFavorite } from '../data/client'
import { useI18n } from '../i18n/useI18n'
import { haptic, openLink } from '../telegram'

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-tg-secondary px-3 py-2">
      <dt className="text-[11px] uppercase tracking-wide text-tg-hint">{label}</dt>
      <dd className="mt-0.5 text-sm font-semibold">{value}</dd>
    </div>
  )
}

export function Detail({ id, onBack }: { id: string; onBack: () => void }) {
  const { t, formatPrice, formatNumber, formatSince } = useI18n()
  const queryClient = useQueryClient()
  const [phones, setPhones] = useState<string[] | null>(null)
  const [reported, setReported] = useState(false)

  const query = useQuery({ queryKey: ['listing', id], queryFn: () => getListing(id) })

  const favorite = useMutation({
    mutationFn: toggleFavorite,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['listing', id] })
      void queryClient.invalidateQueries({ queryKey: ['listings'] })
      void queryClient.invalidateQueries({ queryKey: ['favorites'] })
    },
  })

  const contact = useMutation({
    mutationFn: () => revealContact(id),
    onSuccess: (result) => {
      haptic.notify('success')
      setPhones(result)
    },
  })

  if (query.isError) return <ErrorState onRetry={() => void query.refetch()} />

  if (query.isPending || !query.data) {
    return (
      <div>
        <div className="skeleton aspect-[4/3] w-full" />
        <div className="space-y-3 p-4">
          <div className="skeleton h-6 w-3/4 rounded" />
          <div className="skeleton h-8 w-1/2 rounded" />
          <div className="skeleton h-20 w-full rounded-xl" />
        </div>
      </div>
    )
  }

  const listing = query.data
  const period =
    listing.price_period === 'month' ? t.perMonth : listing.price_period === 'day' ? t.perDay : null

  const previous = listing.price_history.length > 1 ? listing.price_history[0] : null
  const dropped = previous && previous.price_usd > listing.price_usd

  return (
    <div className="pb-6">
      <div className="relative">
        <Gallery photos={listing.photos} />
        <button
          type="button"
          onClick={onBack}
          aria-label={t.navFeed}
          className="absolute left-3 top-3 rounded-full bg-black/45 p-2 text-white backdrop-blur"
        >
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" aria-hidden="true">
            <path d="m15 5-7 7 7 7" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>

      <div className="bg-tg-section px-4 py-4">
        <div className="flex items-start justify-between gap-3">
          <h1 className="text-lg leading-snug font-bold">{listing.title}</h1>
          <button
            type="button"
            aria-pressed={listing.is_favorite}
            aria-label={t.navFavorites}
            onClick={() => {
              haptic.impact('light')
              favorite.mutate(listing.id)
            }}
            className={listing.is_favorite ? 'text-tg-destructive' : 'text-tg-hint'}
          >
            <HeartIcon className="h-7 w-7" filled={listing.is_favorite} />
          </button>
        </div>

        <div className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="text-2xl font-bold">
            {formatPrice(listing.price_amount, listing.price_currency)}
          </span>
          {period ? <span className="text-sm text-tg-hint">{period}</span> : null}
          {listing.negotiable ? (
            <span className="rounded-md bg-tg-secondary px-2 py-0.5 text-xs font-medium text-tg-hint">
              {t.negotiable}
            </span>
          ) : null}
        </div>

        {listing.price_per_m2 ? (
          <p className="mt-0.5 text-sm text-tg-hint">
            {formatNumber(listing.price_per_m2)} $ / {t.perM2}
          </p>
        ) : null}

        {dropped && previous ? (
          <p className="mt-2 text-sm font-medium text-emerald-600 dark:text-emerald-400">
            {t.priceDropped(
              formatPrice(previous.price_usd, 'USD'),
              formatPrice(listing.price_usd, 'USD'),
            )}
          </p>
        ) : null}

        {listing.landmark ? (
          <p className="mt-2 text-sm">
            <span className="text-tg-hint">
              {listing.district ? t.districts[listing.district] : ''}
              {listing.district ? ' · ' : ''}
            </span>
            {listing.landmark}
          </p>
        ) : null}

        <p className="mt-1 text-xs text-tg-hint">{formatSince(listing.first_seen_at)}</p>
      </div>

      <section className="mt-2 bg-tg-section px-4 py-4">
        <h2 className="mb-2.5 text-sm font-semibold">{t.detailsLabel}</h2>
        <dl className="grid grid-cols-2 gap-2">
          {listing.rooms ? <Fact label={t.rooms} value={t.roomsShort(listing.rooms)} /> : null}
          {listing.area_m2 ? (
            <Fact label={t.areaM2} value={`${formatNumber(listing.area_m2)} m²`} />
          ) : null}
          {listing.land_sotix ? (
            <Fact label={t.landArea} value={`${listing.land_sotix} sotix`} />
          ) : null}
          {listing.floor && listing.floors_total ? (
            <Fact label="Qavat" value={t.floorOf(listing.floor, listing.floors_total)} />
          ) : null}
          <Fact label={t.renovationLabel} value={t.renovations[listing.renovation]} />
          <Fact label={t.propertyType} value={t.properties[listing.property_type]} />
        </dl>
      </section>

      <section className="mt-2 bg-tg-section px-4 py-4">
        <h2 className="mb-2 text-sm font-semibold">{t.descriptionLabel}</h2>
        <p className="whitespace-pre-line text-[15px] leading-relaxed">{listing.description}</p>
      </section>

      <section className="mt-2 bg-tg-section px-4 py-4">
        <h2 className="mb-2 text-sm font-semibold">
          {listing.sources.length > 1 ? t.originalPosts : t.originalPost}
        </h2>
        <p className="mb-2.5 text-xs text-tg-hint">{t.seenIn(listing.sources.length)}</p>
        <ul className="space-y-1.5">
          {listing.sources.map((source, i) => (
            <li key={i}>
              {source.tg_link ? (
                <button
                  type="button"
                  onClick={() => openLink(source.tg_link!)}
                  className="flex w-full items-center justify-between gap-2 rounded-xl bg-tg-secondary px-3 py-2.5 text-left"
                >
                  <span className="truncate text-sm">{source.title}</span>
                  <ExternalIcon className="h-4 w-4 shrink-0 text-tg-link" />
                </button>
              ) : (
                <div className="rounded-xl bg-tg-secondary px-3 py-2.5">
                  <span className="truncate text-sm text-tg-hint">{source.title}</span>
                </div>
              )}
            </li>
          ))}
        </ul>
      </section>

      <div className="mt-4 space-y-2 px-4">
        {phones ? (
          <a
            href={`tel:${phones[0]}`}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-tg-button py-3.5 text-[15px] font-semibold text-tg-button-text"
          >
            <PhoneIcon />
            {phones[0]}
          </a>
        ) : (
          <button
            type="button"
            disabled={contact.isPending}
            onClick={() => contact.mutate()}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-tg-button py-3.5 text-[15px] font-semibold text-tg-button-text disabled:opacity-60"
          >
            <PhoneIcon />
            {t.showPhone}
          </button>
        )}

        <button
          type="button"
          onClick={() => {
            haptic.notify('warning')
            setReported(true)
          }}
          className="w-full rounded-xl border border-tg-border py-2.5 text-sm font-medium text-tg-hint"
        >
          {reported ? t.reportSent : t.report}
        </button>
      </div>
    </div>
  )
}
