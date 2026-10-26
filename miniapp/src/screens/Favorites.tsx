/** Saved listings (SPEC section 10 "Favorites"). */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ListingCardView } from '../components/ListingCardView'
import { CardSkeleton, EmptyState, ErrorState } from '../components/ui'
import { listFavorites, toggleFavorite } from '../data/client'
import { useI18n } from '../i18n/useI18n'

export function Favorites({ onOpen }: { onOpen: (id: string) => void }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()

  const query = useQuery({ queryKey: ['favorites'], queryFn: listFavorites })

  const favorite = useMutation({
    mutationFn: toggleFavorite,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['favorites'] })
      void queryClient.invalidateQueries({ queryKey: ['listings'] })
    },
  })

  return (
    <>
      <header className="sticky top-0 z-20 border-b border-tg-border bg-tg-secondary/95 px-4 py-3 backdrop-blur">
        <h1 className="text-base font-semibold">{t.navFavorites}</h1>
      </header>

      {query.isError ? (
        <ErrorState onRetry={() => void query.refetch()} />
      ) : query.isPending ? (
        <div className="space-y-2.5 p-3">
          <CardSkeleton />
          <CardSkeleton />
        </div>
      ) : query.data.length === 0 ? (
        <EmptyState title={t.noFavorites} hint={t.noFavoritesHint} />
      ) : (
        <div className="space-y-2.5 p-3">
          {query.data.map((listing) => (
            <ListingCardView
              key={listing.id}
              listing={listing}
              onOpen={onOpen}
              onToggleFavorite={(id) => favorite.mutate(id)}
            />
          ))}
        </div>
      )}
    </>
  )
}
