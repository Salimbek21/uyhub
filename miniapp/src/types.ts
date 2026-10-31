/**
 * API contract.
 *
 * These types mirror the response shapes in docs/SPEC.md section 9.2 so that
 * switching from the mock data source to the real API is a change in
 * src/data/client.ts and nowhere else.
 */

export type DealType = 'sale' | 'rent'

export type PropertyType = 'apartment' | 'house' | 'land' | 'commercial' | 'room' | 'other'

/** The twelve districts of Tashkent (SPEC 6.5). */
export type DistrictId =
  | 'bektemir'
  | 'chilonzor'
  | 'mirobod'
  | 'mirzo_ulugbek'
  | 'olmazor'
  | 'sergeli'
  | 'shayxontohur'
  | 'uchtepa'
  | 'yakkasaroy'
  | 'yashnobod'
  | 'yunusobod'
  | 'yangihayot'

export type Renovation = 'euro' | 'good' | 'cosmetic' | 'needs_repair' | 'none' | 'unknown'

export type BuildingType = 'brick' | 'panel' | 'monolith' | 'other' | 'unknown'

export type SortOption = 'new' | 'price_asc' | 'price_desc' | 'price_per_m2'

/** A card in the feed — `GET /v1/listings`. */
export interface ListingCard {
  id: string
  title: string
  deal_type: DealType
  property_type: PropertyType
  /** Null when the post never named a price — rarer than it sounds, but real. */
  price_amount: number | null
  price_currency: 'USD' | 'UZS' | null
  /** Null for a UZS price seen while no exchange rate was available. */
  price_usd: number | null
  price_period: 'month' | 'day' | null
  price_per_m2: number | null
  district: DistrictId | null
  rooms: number | null
  area_m2: number | null
  /** Plot size in sotix (1 sotix = 100 m²). Set for land and houses. */
  land_sotix: number | null
  floor: number | null
  floors_total: number | null
  thumb_url: string | null
  photo_count: number
  first_seen_at: string
  is_favorite: boolean
}

/** One photo of a listing. */
export interface ListingPhoto {
  large_url: string | null
  thumb_url: string | null
  width: number | null
  height: number | null
}

/** Where a listing was seen — the attribution required by SPEC 13. */
export interface ListingSource {
  title: string
  tg_link: string | null
  seen_at: string
}

/** A price observation — `price_history` in SPEC section 3. */
export interface PriceObservation {
  price_usd: number
  observed_at: string
}

/** Full detail — `GET /v1/listings/{id}`. Never includes phones. */
export interface ListingDetail extends ListingCard {
  description: string | null
  landmark: string | null
  address_text: string | null
  building_type: BuildingType
  renovation: Renovation
  negotiable: boolean
  status: 'active' | 'sold' | 'expired' | 'removed'
  last_seen_at: string
  photos: ListingPhoto[]
  sources: ListingSource[]
  price_history: PriceObservation[]
}

/** Filters accepted by `GET /v1/listings`. */
export interface Filters {
  deal_type: DealType
  property_type: PropertyType | null
  districts: DistrictId[]
  rooms: number[]
  price_min: number | null
  price_max: number | null
  area_min: number | null
  area_max: number | null
  has_photos: boolean
  q: string
  sort: SortOption
}

/** Cursor-paginated result (SPEC 9.2). */
export interface Page<T> {
  items: T[]
  next_cursor: string | null
  /** Null when the server could not count — render "no count", never zero. */
  total: number | null
}

/** A saved search — `GET /v1/saved-searches`. */
export interface SavedSearch {
  id: string
  name: string
  filters: Filters
  mode: 'instant' | 'daily'
  active: boolean
}

export type Language = 'uz' | 'ru'

export const DEFAULT_FILTERS: Filters = {
  deal_type: 'sale',
  property_type: 'apartment',
  districts: [],
  rooms: [],
  price_min: null,
  price_max: null,
  area_min: null,
  area_max: null,
  has_photos: false,
  q: '',
  sort: 'new',
}
