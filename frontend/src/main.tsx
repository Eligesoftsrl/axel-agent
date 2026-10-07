import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'
import { useStore } from './store'

// utile per debug dalla console del browser: __axel.getState()
;(window as unknown as { __axel: typeof useStore }).__axel = useStore

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
