/**
 * Mock listings.
 *
 * Written in the style the parser is expected to produce from real Telegram posts:
 * generated `title`, cleaned `description` with phones and links already stripped,
 * canonical district ids, prices normalised to USD. Replaced by the real API in
 * Phase 4 — see src/data/client.ts.
 */

import type { DistrictId, ListingDetail } from '../types'

/** Prototype exchange rate. Phase 2 reads the real CBU rate from `exchange_rates`. */
const UZS_PER_USD = 12_600

interface Seed {
  deal: 'sale' | 'rent'
  property: ListingDetail['property_type']
  rooms: number | null
  area: number | null
  land?: number
  floor: number | null
  floors: number | null
  /** The amount as posted, in `currency`. */
  price: number
  currency: 'USD' | 'UZS'
  period?: 'month' | 'day'
  district: DistrictId
  landmark: string
  building: ListingDetail['building_type']
  renovation: ListingDetail['renovation']
  negotiable: boolean
  photos: number
  hoursAgo: number
  description: string
  /** A previous USD price, when this listing had a drop. */
  priceDrop?: number
}

const SEEDS: Seed[] = [
  {
    deal: 'sale', property: 'apartment', rooms: 3, area: 75, floor: 4, floors: 9,
    price: 65000, currency: 'USD', district: 'chilonzor', landmark: 'Chilonzor metro, Qatortol',
    building: 'panel', renovation: 'euro', negotiable: true, photos: 6, hoursAgo: 2,
    description:
      'Chilonzor tumani, Qatortol ko\'chasi. 3 xonali kvartira, 75 m², 4/9-qavat.\nEvro ta\'mir qilingan, mebel bilan. Oshxona kengaytirilgan, konditsioner bor.\nMetroga 7 daqiqa piyoda. Maktab va bog\'cha yaqin.\nNarxi kelishiladi.',
    priceDrop: 68000,
  },
  {
    deal: 'sale', property: 'apartment', rooms: 2, area: 54, floor: 7, floors: 9,
    price: 48000, currency: 'USD', district: 'yunusobod', landmark: 'Shahriston, 4-kvartal',
    building: 'panel', renovation: 'good', negotiable: false, photos: 4, hoursAgo: 5,
    description:
      'Yunusobod 4-kvartal, Shahriston yonida. 2 xonali, 54 m², 7/9-qavat.\nYaxshi holatda, plastik derazalar, temir eshik.\nLift ishlaydi. Hovli obod, mashina uchun joy bor.',
  },
  {
    deal: 'rent', property: 'apartment', rooms: 2, area: 58, floor: 3, floors: 5,
    price: 400, currency: 'USD', period: 'month', district: 'mirobod', landmark: 'Oybek metro',
    building: 'brick', renovation: 'euro', negotiable: true, photos: 5, hoursAgo: 1,
    description:
      'Oybek metro yaqinida ijaraga 2 xonali kvartira beriladi.\n58 m², 3/5-qavat, g\'ishtli uy. Evro ta\'mir, sovutgich, kir yuvish mashinasi, televizor bor.\nOylik to\'lov, 1 oylik depozit. Oilaga beriladi.',
  },
  {
    deal: 'sale', property: 'apartment', rooms: 1, area: 36, floor: 2, floors: 4,
    price: 32000, currency: 'USD', district: 'olmazor', landmark: 'Olmazor bozori',
    building: 'brick', renovation: 'cosmetic', negotiable: true, photos: 3, hoursAgo: 9,
    description:
      'Olmazor tumani, bozor yaqinida 1 xonali kvartira sotiladi.\n36 m², 2/4-qavat. Kosmetik ta\'mir. Hujjatlari tayyor.\nNarxi bo\'yicha kelishamiz.',
  },
  {
    deal: 'sale', property: 'house', rooms: 5, area: 180, land: 6, floor: null, floors: 2,
    price: 145000, currency: 'USD', district: 'yashnobod', landmark: 'Parkent bozori',
    building: 'brick', renovation: 'good', negotiable: true, photos: 8, hoursAgo: 14,
    description:
      'Yashnobod tumani, Parkent bozoriga yaqin. Hovli uy sotiladi.\n6 sotix yer, 180 m² qurilish maydoni, 2 qavatli, 5 xona.\nGaraj, oshxona alohida, tok va gaz bor. Daraxtlar ko\'p.\nHujjatlar tayyor, kadastr bor.',
  },
  {
    deal: 'rent', property: 'apartment', rooms: 3, area: 80, floor: 5, floors: 9,
    price: 550, currency: 'USD', period: 'month', district: 'mirzo_ulugbek',
    landmark: 'Buyuk Ipak Yo\'li metro',
    building: 'panel', renovation: 'euro', negotiable: false, photos: 7, hoursAgo: 3,
    description:
      'Mirzo Ulug\'bek tumani, Buyuk Ipak Yo\'li metro yonida.\n3 xonali kvartira ijaraga beriladi. 80 m², 5/9-qavat.\nTo\'liq jihozlangan, 2 ta konditsioner, internet ulangan.\nUzoq muddatga beriladi.',
  },
  {
    deal: 'sale', property: 'apartment', rooms: 4, area: 105, floor: 8, floors: 12,
    price: 118000, currency: 'USD', district: 'yunusobod', landmark: 'Minor masjidi',
    building: 'monolith', renovation: 'euro', negotiable: false, photos: 9, hoursAgo: 20,
    description:
      'Yunusobod, Minor masjidi yaqinida yangi binoda 4 xonali kvartira.\n105 m², 8/12-qavat, monolit uy. Evro ta\'mir, issiq pol (teplyy pol).\nYopiq hovli, qo\'riqlanadi, yer osti avtoturargoh.\nBank krediti orqali ham olish mumkin.',
  },
  {
    deal: 'sale', property: 'apartment', rooms: 2, area: 48, floor: 1, floors: 5,
    price: 41000, currency: 'USD', district: 'uchtepa', landmark: 'Chorsu tomon, Qorasaroy',
    building: 'panel', renovation: 'needs_repair', negotiable: true, photos: 2, hoursAgo: 30,
    description:
      'Uchtepa tumani, Qorasaroy. 2 xonali kvartira, 48 m², 1/5-qavat.\nTa\'mir talab qiladi, shuning uchun narxi arzon.\nBirinchi qavat — do\'kon yoki ofis qilish mumkin.',
  },
  {
    deal: 'rent', property: 'room', rooms: 1, area: 18, floor: 2, floors: 4,
    price: 150, currency: 'USD', period: 'month', district: 'shayxontohur',
    landmark: 'Gospital bozori',
    building: 'brick', renovation: 'cosmetic', negotiable: false, photos: 2, hoursAgo: 6,
    description:
      'Shayxontohur tumani, Gospital bozori yaqinida xona ijaraga beriladi.\n18 m², alohida kirish. Oshxona va hammom umumiy.\nTalabalar yoki yolg\'iz ishlaydiganlar uchun qulay.',
  },
  {
    deal: 'sale', property: 'land', rooms: null, area: null, land: 10, floor: null, floors: null,
    price: 85000, currency: 'USD', district: 'sergeli', landmark: 'Sergeli-7',
    building: 'unknown', renovation: 'unknown', negotiable: true, photos: 3, hoursAgo: 48,
    description:
      'Sergeli-7, asfalt yo\'l bo\'yida 10 sotix yer sotiladi.\nQurilishga ruxsat bor, kommunikatsiyalar yaqin: tok, gaz, suv.\nBiznes yoki uy qurish uchun qulay joy. Hujjatlari tayyor.',
  },
  {
    deal: 'sale', property: 'apartment', rooms: 3, area: 68, floor: 6, floors: 9,
    price: 58000, currency: 'USD', district: 'chilonzor', landmark: 'Mirzo Ulug\'bek ko\'chasi',
    building: 'panel', renovation: 'good', negotiable: true, photos: 5, hoursAgo: 11,
    description:
      'Chilonzor, 19-kvartal. 3 xonali kvartira, 68 m², 6/9-qavat.\nYaxshi ta\'mir, xonalar alohida. Balkon shishalangan.\nTransport qulay, avtobus bekati yonida.',
  },
  {
    deal: 'rent', property: 'commercial', rooms: null, area: 120, floor: 1, floors: 5,
    price: 1200, currency: 'USD', period: 'month', district: 'mirobod',
    landmark: 'Amir Temur ko\'chasi',
    building: 'monolith', renovation: 'euro', negotiable: true, photos: 4, hoursAgo: 26,
    description:
      'Mirobod tumani, Amir Temur ko\'chasida savdo maydoni ijaraga beriladi.\n120 m², 1-qavat, ko\'chaga chiqishi bor, vitrina derazalar.\nDo\'kon, salon yoki ofis uchun. Avtoturargoh bor.',
  },
  {
    deal: 'sale', property: 'apartment', rooms: 2, area: 52, floor: 3, floors: 4,
    price: 44000, currency: 'USD', district: 'yakkasaroy', landmark: 'Qo\'shbegi, Mustaqillik',
    building: 'brick', renovation: 'good', negotiable: false, photos: 6, hoursAgo: 4,
    description:
      'Yakkasaroy tumani, markazda. 2 xonali kvartira, 52 m², 3/4-qavat.\nG\'ishtli uy, shift baland. Ta\'mirlangan, mebel qoladi.\nMarkazga yaqin, hamma joyga piyoda borish mumkin.',
  },
  {
    deal: 'sale', property: 'house', rooms: 4, area: 140, land: 4, floor: null, floors: 1,
    price: 95000, currency: 'USD', district: 'bektemir', landmark: 'Bektemir markazi',
    building: 'brick', renovation: 'cosmetic', negotiable: true, photos: 5, hoursAgo: 60,
    description:
      'Bektemir tumani markazida hovli uy sotiladi.\n4 sotix, 140 m², 1 qavatli, 4 xona.\nTok, gaz, suv markaziy. Hovlida mevali daraxtlar.\nTinch joy, maktab yaqin.',
  },
  {
    deal: 'rent', property: 'apartment', rooms: 1, area: 40, floor: 4, floors: 9,
    price: 280, currency: 'USD', period: 'month', district: 'olmazor',
    landmark: 'Shifokorlar shaharchasi',
    building: 'panel', renovation: 'good', negotiable: false, photos: 3, hoursAgo: 8,
    description:
      'Olmazor, Shifokorlar shaharchasi. 1 xonali kvartira ijaraga.\n40 m², 4/9-qavat. Jihozlangan: sovutgich, kir yuvish mashinasi, divan.\nKommunal to\'lov alohida.',
  },
  {
    deal: 'sale', property: 'apartment', rooms: 3, area: 88, floor: 10, floors: 16,
    price: 92000, currency: 'USD', district: 'yangihayot', landmark: 'Yangihayot, yangi massiv',
    building: 'monolith', renovation: 'none', negotiable: false, photos: 4, hoursAgo: 16,
    description:
      'Yangihayot tumani, yangi qurilgan turar-joy majmuasi.\n3 xonali, 88 m², 10/16-qavat. Ta\'mirsiz, "oq qoralama" holatda.\nUy topshirilgan, hujjatlar tayyor. To\'lov bo\'lib-bo\'lib mumkin.',
  },
  {
    deal: 'sale', property: 'apartment', rooms: 2, area: 60, floor: 5, floors: 5,
    price: 630000000, currency: 'UZS', district: 'uchtepa', landmark: 'Uchtepa bozori',
    building: 'panel', renovation: 'good', negotiable: true, photos: 4, hoursAgo: 22,
    description:
      'Uchtepa tumani, bozor yonida 2 xonali kvartira sotiladi.\n60 m², 5/5-qavat, tom yangi yopilgan.\nNarxi so\'mda, kelishiladi. Hujjatlar tayyor.',
  },
  {
    deal: 'rent', property: 'house', rooms: 6, area: 220, land: 8, floor: null, floors: 2,
    price: 1500, currency: 'USD', period: 'month', district: 'mirzo_ulugbek',
    landmark: 'Durmon yo\'li',
    building: 'brick', renovation: 'euro', negotiable: true, photos: 10, hoursAgo: 34,
    description:
      'Mirzo Ulug\'bek tumani, Durmon yo\'li. Hovli uy ijaraga beriladi.\n8 sotix, 220 m², 2 qavat, 6 xona. Basseyn, garaj, oshxona alohida.\nTo\'liq jihozlangan. Elchixona xodimlari yoki katta oila uchun.',
  },
  {
    deal: 'sale', property: 'apartment', rooms: 1, area: 42, floor: 6, floors: 12,
    price: 39000, currency: 'USD', district: 'sergeli', landmark: 'Sergeli metro',
    building: 'monolith', renovation: 'euro', negotiable: false, photos: 5, hoursAgo: 7,
    description:
      'Sergeli metro yonida 1 xonali kvartira. 42 m², 6/12-qavat.\nEvro ta\'mir, yangi mebel. Lift, qo\'riqlanadigan hovli.\nMetroga 3 daqiqa.',
  },
  {
    deal: 'sale', property: 'apartment', rooms: 4, area: 98, floor: 2, floors: 9,
    price: 79000, currency: 'USD', district: 'shayxontohur', landmark: 'Beruniy metro',
    building: 'panel', renovation: 'good', negotiable: true, photos: 7, hoursAgo: 40,
    description:
      'Shayxontohur, Beruniy metro yaqinida 4 xonali kvartira.\n98 m², 2/9-qavat. Xonalar alohida, 2 ta balkon.\nMaktab, bog\'cha, poliklinika yonida. Narx kelishiladi.',
  },
  {
    deal: 'rent', property: 'apartment', rooms: 2, area: 50, floor: 8, floors: 9,
    price: 320, currency: 'USD', period: 'month', district: 'chilonzor',
    landmark: 'Novza metro',
    building: 'panel', renovation: 'cosmetic', negotiable: false, photos: 3, hoursAgo: 12,
    description:
      'Novza metro yaqinida 2 xonali kvartira ijaraga beriladi.\n50 m², 8/9-qavat. Oddiy ta\'mir, zarur mebel bor.\nTalabalarga ham beriladi.',
  },
  {
    deal: 'sale', property: 'apartment', rooms: 3, area: 72, floor: 3, floors: 9,
    price: 61000, currency: 'USD', district: 'yashnobod', landmark: 'Tuzel, Avtovokzal',
    building: 'panel', renovation: 'euro', negotiable: true, photos: 6, hoursAgo: 18,
    description:
      'Yashnobod tumani, Tuzel. 3 xonali kvartira, 72 m², 3/9-qavat.\nEvro ta\'mir tugagan, hech kim yashamagan.\nAvtovokzal va bozor yaqin. Hujjatlar tayyor.',
    priceDrop: 64000,
  },
  {
    deal: 'sale', property: 'apartment', rooms: 2, area: 56, floor: 9, floors: 9,
    price: 43000, currency: 'USD', district: 'yunusobod', landmark: 'Qoraqamish',
    building: 'panel', renovation: 'needs_repair', negotiable: true, photos: 3, hoursAgo: 52,
    description:
      'Qoraqamish massivi, 2 xonali kvartira. 56 m², 9/9-qavat.\nTa\'mir kerak. Tom yangilangan, oqmaydi.\nArzon narxda, tez sotiladi.',
  },
  {
    deal: 'rent', property: 'apartment', rooms: 1, area: 35, floor: 2, floors: 5,
    price: 35, currency: 'USD', period: 'day', district: 'mirobod',
    landmark: 'Toshkent shahri markazi',
    building: 'brick', renovation: 'euro', negotiable: false, photos: 5, hoursAgo: 2,
    description:
      'Markazda sutkalik kvartira. 1 xonali, 35 m², 2/5-qavat.\nEvro ta\'mir, Wi-Fi, konditsioner, barcha qulayliklar.\nMehmonlar va ish safari uchun qulay. Hisob-faktura beriladi.',
  },
]

