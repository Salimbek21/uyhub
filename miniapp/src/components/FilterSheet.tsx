/** The full filter sheet (SPEC section 10 "Filter sheet"). */

import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { countMatches } from '../data/client'
import { useI18n } from '../i18n/useI18n'
import { haptic } from '../telegram'
import type { DistrictId, Filters, PropertyType, SortOption } from '../types'
import { DEFAULT_FILTERS } from '../types'
import { Chip } from './ui'

const DISTRICTS: DistrictId[] = [
  'bektemir',
  'chilonzor',
  'mirobod',
  'mirzo_ulugbek',
  'olmazor',
  'sergeli',
  'shayxontohur',
  'uchtepa',
  'yakkasaroy',
  'yashnobod',
  'yunusobod',
  'yangihayot',
]

const PROPERTY_TYPES: PropertyType[] = ['apartment', 'house', 'land', 'commercial', 'room']
const SORTS: SortOption[] = ['new', 'price_asc', 'price_desc', 'price_per_m2']

interface Props {
  initial: Filters
  onApply: (filters: Filters) => void
  onClose: () => void
  onSaveSearch: (filters: Filters) => void
}

function NumberPair({
  label,
  from,
  to,
  onFrom,
  onTo,
}: {
  label: string
  from: number | null
  to: number | null
  onFrom: (value: number | null) => void
  onTo: (value: number | null) => void
}) {
  const { t } = useI18n()
  const field =
    'w-full rounded-xl border border-tg-border bg-tg-bg px-3 py-2.5 text-[15px] outline-none focus:border-tg-button'
  const parse = (raw: string) => (raw.trim() === '' ? null : Number(raw.replace(/\D/g, '')) || null)

  return (
    <section className="px-4 py-3">
      <h4 className="mb-2 text-sm font-semibold">{label}</h4>
      <div className="flex gap-2">
        <input
          type="text"
          inputMode="numeric"
          placeholder={t.from}
          value={from ?? ''}
          onChange={(e) => onFrom(parse(e.target.value))}
          className={field}
        />
        <input
          type="text"
          inputMode="numeric"
          placeholder={t.to}
          value={to ?? ''}
          onChange={(e) => onTo(parse(e.target.value))}
          className={field}
        />
      </div>
    </section>
  )
}

export function FilterSheet({ initial, onApply, onClose, onSaveSearch }: Props) {
  const { t } = useI18n()
  const [draft, setDraft] = useState<Filters>(initial)

  // Live match count, so "Apply" states its own consequence before it is pressed.
  const { data: count } = useQuery({
    queryKey: ['count', draft],
    queryFn: () => countMatches(draft),
  })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const patch = (next: Partial<Filters>) => setDraft((prev) => ({ ...prev, ...next }))

  const toggleDistrict = (id: DistrictId) => {
    haptic.select()
    patch({
      districts: draft.districts.includes(id)
        ? draft.districts.filter((d) => d !== id)
        : [...draft.districts, id],
    })
  }

  const toggleRoom = (n: number) => {
    haptic.select()
    patch({ rooms: draft.rooms.includes(n) ? draft.rooms.filter((r) => r !== n) : [...draft.rooms, n] })
  }

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-black/40" role="dialog" aria-modal="true">
      <button type="button" aria-label={t.reset} className="flex-1" onClick={onClose} />

      <div className="flex max-h-[88vh] flex-col rounded-t-2xl bg-tg-secondary">
        <header className="flex items-center justify-between border-b border-tg-border px-4 py-3">
          <h2 className="text-base font-semibold">{t.filters}</h2>
          <button
            type="button"
            onClick={() => setDraft({ ...DEFAULT_FILTERS, deal_type: draft.deal_type })}
            className="text-sm font-medium text-tg-link"
          >
            {t.reset}
          </button>
        </header>

        <div className="flex-1 divide-y divide-tg-border overflow-y-auto">
          <section className="px-4 py-3">
            <h4 className="mb-2 text-sm font-semibold">{t.dealType}</h4>
            <div className="flex gap-2">
              <Chip active={draft.deal_type === 'sale'} onClick={() => patch({ deal_type: 'sale' })}>
                {t.sale}
              </Chip>
              <Chip active={draft.deal_type === 'rent'} onClick={() => patch({ deal_type: 'rent' })}>
                {t.rent}
              </Chip>
            </div>
          </section>

          <section className="px-4 py-3">
            <h4 className="mb-2 text-sm font-semibold">{t.propertyType}</h4>
            <div className="flex flex-wrap gap-2">
              {PROPERTY_TYPES.map((type) => (
                <Chip
                  key={type}
                  active={draft.property_type === type}
                  onClick={() => patch({ property_type: draft.property_type === type ? null : type })}
                >
                  {t.properties[type]}
                </Chip>
              ))}
            </div>
          </section>

          <section className="px-4 py-3">
            <h4 className="mb-2 text-sm font-semibold">{t.rooms}</h4>
            <div className="flex flex-wrap gap-2">
              {[1, 2, 3, 4].map((n) => (
                <Chip key={n} active={draft.rooms.includes(n)} onClick={() => toggleRoom(n)}>
                  {n === 4 ? t.roomsPlus(4) : t.roomsShort(n)}
                </Chip>
              ))}
            </div>
          </section>

          <section className="px-4 py-3">
            <h4 className="mb-2 text-sm font-semibold">{t.district}</h4>
            <div className="flex flex-wrap gap-2">
              {DISTRICTS.map((id) => (
                <Chip
                  key={id}
                  active={draft.districts.includes(id)}
                  onClick={() => toggleDistrict(id)}
                >
                  {t.districts[id]}
                </Chip>
              ))}
            </div>
          </section>

          <NumberPair
            label={t.priceUsd}
            from={draft.price_min}
            to={draft.price_max}
            onFrom={(v) => patch({ price_min: v })}
            onTo={(v) => patch({ price_max: v })}
          />

          <NumberPair
            label={t.areaM2}
            from={draft.area_min}
            to={draft.area_max}
            onFrom={(v) => patch({ area_min: v })}
            onTo={(v) => patch({ area_max: v })}
          />

          <section className="px-4 py-3">
            <h4 className="mb-2 text-sm font-semibold">{t.sortBy}</h4>
            <div className="flex flex-wrap gap-2">
              {SORTS.map((sort) => (
                <Chip key={sort} active={draft.sort === sort} onClick={() => patch({ sort })}>
                  {t.sorts[sort]}
                </Chip>
              ))}
            </div>
          </section>

          <label className="flex items-center justify-between px-4 py-3.5">
            <span className="text-sm font-medium">{t.onlyWithPhotos}</span>
            <input
              type="checkbox"
              checked={draft.has_photos}
              onChange={(e) => patch({ has_photos: e.target.checked })}
              className="h-5 w-5 accent-[var(--tg-button)]"
            />
          </label>

          <section className="px-4 py-3">
            <button
              type="button"
              onClick={() => onSaveSearch(draft)}
              className="w-full rounded-xl border border-tg-border bg-tg-section py-2.5 text-sm font-semibold text-tg-link"
            >
              {t.saveSearch}
            </button>
            <p className="mt-1.5 text-center text-xs text-tg-hint">{t.maxSearches}</p>
          </section>
        </div>

        <footer className="border-t border-tg-border p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <button
            type="button"
            onClick={() => {
              haptic.impact('medium')
              onApply(draft)
            }}
            className="w-full rounded-xl bg-tg-button py-3 text-[15px] font-semibold text-tg-button-text"
          >
            {count === undefined ? t.apply : t.applyWithCount(count)}
          </button>
        </footer>
      </div>
    </div>
  )
}
