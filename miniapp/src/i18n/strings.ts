/**
 * Translations.
 *
 * Uzbek (Latin) is the default, Russian is the alternative (SPEC 1.3). Keys are
 * grouped by screen. Nothing user-facing may be hardcoded in a component.
 */

import type { DistrictId, Language, PropertyType, Renovation, SortOption } from '../types'

export interface Strings {
  appName: string
  // Navigation
  navFeed: string
  navFavorites: string
  navSearches: string
  navSettings: string
  // Feed
  sale: string
  rent: string
  filters: string
  rooms: string
  anyRooms: string
  roomsShort: (n: number) => string
  roomsPlus: (n: number) => string
  resultsCount: (n: number) => string
  nothingFound: string
  nothingFoundHint: string
  resetFilters: string
  loadMore: string
  loadError: string
  retry: string
  // Filter sheet
  dealType: string
  propertyType: string
  district: string
  anyDistrict: string
  priceUsd: string
  areaM2: string
  from: string
  to: string
  onlyWithPhotos: string
  sortBy: string
  searchPlaceholder: string
  apply: string
  applyWithCount: (n: number) => string
  reset: string
  saveSearch: string
  // Detail
  perM2: string
  perMonth: string
  perDay: string
  negotiable: string
  priceUnknown: string
  floorOf: (floor: number, total: number) => string
  landArea: string
  buildingType: string
  renovationLabel: string
  contactSeller: string
  contactHint: string
  originalPost: string
  originalPosts: string
  priceHistory: string
  priceDropped: (from: string, to: string) => string
  report: string
  reportSent: string
  seenIn: (n: number) => string
  descriptionLabel: string
  detailsLabel: string
  // Favorites
  noFavorites: string
  noFavoritesHint: string
  // Saved searches
  noSearches: string
  noSearchesHint: string
  createFromFilters: string
  notifyInstant: string
  notifyDaily: string
  deleteSearch: string
  searchNamePrompt: string
  maxSearches: string
  // Settings
  language: string
  notifications: string
  notificationsHint: string
  privacyPolicy: string
  aboutHint: string
  // Shared
  time: {
    justNow: string
    minutesAgo: (n: number) => string
    hoursAgo: (n: number) => string
    daysAgo: (n: number) => string
  }
  districts: Record<DistrictId, string>
  properties: Record<PropertyType, string>
  renovations: Record<Renovation, string>
  sorts: Record<SortOption, string>
}

