/** Swipeable photo gallery. Native scroll-snap rather than a carousel library. */

import { useRef, useState } from 'react'

import type { ListingPhoto } from '../types'
import { Photo } from './Photo'

export function Gallery({ photos, seedKey }: { photos: ListingPhoto[]; seedKey: string }) {
  const [index, setIndex] = useState(0)
  const trackRef = useRef<HTMLDivElement>(null)

  if (photos.length === 0) {
    return <div className="aspect-[4/3] w-full bg-tg-secondary" />
  }

  const onScroll = () => {
    const track = trackRef.current
    if (!track) return
    setIndex(Math.round(track.scrollLeft / track.clientWidth))
  }

  return (
    <div className="relative">
      <div
        ref={trackRef}
        onScroll={onScroll}
        className="no-scrollbar flex snap-x snap-mandatory overflow-x-auto"
      >
        {photos.map((photo, i) => (
          <Photo
            key={i}
            src={photo.large_url}
            seedKey={`${seedKey}-${i}`}
            eager={i === 0}
            className="aspect-[4/3] w-full shrink-0 snap-center object-cover"
          />
        ))}
      </div>

      {photos.length > 1 ? (
        <>
          <div className="pointer-events-none absolute bottom-3 left-1/2 flex -translate-x-1/2 gap-1.5">
            {photos.map((_, i) => (
              <span
                key={i}
                className={[
                  'h-1.5 rounded-full transition-all',
                  i === index ? 'w-4 bg-white' : 'w-1.5 bg-white/50',
                ].join(' ')}
              />
            ))}
          </div>
          <span className="pointer-events-none absolute right-3 top-3 rounded-md bg-black/55 px-2 py-0.5 text-xs font-medium text-white">
            {index + 1} / {photos.length}
          </span>
        </>
      ) : null}
    </div>
  )
}
