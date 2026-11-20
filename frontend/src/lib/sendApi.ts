import { api } from '../api/client'
import type { Authorization, Contact, SendRoutesResponse } from '../api/types'

/** Saved wallet recipient for a pasted address + token (reuses an existing one). */
export const walletContact = (address: string, currency: string) =>
  api<Contact>('/contacts', { method: 'POST', body: JSON.stringify({ kind: 'wallet', currency, wallet_address: address }) })

export const confirmContact = (id: string) => api<Contact>(`/contacts/${id}/confirm`, { method: 'POST' })

export const quoteRoutes = (contactId: string, amount: string, source?: 'live' | 'recorded') =>
  api<SendRoutesResponse>('/send/routes', {
    method: 'POST',
    body: JSON.stringify({ contact_id: contactId, amount_usdc: amount, ...(source ? { source } : {}) }),
  })

export const startSendWatch = (body: {
  contact_id: string
  amount_usdc: string
  min_out: string
  deadline?: string
  deadline_local?: string
  time_zone: string
  mode: 'notify' | 'auto'
  intent_text?: string
}) =>
  api<Authorization>('/send/watch', {
    method: 'POST',
    headers: { 'Idempotency-Key': crypto.randomUUID() },
    body: JSON.stringify(body),
  })

export const sendHref = (contactId: string, amount: string) => `#/send?to=${contactId}&amount=${encodeURIComponent(amount)}`
