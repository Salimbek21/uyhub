/** One listing card in the feed (SPEC section 9.2 "Returns cards"). */

import { useI18n } from '../i18n/useI18n'
import { haptic } from '../telegram'
import type { ListingCard } from '../types'
import { CameraIcon, HeartIcon } from './Icons'
import { Photo } from './Photo'

interface Props {
  listing: ListingCard
  onOpen: (id: string) => void
  onToggleFavorite: (id: string) => void
}

export function ListingCardView({ listing, onOpen, onToggleFavorite }: Props) {
  const { t, formatPrice, formatNumber, formatSince } = useI18n()

  const price = formatPrice(listing.price_amount, listing.price_currency)
  const period =
    listing.price_period === 'month' ? t.perMonth : listing.price_period === 'day' ? t.perDay : null

  const facts = [
    listing.district ? t.districts[listing.district] : null,
    listing.area_m2 ? `${formatNumber(listing.area_m2)} m²` : null,
    listing.land_sotix ? `${listing.land_sotix} sotix` : null,
  ].filter(Boolean)

  return (
    <article className="overflow-hidden rounded-2xl bg-tg-section">
      <button
        type="button"
        onClick={() => onOpen(listing.id)}
        className="flex w-full gap-3 p-3 text-left"
      >
        <div className="relative h-24 w-28 shrink-0 overflow-hidden rounded-xl bg-tg-secondary">
          <Photo
            src={listing.thumb_url}
            seedKey={listing.id}
            className="h-full w-full object-cover"
          />
          {listing.photo_count > 1 ? (
            <span className="absolute bottom-1 right-1 flex items-center gap-1 rounded-md bg-black/55 px-1.5 py-0.5 text-[11px] font-medium text-white">
              <CameraIcon />
              {listing.photo_count}
            </span>
          ) : null}
        </div>

        <div className="min-w-0 flex-1">
          <h3 className="line-clamp-2 text-[15px] leading-snug font-semibold">{listing.title}</h3>

          <p className="mt-1 truncate text-[13px] text-tg-hint">{facts.join(' · ')}</p>

          {listing.floor && listing.floors_total ? (
            <p className="text-[13px] text-tg-hint">
              {t.floorOf(listing.floor, listing.floors_total)}
            </p>
          ) : null}

          <div className="mt-1.5 flex items-baseline gap-2">
            <span className="text-[17px] font-bold">{price}</span>
            {period ? <span className="text-xs text-tg-hint">{period}</span> : null}
          </div>

          {listing.price_per_m2 ? (
            <p className="text-xs text-tg-hint">
              {formatNumber(listing.price_per_m2)} $ / {t.perM2}
            </p>
          ) : null}
        </div>
      </button>

      <div className="flex items-center justify-between border-t border-tg-border px-3 py-2">
        <span className="text-xs text-tg-hint">{formatSince(listing.first_seen_at)}</span>
        <button
          type="button"
          aria-label={t.navFavorites}
          aria-pressed={listing.is_favorite}
          onClick={() => {
            haptic.impact('light')
            onToggleFavorite(listing.id)
          }}
          className={listing.is_favorite ? 'text-tg-destructive' : 'text-tg-hint'}
        >
          <HeartIcon filled={listing.is_favorite} />
        </button>
      </div>
    </article>
  )
}