const uz: Strings = {
  appName: 'UyHub',
  navFeed: 'E\'lonlar',
  navFavorites: 'Saqlangan',
  navSearches: 'Qidiruvlar',
  navSettings: 'Sozlamalar',

  sale: 'Sotuv',
  rent: 'Ijara',
  filters: 'Filtr',
  rooms: 'Xonalar',
  anyRooms: 'Farqi yo\'q',
  roomsShort: (n) => `${n} xona`,
  roomsPlus: (n) => `${n}+ xona`,
  resultsCount: (n) => `${n} ta e'lon`,
  nothingFound: 'E\'lon topilmadi',
  nothingFoundHint: 'Filtrlarni kengaytirib ko\'ring yoki keyinroq qayting.',
  resetFilters: 'Filtrlarni tozalash',
  loadMore: 'Yana yuklash',
  loadError: 'Yuklashda xatolik',
  retry: 'Qayta urinish',

  dealType: 'Bitim turi',
  propertyType: 'Obyekt turi',
  district: 'Tuman',
  anyDistrict: 'Barcha tumanlar',
  priceUsd: 'Narx, $',
  areaM2: 'Maydon, m²',
  from: 'dan',
  to: 'gacha',
  onlyWithPhotos: 'Faqat rasmli e\'lonlar',
  sortBy: 'Saralash',
  searchPlaceholder: 'Mo\'ljal yoki sarlavha bo\'yicha qidirish',
  apply: 'Qo\'llash',
  applyWithCount: (n) => `${n} ta e'lonni ko'rish`,
  reset: 'Tozalash',
  saveSearch: 'Qidiruvni saqlash',

  perM2: 'm² uchun',
  perMonth: 'oyiga',
  perDay: 'kuniga',
  negotiable: 'Kelishiladi',
  priceUnknown: 'Narx ko\'rsatilmagan',
  floorOf: (floor, total) => `${floor}/${total}-qavat`,
  landArea: 'Yer maydoni',
  buildingType: 'Uy turi',
  renovationLabel: 'Ta\'mir',
  contactSeller: 'Asl e\'lonni ochish',
  contactHint: 'Telefon raqam saqlanmaydi — u asl postda turadi',
  originalPost: 'Asl e\'lon',
  originalPosts: 'Asl e\'lonlar',
  priceHistory: 'Narx tarixi',
  priceDropped: (from, to) => `Narx tushdi: ${from} → ${to}`,
  report: 'Shikoyat qilish',
  reportSent: 'Shikoyat yuborildi. Rahmat!',
  seenIn: (n) => `${n} ta guruhda topildi`,
  descriptionLabel: 'Tavsif',
  detailsLabel: 'Asosiy ma\'lumotlar',

  noFavorites: 'Saqlangan e\'lonlar yo\'q',
  noFavoritesHint: 'E\'lon yonidagi yurakchani bosib, uni shu yerga saqlang.',

  noSearches: 'Saqlangan qidiruvlar yo\'q',
  noSearchesHint:
    'Filtrlarni sozlang va "Qidiruvni saqlash" tugmasini bosing — mos e\'lon chiqsa, bot xabar beradi.',
  createFromFilters: 'Joriy filtrlardan yaratish',
  notifyInstant: 'Darhol xabar',
  notifyDaily: 'Kunlik to\'plam',
  deleteSearch: 'O\'chirish',
  searchNamePrompt: 'Qidiruv nomi',
  maxSearches: 'Ko\'pi bilan 10 ta qidiruv saqlanadi',

  language: 'Til',
  notifications: 'Bildirishnomalar',
  notificationsHint: 'Saqlangan qidiruvlaringizga mos e\'lonlar haqida bot xabar beradi.',
  privacyPolicy: 'Maxfiylik siyosati',
  aboutHint: 'E\'lonlar ochiq Telegram guruhlaridan to\'planadi. Har bir e\'londa manbaga havola bor.',

  time: {
    justNow: 'hozirgina',
    minutesAgo: (n) => `${n} daqiqa oldin`,
    hoursAgo: (n) => `${n} soat oldin`,
    daysAgo: (n) => `${n} kun oldin`,
  },

  districts: {
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
  },
  properties: {
    apartment: 'Kvartira',
    house: 'Hovli uy',
    land: 'Yer uchastka',
    commercial: 'Tijorat',
    room: 'Xona',
    other: 'Boshqa',
  },
  renovations: {
    euro: 'Evro ta\'mir',
    good: 'Yaxshi',
    cosmetic: 'Kosmetik',
    needs_repair: 'Ta\'mir talab',
    none: 'Ta\'mirsiz',
    unknown: 'Noma\'lum',
  },
  sorts: {
    new: 'Avval yangilari',
    price_asc: 'Avval arzonlari',
    price_desc: 'Avval qimmatlari',
    price_per_m2: 'm² narxi bo\'yicha',
  },
}

