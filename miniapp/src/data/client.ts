/**
 * Data access.
 *
 * This is the ONLY file that knows where listings come from. Every function here
 * matches an endpoint in docs/SPEC.md section 9.2, so Phase 4 replaces the bodies
 * with `fetch` calls and no screen changes.
 *
 *   listListings   -> GET    /v1/listings
 *   getListing     -> GET    /v1/listings/{id}
 *   revealContact  -> POST   /v1/listings/{id}/contact
 *   toggleFavorite -> PUT/DELETE /v1/favorites/{id}
 *   listFavorites  -> GET    /v1/favorites
 *   savedSearches  -> GET/POST/DELETE /v1/saved-searches
 */

import type { Filters, ListingCard, ListingDetail, Page, SavedSearch } from '../types'
import { MOCK_LISTINGS } from './listings'

const PAGE_SIZE = 8

/** Simulated round-trip so loading states are visible and real. */
const LATENCY_MS = 350

function delay<T>(value: T, ms = LATENCY_MS): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms))
}

// --- Local persistence ------------------------------------------------------
// Phase 4 moves these to the server (`favorites`, `saved_searches` tables).

const FAVORITES_KEY = 'uyhub.favorites'
const SEARCHES_KEY = 'uyhub.saved_searches'

function readSet(key: string): Set<string> {
  try {
    const raw = localStorage.getItem(key)
    return new Set(raw ? (JSON.parse(raw) as string[]) : [])
  } catch {
    return new Set()
  }
}

function writeSet(key: string, value: Set<string>): void {
  localStorage.setItem(key, JSON.stringify([...value]))
}

export function favoriteIds(): Set<string> {
  return readSet(FAVORITES_KEY)
}

// --- Filtering ---------------------------------------------------------------

function matches(listing: ListingDetail, f: Filters): boolean {
  if (listing.deal_type !== f.deal_type) return false
  if (f.property_type && listing.property_type !== f.property_type) return false
  if (f.districts.length && (!listing.district || !f.districts.includes(listing.district))) {
    return false
  }
  if (f.rooms.length) {
    // 4 means "4 or more", matching the feed's chip labels.
    const ok = f.rooms.some((r) => (r >= 4 ? (listing.rooms ?? 0) >= 4 : listing.rooms === r))
    if (!ok) return false
  }
  if (f.price_min !== null && listing.price_usd < f.price_min) return false
  if (f.price_max !== null && listing.price_usd > f.price_max) return false
  if (f.area_min !== null && (listing.area_m2 ?? 0) < f.area_min) return false
  if (f.area_max !== null && (listing.area_m2 ?? Infinity) > f.area_max) return false
  if (f.has_photos && listing.photo_count === 0) return false
  if (f.q.trim()) {
    const needle = f.q.trim().toLowerCase()
    const hay = `${listing.title} ${listing.landmark ?? ''}`.toLowerCase()
    if (!hay.includes(needle)) return false
  }
  return true
}

function sortListings(items: ListingDetail[], sort: Filters['sort']): ListingDetail[] {
  const sorted = [...items]
  switch (sort) {
    case 'price_asc':
      return sorted.sort((a, b) => a.price_usd - b.price_usd)
    case 'price_desc':
      return sorted.sort((a, b) => b.price_usd - a.price_usd)
    case 'price_per_m2':
      return sorted.sort((a, b) => (a.price_per_m2 ?? Infinity) - (b.price_per_m2 ?? Infinity))
    case 'new':
    default:
      return sorted.sort(
        (a, b) => Date.parse(b.first_seen_at) - Date.parse(a.first_seen_at),
      )
  }
}

function toCard(listing: ListingDetail, favorites: Set<string>): ListingCard {
  return { ...listing, is_favorite: favorites.has(listing.id) }
}

// --- API ----------------------------------------------------------------------

export async function listListings(
  filters: Filters,
  cursor: string | null,
): Promise<Page<ListingCard>> {
  const favorites = favoriteIds()
  const all = sortListings(MOCK_LISTINGS.filter((l) => matches(l, filters)), filters.sort)
  const start = cursor ? Number(cursor) : 0
  const slice = all.slice(start, start + PAGE_SIZE)
  const next = start + PAGE_SIZE < all.length ? String(start + PAGE_SIZE) : null
  return delay({
    items: slice.map((l) => toCard(l, favorites)),
    next_cursor: next,
    total: all.length,
  })
}

export async function getListing(id: string): Promise<ListingDetail> {
  const favorites = favoriteIds()
  const found = MOCK_LISTINGS.find((l) => l.id === id)
  if (!found) throw new Error('not_found')
  return delay({ ...found, is_favorite: favorites.has(found.id) })
}

export async function listFavorites(): Promise<ListingCard[]> {
  const favorites = favoriteIds()
  const items = MOCK_LISTINGS.filter((l) => favorites.has(l.id)).map((l) => toCard(l, favorites))
  return delay(items)
}

export async function toggleFavorite(id: string): Promise<boolean> {
  const favorites = favoriteIds()
  const now = !favorites.has(id)
  if (now) favorites.add(id)
  else favorites.delete(id)
  writeSet(FAVORITES_KEY, favorites)
  return delay(now, 80)
}

/**
 * Reveals the seller's phone.
 *
 * In production this hits `POST /v1/listings/{id}/contact`, which writes a
 * `contact_reveals` row and is rate limited to 30 per user per hour (SPEC 9.2).
 * Phones are never part of the listing payload — that is why this is a separate
 * call rather than a field.
 */
export async function revealContact(id: string): Promise<string[]> {
  const n = (Number(id.replace(/\D/g, '')) % 7) + 1
  return delay([`+99890${String(1000000 + n * 137).slice(0, 7)}`], 500)
}

export async function listSavedSearches(): Promise<SavedSearch[]> {
  try {
    const raw = localStorage.getItem(SEARCHES_KEY)
    return delay(raw ? (JSON.parse(raw) as SavedSearch[]) : [], 120)
  } catch {
    return delay([], 120)
  }
}

export async function createSavedSearch(
  name: string,
  filters: Filters,
  mode: SavedSearch['mode'],
): Promise<SavedSearch> {
  const existing = await listSavedSearches()
  const entry: SavedSearch = {
    id: `S${Date.now()}`,
    name,
    filters,
    mode,
    active: true,
  }
  // SPEC section 3 caps saved searches at 10 per user.
  const next = [...existing, entry].slice(-10)
  localStorage.setItem(SEARCHES_KEY, JSON.stringify(next))
  return delay(entry, 120)
}

export async function deleteSavedSearch(id: string): Promise<void> {
  const existing = await listSavedSearches()
  localStorage.setItem(SEARCHES_KEY, JSON.stringify(existing.filter((s) => s.id !== id)))
  return delay(undefined, 100)
}

/** How many listings match, without fetching a page. Used by the filter sheet. */
export async function countMatches(filters: Filters): Promise<number> {
  return delay(MOCK_LISTINGS.filter((l) => matches(l, filters)).length, 120)
}
