// Ariadne Desktop: the chat-and-sessions shell around Ariadne's worker.
// - Hides the nav rows Ariadne does not support (Capabilities, Messaging platforms, Artifacts, Scheduled jobs);
//   new chat + the sessions list stay.
// - Shows what the local model is doing (status bar) and, above the composer, when a task holds it.
// - Park / Resume: a deliberate choice. Parking lets the step in flight finish, then frees the model for chat;
//   nothing is ever parked automatically.
import { Button, COMPOSER_AREAS, SIDEBAR_NAV_PREFS_AREA, useMutation, useQuery, queryClient } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'

const KEY = ['ariadne', 'status']

function minutes(since) {
  if (!since) return ''
  const m = Math.max(0, Math.round((Date.now() / 1000 - since) / 60))
  return m < 1 ? 'just now' : `${m} min`
}

function useStatus(ctx) {
  return useQuery({ queryKey: KEY, queryFn: () => ctx.rest('/status'), refetchInterval: 3000 })
}

function useAction(ctx, path) {
  return useMutation({
    mutationFn: () => ctx.rest(path, { method: 'POST' }),
    onSuccess: data => queryClient.setQueryData(KEY, data)
  })
}

function state(s) {
  if (!s) return 'unknown'
  if (s.park && s.park.parked) return 'parked'
  if (s.park) return 'parking'
  return s.busy ? 'busy' : 'idle'
}

function Chip({ ctx }) {
  const { data } = useStatus(ctx)
  const st = state(data)
  const t = data && data.task
  const label =
    st === 'idle' ? 'Ariadne: model free'
    : st === 'parked' ? `Ariadne: task ${data.park.task} parked`
    : st === 'parking' ? 'Ariadne: parking at the next step'
    : st === 'busy' ? `Ariadne: ${t.flow || 'task'} ${t.status} ${t.id} (${minutes(t.since)})`
    : 'Ariadne'
  const recent = (data && data.recent) || []
  return jsx('span', {
    className: 'px-1.5 text-[0.6875rem] text-(--ui-text-tertiary) whitespace-nowrap',
    title: recent.join('\n'),
    children: label
  })
}

function Banner({ ctx }) {
  const { data } = useStatus(ctx)
  const parkIt = useAction(ctx, '/park')
  const resume = useAction(ctx, '/resume')
  const st = state(data)
  if (st === 'idle' || st === 'unknown') return null
  const t = data.task
  const last = (data.recent || []).slice(-1)[0] || ''
  const text =
    st === 'parked'
      ? `Task ${data.park.task} is parked: the model is yours. Resume it when you are done.`
      : st === 'parking'
        ? 'Parking: the task finishes the step in flight, then the model is yours.'
        : `The local model is working on task ${t.id} (${t.flow}, ${t.status}, ${minutes(t.since)}). ` +
          'Your messages wait until its current run ends, or park it to talk now.'
  const button =
    st === 'parked'
      ? jsx(Button, { size: 'sm', onClick: () => resume.mutate(), disabled: resume.isPending, children: 'Resume task' })
      : st === 'busy'
        ? jsx(Button, { size: 'sm', variant: 'outline', onClick: () => parkIt.mutate(), disabled: parkIt.isPending,
                        children: 'Park task' })
        : null
  return jsxs('div', {
    className: 'flex items-start gap-2 px-3 py-1.5 text-xs text-(--ui-text-secondary)',
    children: [
      jsxs('div', {
        className: 'flex-1 min-w-0',
        children: [
          jsx('div', { children: text }),
          last ? jsx('div', { className: 'truncate text-(--ui-text-quaternary)', title: (data.recent || []).join('\n'),
                               children: last }) : null
        ]
      }),
      button
    ]
  })
}

export default {
  id: 'ariadne',
  name: 'Ariadne',
  register(ctx) {
    ctx.register({
      id: 'nav',
      area: SIDEBAR_NAV_PREFS_AREA,
      data: { hide: ['capabilities', 'messaging', 'artifacts', 'cron'], order: ['new-session'] }
    })
    ctx.register({ id: 'status', area: 'statusBar.left', order: 5, render: () => jsx(Chip, { ctx }) })
    ctx.register({ id: 'banner', area: COMPOSER_AREAS.top, render: () => jsx(Banner, { ctx }) })
  }
}
