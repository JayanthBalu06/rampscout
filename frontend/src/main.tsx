import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App'

// Establish the demo-session cookie once, before any page fires parallel requests.
// (If it fails, the app still renders and the first request creates the session.)
fetch(`${import.meta.env.VITE_API_BASE ?? '/api'}/session`, { method: 'POST', credentials: 'include' })
  .catch(() => undefined)
  .finally(() =>
    createRoot(document.getElementById('root')!).render(
      <StrictMode>
        <App />
      </StrictMode>,
    ),
  )