const DISTRICT_LABEL: Record<DistrictId, string> = {
  bektemir: 'Bektemir',
  chilonzor: 'Chilonzor',
  mirobod: 'Mirobod',
  mirzo_ulugbek: 'Mirzo Ulug\'bek',
  olmazor: 'Olmazor',
  sergeli: 'Sergeli',
  shayxontohur: 'Shayxontohur',
  uchtepa: 'Uchtepa',
  yakkasaroy: 'Yakkasaroy',
  yashnobod: 'Yashnobod',
  yunusobod: 'Yunusobod',
  yangihayot: 'Yangihayot',
}

const PROPERTY_LABEL_UZ: Record<ListingDetail['property_type'], string> = {
  apartment: 'kvartira',
  house: 'hovli uy',
  land: 'yer uchastka',
  commercial: 'tijorat obyekti',
  room: 'xona',
  other: 'obyekt',
}

/** Builds the short generated title the parser produces (SPEC 6.2, max 80 chars). */
function buildTitle(seed: Seed): string {
  const parts: string[] = []
  if (seed.rooms && seed.property !== 'land') parts.push(`${seed.rooms} xonali`)
  parts.push(PROPERTY_LABEL_UZ[seed.property])
  parts.push(DISTRICT_LABEL[seed.district])
  if (seed.property === 'land' && seed.land) parts.push(`${seed.land} sotix`)
  else if (seed.area) parts.push(`${seed.area} m²`)
  return parts.join(', ').slice(0, 80)
}