const ru: Strings = {
  appName: 'UyHub',
  navFeed: 'Объявления',
  navFavorites: 'Избранное',
  navSearches: 'Поиски',
  navSettings: 'Настройки',

  sale: 'Продажа',
  rent: 'Аренда',
  filters: 'Фильтр',
  rooms: 'Комнаты',
  anyRooms: 'Неважно',
  roomsShort: (n) => `${n} комн.`,
  roomsPlus: (n) => `${n}+ комн.`,
  resultsCount: (n) => `${n} объявлений`,
  nothingFound: 'Ничего не найдено',
  nothingFoundHint: 'Попробуйте расширить фильтры или зайдите позже.',
  resetFilters: 'Сбросить фильтры',
  loadMore: 'Загрузить ещё',
  loadError: 'Ошибка загрузки',
  retry: 'Повторить',

  dealType: 'Тип сделки',
  propertyType: 'Тип объекта',
  district: 'Район',
  anyDistrict: 'Все районы',
  priceUsd: 'Цена, $',
  areaM2: 'Площадь, м²',
  from: 'от',
  to: 'до',
  onlyWithPhotos: 'Только с фото',
  sortBy: 'Сортировка',
  searchPlaceholder: 'Поиск по ориентиру или заголовку',
  apply: 'Применить',
  applyWithCount: (n) => `Показать ${n} объявлений`,
  reset: 'Сбросить',
  saveSearch: 'Сохранить поиск',

  perM2: 'за м²',
  perMonth: 'в месяц',
  perDay: 'в сутки',
  negotiable: 'Торг уместен',
  priceUnknown: 'Цена не указана',
  floorOf: (floor, total) => `${floor}/${total} этаж`,
  landArea: 'Площадь участка',
  buildingType: 'Тип дома',
  renovationLabel: 'Ремонт',
  contactSeller: 'Открыть оригинал объявления',
  contactHint: 'Телефон не хранится — он в оригинальном посте',
  originalPost: 'Оригинал объявления',
  originalPosts: 'Оригиналы объявлений',
  priceHistory: 'История цены',
  priceDropped: (from, to) => `Цена снижена: ${from} → ${to}`,
  report: 'Пожаловаться',
  reportSent: 'Жалоба отправлена. Спасибо!',
  seenIn: (n) => `Найдено в ${n} группах`,
  descriptionLabel: 'Описание',
  detailsLabel: 'Характеристики',

  noFavorites: 'Нет сохранённых объявлений',
  noFavoritesHint: 'Нажмите на сердечко рядом с объявлением, чтобы сохранить его здесь.',

  noSearches: 'Нет сохранённых поисков',
  noSearchesHint:
    'Настройте фильтры и нажмите «Сохранить поиск» — бот пришлёт уведомление о подходящих объявлениях.',
  createFromFilters: 'Создать из текущих фильтров',
  notifyInstant: 'Сразу',
  notifyDaily: 'Раз в день',
  deleteSearch: 'Удалить',
  searchNamePrompt: 'Название поиска',
  maxSearches: 'Можно сохранить не более 10 поисков',

  language: 'Язык',
  notifications: 'Уведомления',
  notificationsHint: 'Бот пришлёт объявления, подходящие под сохранённые поиски.',
  privacyPolicy: 'Политика конфиденциальности',
  aboutHint:
    'Объявления собираются из открытых Telegram-групп. У каждого объявления есть ссылка на источник.',

  time: {
    justNow: 'только что',
    minutesAgo: (n) => `${n} мин. назад`,
    hoursAgo: (n) => `${n} ч. назад`,
    daysAgo: (n) => `${n} дн. назад`,
  },

  districts: {
    bektemir: 'Бектемир',
    chilonzor: 'Чиланзар',
    mirobod: 'Мирабад',
    mirzo_ulugbek: 'Мирзо-Улугбек',
    olmazor: 'Алмазар',
    sergeli: 'Сергели',
    shayxontohur: 'Шайхантахур',
    uchtepa: 'Учтепа',
    yakkasaroy: 'Яккасарай',
    yashnobod: 'Яшнабад',
    yunusobod: 'Юнусабад',
    yangihayot: 'Янгихаёт',
  },
  properties: {
    apartment: 'Квартира',
    house: 'Частный дом',
    land: 'Участок',
    commercial: 'Коммерция',
    room: 'Комната',
    other: 'Другое',
  },
  renovations: {
    euro: 'Евроремонт',
    good: 'Хороший',
    cosmetic: 'Косметический',
    needs_repair: 'Требует ремонта',
    none: 'Без ремонта',
    unknown: 'Не указан',
  },
  sorts: {
    new: 'Сначала новые',
    price_asc: 'Сначала дешёвые',
    price_desc: 'Сначала дорогие',
    price_per_m2: 'По цене за м²',
  },
}

export const STRINGS: Record<Language, Strings> = { uz, ru }
