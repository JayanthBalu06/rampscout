const STYLES: Record<string, string> = {
  watching: 'bg-sky-100 text-sky-900 dark:bg-sky-900/50 dark:text-sky-100',
  notified: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-900/50 dark:text-emerald-100',
  completed: 'bg-emerald-600 text-white',
  claimed: 'bg-violet-100 text-violet-900 dark:bg-violet-900/50 dark:text-violet-100',
  executing: 'bg-violet-600 text-white',
  canceled: 'bg-neutral-200 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300',
  expired: 'bg-neutral-200 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300',
  payout_pending: 'bg-amber-100 text-amber-900 dark:bg-amber-900/50 dark:text-amber-100',
  failed: 'bg-red-600 text-white',
  requote_required: 'bg-amber-100 text-amber-900 dark:bg-amber-900/50 dark:text-amber-100',
}

const LABELS: Record<string, string> = {
  watching: 'Watching',
  notified: 'Target reached · notified',
  completed: 'Completed',
  claimed: 'Claimed for execution',
  executing: 'Executing',
  canceled: 'Canceled',
  expired: 'Expired unfilled',
  requote_required: 'Needs fresh quote',
  payout_pending: 'Transfer confirmed · payout pending',
  failed: 'Failed · no payout',
}

export function StatusPill({ status }: { status: string }) {
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${STYLES[status] ?? STYLES.canceled}`}>
      {LABELS[status] ?? status}
    </span>
  )
}
