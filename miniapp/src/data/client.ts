/**
 * Data access.
 *
 * This is the ONLY file that knows where listings come from. Every function
 * here maps to an endpoint in docs/SPEC.md section 9.2:
 *
 *   listListings   -> GET /v1/listings
 *   getListing     -> GET /v1/listings/{id}
 *   countMatches   -> GET /v1/listings?limit=1   (reads `total`)
 *
 * Favourites and saved searches are still local to the device. The server
 * tables exist but the write endpoints do not yet, and keeping them here means
 * the screens that use them did not have to change when the feed went live.
 *
 * There is no `revealContact`. Phone numbers are stored only as HMAC hashes
 * (docs/DECISIONS.md P.2), so no endpoint can return one; `ListingDetail.sources`
 * links to the original posts, where the number actually is.
 */

import type { Filters, ListingCard, ListingDetail, Page, SavedSearch } from '../types'
import { initData } from '../telegram'

/**
 * Where the API lives.
 *
 * Same-origin by default so a production build behind one reverse proxy needs
 * no configuration; `VITE_API_BASE_URL` points `npm run dev` at a local API.
 */
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

/** Raised for any non-2xx response, carrying the status so callers can branch. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(`${status}: ${detail}`)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, params?: URLSearchParams): Promise<T> {
  const url = `${API_BASE}${path}${params && [...params].length ? `?${params}` : ''}`

  // Telegram's initData is the credential (SPEC 9.1). Outside Telegram there
  // is none, and the API rejects the request unless it is running with
  // API_ALLOW_INSECURE_AUTH — which is how `npm run dev` works in a browser.
  const auth = initData()
  const response = await fetch(url, {
    headers: auth ? { Authorization: `tma ${auth}` } : {},
  })

  if (!response.ok) {
    throw new ApiError(response.status, await detailOf(response))
  }
  return (await response.json()) as T
}

async function detailOf(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    return typeof body.detail === 'string' ? body.detail : response.statusText
  } catch {
    return response.statusText
  }
}

// --- Local persistence ------------------------------------------------------
// Favourites and saved searches are per-device until the server write path
// exists. The feed's `is_favorite` is always false, so it is overlaid here.

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

// --- Filters to query parameters ---------------------------------------------

function queryOf(filters: Filters): URLSearchParams {
  const params = new URLSearchParams()
  params.set('deal_type', filters.deal_type)
  if (filters.property_type) params.set('property_type', filters.property_type)
  for (const district of filters.districts) params.append('district', district)

  if (filters.rooms.length) {
    // The chips are a set of exact counts where 4 means "4 or more", but the
    // API takes a range. A contiguous set converts exactly; a gapped one
    // ("1 or 3") widens to its span, so the extra rows are filtered out below.
    params.set('rooms_min', String(Math.min(...filters.rooms)))
    if (!filters.rooms.includes(4)) params.set('rooms_max', String(Math.max(...filters.rooms)))
  }

  if (filters.price_min !== null) params.set('price_min', String(filters.price_min))
  if (filters.price_max !== null) params.set('price_max', String(filters.price_max))
  if (filters.area_min !== null) params.set('area_min', String(filters.area_min))
  if (filters.area_max !== null) params.set('area_max', String(filters.area_max))
  if (filters.has_photos) params.set('has_photos', 'true')
  if (filters.q.trim()) params.set('q', filters.q.trim())
  params.set('sort', filters.sort)
  return params
}

/** Whether a gapped room selection needs client-side narrowing. */
function roomsAreGapped(rooms: number[]): boolean {
  if (rooms.length < 2) return false
  const span = Math.max(...rooms) - Math.min(...rooms) + 1
  return !rooms.includes(4) && span !== rooms.length
}

function matchesRooms(card: ListingCard, rooms: number[]): boolean {
  return rooms.some((r) => (r >= 4 ? (card.rooms ?? 0) >= 4 : card.rooms === r))
}

// --- API ----------------------------------------------------------------------

export async function listListings(
  filters: Filters,
  cursor: string | null,
): Promise<Page<ListingCard>> {
  const params = queryOf(filters)
  if (cursor) params.set('cursor', cursor)

  const page = await request<Page<ListingCard>>('/v1/listings', params)
  const favorites = favoriteIds()
  let items = page.items.map((item) => ({ ...item, is_favorite: favorites.has(item.id) }))
  if (roomsAreGapped(filters.rooms)) {
    items = items.filter((item) => matchesRooms(item, filters.rooms))
  }
  return { ...page, items }
}

export async function getListing(id: string): Promise<ListingDetail> {
  const listing = await request<ListingDetail>(`/v1/listings/${encodeURIComponent(id)}`)
  return { ...listing, is_favorite: favoriteIds().has(listing.id) }
}

/**
 * The favourited listings, fetched one by one.
 *
 * There is no server-side favourites endpoint yet, and the ids live on this
 * device. A listing that has since expired or been removed 404s, and is
 * dropped from the list rather than failing the whole screen.
 */
export async function listFavorites(): Promise<ListingCard[]> {
  const ids = [...favoriteIds()]
  const results = await Promise.all(
    ids.map((id) => getListing(id).catch(() => null)),
  )
  return results.filter((listing): listing is ListingDetail => listing !== null)
}

export async function toggleFavorite(id: string): Promise<boolean> {
  const favorites = favoriteIds()
  const now = !favorites.has(id)
  if (now) favorites.add(id)
  else favorites.delete(id)
  writeSet(FAVORITES_KEY, favorites)
  return now
}

export async function listSavedSearches(): Promise<SavedSearch[]> {
  try {
    const raw = localStorage.getItem(SEARCHES_KEY)
    return raw ? (JSON.parse(raw) as SavedSearch[]) : []
  } catch {
    return []
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
  return entry
}

export async function deleteSavedSearch(id: string): Promise<void> {
  const existing = await listSavedSearches()
  localStorage.setItem(SEARCHES_KEY, JSON.stringify(existing.filter((s) => s.id !== id)))
}

/** How many listings match, without fetching a page. Used by the filter sheet. */
export async function countMatches(filters: Filters): Promise<number> {
  const params = queryOf(filters)
  params.set('limit', '1')
  const page = await request<Page<ListingCard>>('/v1/listings', params)
  return page.total ?? page.items.length
}
