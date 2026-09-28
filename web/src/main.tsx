import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import './styles.css'
import './dashboard.css'
import './flock.css'
import './today.css'
import './theme.css'
import './type.css'
import { applyTheme, currentTheme } from './lib/theme'
import Landing from './pages/Landing'
import CoopPage from './pages/Coop'
import NodePage from './pages/Node'
import Farm from './pages/Farm'
import Admin from './pages/Admin'
import { registerWorker } from './lib/push'

applyTheme(currentTheme())
registerWorker().catch(() => {})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/coop/:coopId" element={<CoopPage />} />
        <Route path="/call" element={<CoopPage />} />
        <Route path="/farm" element={<Farm />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="/node/:coopId" element={<NodePage />} />
        <Route path="*" element={<Landing />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