const SOURCE_NAMES = [
  'Toshkent kvartira sotuv',
  'Uy joy e\'lonlari TOSHKENT',
  'Недвижимость Ташкент',
  'Kvartira ijara Toshkent',
  'TOSHKENT UY-JOY BOZORI',
]

/** Builds the full dataset once, at module load. */
function build(): ListingDetail[] {
  const now = Date.now()
  return SEEDS.map((seed, i) => {
    const firstSeen = new Date(now - seed.hoursAgo * 3_600_000)
    // No URLs yet: MinIO starts serving real images once the collector runs
    // (Phase 1). The Photo component draws a placeholder meanwhile.
    const photos = Array.from({ length: seed.photos }, () => ({
      large_url: null,
      thumb_url: null,
      width: 1280,
      height: 960,
    }))

    // The same flat is cross-posted; 1–3 sources per listing mirrors reality.
    const sourceCount = 1 + (i % 3)
    const sources = Array.from({ length: sourceCount }, (_, s) => ({
      title: SOURCE_NAMES[(i + s) % SOURCE_NAMES.length]!,
      tg_link: s === 2 ? null : `https://t.me/c/${1000000 + i * 7 + s}/${100 + i}`,
      seen_at: new Date(firstSeen.getTime() + s * 1_800_000).toISOString(),
    }))

    // The scheduler keeps `exchange_rates` current; 12 600 is a plausible
    // UZS/USD rate for the prototype (SPEC 6.3). price_usd is always USD so that
    // filtering and sorting compare like with like.
    const priceUsd =
      seed.currency === 'UZS' ? Math.round(seed.price / UZS_PER_USD) : seed.price

    const priceHistory = seed.priceDrop
      ? [
          {
            price_usd: seed.priceDrop,
            observed_at: new Date(firstSeen.getTime() - 86_400_000 * 3).toISOString(),
          },
          { price_usd: priceUsd, observed_at: firstSeen.toISOString() },
        ]
      : [{ price_usd: priceUsd, observed_at: firstSeen.toISOString() }]

    return {
      id: `L${String(i + 1).padStart(4, '0')}`,
      title: buildTitle(seed),
      deal_type: seed.deal,
      property_type: seed.property,
      price_amount: seed.price,
      price_currency: seed.currency,
      price_usd: priceUsd,
      price_period: seed.period ?? null,
      price_per_m2:
        seed.area && seed.deal === 'sale' ? Math.round(priceUsd / seed.area) : null,
      district: seed.district,
      rooms: seed.rooms,
      area_m2: seed.area,
      land_sotix: seed.land ?? null,
      floor: seed.floor,
      floors_total: seed.floors,
      thumb_url: null,
      photo_count: seed.photos,
      first_seen_at: firstSeen.toISOString(),
      last_seen_at: new Date(firstSeen.getTime() + 3_600_000).toISOString(),
      is_favorite: false,
      description: seed.description,
      landmark: seed.landmark,
      address_text: null,
      building_type: seed.building,
      renovation: seed.renovation,
      negotiable: seed.negotiable,
      status: 'active',
      photos,
      sources,
      price_history: priceHistory,
    }
  })
}

export const MOCK_LISTINGS: ListingDetail[] = build()

export { DISTRICT_LABEL }
